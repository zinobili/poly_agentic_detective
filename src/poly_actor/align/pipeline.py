"""I/O wrapper: raw Parquet views + pairs.yaml -> per-pair panels in data/clean/.

Reads only data/raw (never modified) and config/pairs.yaml. Output files are derived and
rebuildable; they are written to a temp file and renamed, so a re-run reproduces identical bytes.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from poly_actor.align import events as ev
from poly_actor.align.consts import HOUR_S, MAX_PM_AGE_S, MAX_SPOT_AGE_S, PM_STAMP_TOLERANCE_S
from poly_actor.align.evaluate import EVALUATORS
from poly_actor.align.grid import (
    bar_table,
    build_row_grid,
    epoch_seconds,
    load_sessions,
    restamp_bars,
)
from poly_actor.align.panel import SPOT_SUFFIX, PairInputs, build_panel
from poly_actor.align.prices import PriceBook
from poly_actor.align.stocks import short_day_sessions
from poly_actor.config import CLEAN_DIR, CONFIG_DIR, RAW_DIR
from poly_actor.ingest.common import to_epoch
from poly_actor.ingest.stocks import stock_gap_table
from poly_actor.ingest.targets import stock_tickers
from poly_actor.store.raw_views import create_raw_views

log = logging.getLogger(__name__)

EVENT_BUILDERS: dict[str, Callable[[Mapping], list[ev.Event]]] = {
    "fed_decision": ev.fed_events,
    "us_cpi_inflation": ev.cpi_events,
    "bitcoin_monthly_ladder": ev.btc_events,
    "us_recession": ev.recession_events,
}


def load_config(path: Path | None = None) -> dict:
    with open(path or CONFIG_DIR / "pairs.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def event_tokens(events: list[ev.Event]) -> list[str]:
    """Every Polymarket token an event family may read."""
    tokens: list[str] = []
    for e in events:
        tokens += [b.token for b in e.fed_buckets] + list(e.fed_other_tokens)
        for c in e.cpi_buckets:
            tokens += [c.token] if c.token else []
            tokens += list(c.plus_tokens) + list(c.minus_tokens)
        if e.btc:
            tokens += list(e.btc.token_by_slug.values())
        if e.token:
            tokens.append(e.token)
    return sorted(set(tokens))


def load_polymarket(con: duckdb.DuckDBPyConnection, tokens: list[str]) -> pd.DataFrame:
    """Raw Polymarket observations of `tokens`: key, fidelity, t (epoch s), p."""
    return con.execute(
        "SELECT token_id AS key, fidelity, t, p FROM raw_polymarket_prices "
        "WHERE list_contains(?, token_id)",
        [tokens],
    ).df()


def load_bars(con: duckdb.DuckDBPyConnection, tickers: list[str]) -> pd.DataFrame:
    """Raw start-stamped stock bars of `tickers` (UTC)."""
    return con.execute(
        "SELECT ticker, ts, open, close, ohlc_all_nan FROM raw_stock_bars "
        "WHERE list_contains(?, ticker) ORDER BY ticker, ts",
        [tickers],
    ).df()


def spot_obs(bars: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """24/7 spot bars -> observations stamped at the bar END (start + 1h), value = close."""
    sel = bars[(bars["ticker"] == ticker) & ~bars["ohlc_all_nan"]]
    return pd.DataFrame(
        {"key": ticker, "t": epoch_seconds(sel["ts"]) + HOUR_S, "p": sel["close"].to_numpy()}
    )


def build_pair_inputs(
    cfg: Mapping,
    pair_id: str,
    con: duckdb.DuckDBPyConnection,
    tolerance_s: int = PM_STAMP_TOLERANCE_S,
) -> tuple[PairInputs, dict]:
    """Load and prepare everything for one pair. Returns (inputs, loading diagnostics)."""
    pair = next(p for p in cfg["pairs"] if p["id"] == pair_id)
    events = EVENT_BUILDERS[pair_id](pair)
    tickers = stock_tickers(cfg, [pair_id])
    bars = load_bars(con, tickers)
    start_s = to_epoch(pair["coverage"]["stock_window_start_utc"])
    equities = [t for t in tickers if not t.endswith(SPOT_SUFFIX)]
    last_bar = bars[bars["ticker"].isin(equities)]["ts"].max()
    end_s = int(pd.Timestamp(last_bar).timestamp()) + HOUR_S
    sessions = load_sessions(start_s, end_s)
    table = bar_table(sessions)
    stamped: dict[str, pd.DataFrame] = {}
    unmatched = 0
    for ticker in equities:
        stamped[ticker], bad = restamp_bars(bars[bars["ticker"] == ticker], table)
        unmatched += len(bad)
    gap_table = stock_gap_table(bars[bars["ticker"].isin(equities)][["ticker", "ts"]])
    rows = build_row_grid(start_s, end_s, sessions)
    rows = rows[rows["end_s"] <= max(s["end_s"].max() for s in stamped.values())]
    poly = load_polymarket(con, event_tokens(events))
    spot_frames = [spot_obs(bars, t) for t in tickers if t.endswith(SPOT_SUFFIX)]
    spot_df = pd.concat(spot_frames) if spot_frames else pd.DataFrame(columns=["key", "t", "p"])
    inputs = PairInputs(
        pair_id=pair_id,
        tickers=tickers,
        events=events,
        evaluator=EVALUATORS[pair_id],
        pm_book=PriceBook(poly, MAX_PM_AGE_S, clip=True, tolerance_s=tolerance_s),
        spot_book=PriceBook(spot_df, MAX_SPOT_AGE_S, clip=False),
        rows=rows.reset_index(drop=True),
        sessions=sessions,
        bars=stamped,
        short_days=short_day_sessions(gap_table, equities),
    )
    nan_bars = int(sum(s["nan_bar"].sum() for s in stamped.values()))
    diag = {
        "unmatched_bars": unmatched,
        "nan_bars": nan_bars,
        "pm_observations": len(poly),
        "pm_stamp_tolerance_s": tolerance_s,
    }
    return inputs, diag


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Write Parquet via a temp file and rename (derived data may be overwritten)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def panel_path(pair_id: str, clean_dir: Path = CLEAN_DIR, strict: bool = False) -> Path:
    """Panel file; the strict as-of robustness variant gets a `_strict` suffix."""
    return clean_dir / f"panel_{pair_id}{'_strict' if strict else ''}.parquet"


def run_pair(
    cfg: Mapping,
    pair_id: str,
    con: duckdb.DuckDBPyConnection,
    clean_dir: Path = CLEAN_DIR,
    strict: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Build and write one pair's panel. `strict` uses tolerance 0 (pure at-or-before as-of,
    the step 6 robustness variant). Returns (panel, loading diagnostics)."""
    tolerance_s = 0 if strict else PM_STAMP_TOLERANCE_S
    inputs, diag = build_pair_inputs(cfg, pair_id, con, tolerance_s)
    if diag["unmatched_bars"]:
        log.warning(
            "%s: %d stock bars did not match an XNYS bar start", pair_id, diag["unmatched_bars"]
        )
    panel = build_panel(inputs)
    write_atomic(panel, panel_path(pair_id, clean_dir, strict))
    return panel, diag


def connect_raw(raw_dir: Path = RAW_DIR) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    create_raw_views(con, raw_dir)
    return con


def pair_ids(cfg: Mapping) -> list[str]:
    return [p["id"] for p in cfg["pairs"]]

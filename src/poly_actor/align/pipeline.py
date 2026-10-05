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
from poly_actor.align.consts import HOUR_S, MAX_PM_AGE_S, MAX_SPOT_AGE_S
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
    """Every Polymarket token the event families may read, sorted and unique."""
    return sorted({tok for e in events for tok in e.tokens()})


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


def find_pair(cfg: Mapping, pair_id: str) -> Mapping:
    """The pairs.yaml entry for `pair_id`; a clear error names the known ids."""
    for pair in cfg["pairs"]:
        if pair["id"] == pair_id:
            return pair
    raise ValueError(f"unknown pair id {pair_id!r}; known: {pair_ids(cfg)}")


def _restamped_equities(
    bars: pd.DataFrame, equities: list[str], table: pd.DataFrame
) -> tuple[dict[str, pd.DataFrame], int]:
    """Re-stamp each equity's start-stamped bars to bar ends. Returns (frames, unmatched count)."""
    stamped: dict[str, pd.DataFrame] = {}
    unmatched = 0
    for ticker in equities:
        stamped[ticker], bad = restamp_bars(bars[bars["ticker"] == ticker], table)
        unmatched += len(bad)
    return stamped, unmatched


def _spot_book(bars: pd.DataFrame, tickers: list[str]) -> PriceBook:
    frames = [spot_obs(bars, t) for t in tickers if t.endswith(SPOT_SUFFIX)]
    spot_df = pd.concat(frames) if frames else pd.DataFrame(columns=["key", "t", "p"])
    return PriceBook(spot_df, MAX_SPOT_AGE_S, clip=False)


def build_pair_inputs(
    cfg: Mapping, pair_id: str, con: duckdb.DuckDBPyConnection
) -> tuple[PairInputs, dict]:
    """Load and prepare everything for one pair. Returns (inputs, loading diagnostics)."""
    pair = find_pair(cfg, pair_id)
    events = EVENT_BUILDERS[pair_id](pair)
    tickers = stock_tickers(cfg, [pair_id])
    bars = load_bars(con, tickers)
    start_s = to_epoch(pair["coverage"]["stock_window_start_utc"])
    equities = [t for t in tickers if not t.endswith(SPOT_SUFFIX)]
    equity_bars = bars[bars["ticker"].isin(equities)]
    if equity_bars.empty:
        raise ValueError(f"{pair_id}: no raw stock bars for {equities}; run the stock ingest")
    end_s = int(pd.Timestamp(equity_bars["ts"].max()).timestamp()) + HOUR_S
    sessions = load_sessions(start_s, end_s)
    stamped, unmatched = _restamped_equities(bars, equities, bar_table(sessions))
    gap_table = stock_gap_table(equity_bars[["ticker", "ts"]])
    rows = build_row_grid(start_s, end_s, sessions)
    rows = rows[rows["end_s"] <= max(s["end_s"].max() for s in stamped.values())]
    poly = load_polymarket(con, event_tokens(events))
    inputs = PairInputs(
        pair_id=pair_id,
        tickers=tickers,
        events=events,
        evaluator=EVALUATORS[pair_id],
        pm_book=PriceBook(poly, MAX_PM_AGE_S, clip=True),
        spot_book=_spot_book(bars, tickers),
        rows=rows.reset_index(drop=True),
        sessions=sessions,
        bars=stamped,
        short_days=short_day_sessions(gap_table, equities),
    )
    diag = {
        "unmatched_bars": unmatched,
        "nan_bars": int(sum(s["nan_bar"].sum() for s in stamped.values())),
        "pm_observations": len(poly),
    }
    return inputs, diag


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Write Parquet via a temp file and rename (derived data may be overwritten)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def panel_path(pair_id: str, clean_dir: Path = CLEAN_DIR) -> Path:
    return clean_dir / f"panel_{pair_id}.parquet"


def run_pair(
    cfg: Mapping,
    pair_id: str,
    con: duckdb.DuckDBPyConnection,
    clean_dir: Path = CLEAN_DIR,
) -> tuple[pd.DataFrame, dict]:
    """Build and write one pair's panel. Returns (panel, loading diagnostics)."""
    inputs, diag = build_pair_inputs(cfg, pair_id, con)
    if diag["unmatched_bars"]:
        log.warning(
            "%s: %d stock bars did not match an XNYS bar start", pair_id, diag["unmatched_bars"]
        )
    panel = build_panel(inputs)
    write_atomic(panel, panel_path(pair_id, clean_dir))
    return panel, diag


def connect_raw(raw_dir: Path = RAW_DIR) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    create_raw_views(con, raw_dir)
    return con


def pair_ids(cfg: Mapping) -> list[str]:
    return [p["id"] for p in cfg["pairs"]]

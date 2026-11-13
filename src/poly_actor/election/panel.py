"""Clean panels for the election study (pure builders + one orchestrator).

All timestamps are tz-aware UTC. Odds are read as-of with `align.prices.PriceBook`: the freshest
CLOB point stamped at or before the instant, missing when older than the cap (6 h at a daily
close, 30 min at an hourly bar end, 10 min at a 5-minute bar end). Equity bars are re-stamped to
bar END with `align.grid` (session close and early closes from exchange_calendars). Missing stock
sessions or bars stay missing, never forward-filled.

Tables (data/clean/election/): daily, odds_daily, hourly, odds_hourly, night_5m, vol_daily,
moratorium_daily (parquet) and coverage.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.align.grid import bar_table, epoch_seconds, load_sessions, restamp_bars
from poly_actor.align.prices import PriceBook, Quotes
from poly_actor.align.stocks import bar_log_returns
from poly_actor.election import ingest as ing
from poly_actor.election.config import SIGNALS, ElectionConfig
from poly_actor.pairs import ET

BAR_5M_S = 300  # futures bar length; bars are stamped at start + BAR_5M_S


def utc(seconds) -> pd.Series:
    """Epoch seconds -> tz-aware UTC timestamps."""
    return pd.to_datetime(pd.Series(seconds, dtype="int64"), unit="s", utc=True)


def sessions_in(cfg: ElectionConfig) -> pd.DataFrame:
    """XNYS sessions inside [data_start, data_end): session, open_s, close_s, early."""
    s = load_sessions(cfg.data_start_s, cfg.data_end_s)
    return s[(s["close_s"] > cfg.data_start_s) & (s["open_s"] < cfg.data_end_s)].reset_index(
        drop=True
    )


def build_book(
    points: dict[str, pd.DataFrame],
    max_age_s: int,
    fid: int | None = None,
    closes: dict[str, int | None] | None = None,
) -> PriceBook | ResolvingBook:
    """PriceBook over {key: points(t, p, fidelity)}; `fid` keeps only that fidelity. With
    `closes` ({key: close epoch s or None}) the A1 resolved-market rule is applied."""
    frames = []
    for key, df in points.items():
        d = df if fid is None else df[df["fidelity"] == fid]
        frames.append(d.assign(key=key))
    obs = (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["key", "t", "p"])
    )
    if closes is None:
        return PriceBook(obs, max_age_s)
    return ResolvingBook(PriceBook(obs, max_age_s), PriceBook(obs, NO_CAP_S), closes)


NO_CAP_S = 10**12  # "no age cap" for the last traded price of a resolved market (A1)


class ResolvingBook:
    """As-of with amendment A1: at instants >= the token's close time the price is the last
    traded price at or before the instant (no age cap); before the close the capped book rules.
    `resolved(key, instants)` flags the instants at or after the close."""

    def __init__(self, capped: PriceBook, uncapped: PriceBook, closes: dict[str, int | None]):
        self.capped, self.uncapped, self.closes = capped, uncapped, closes
        self.max_age_s = capped.max_age_s

    def has(self, key: str) -> bool:
        return self.capped.has(key)

    def resolved(self, key: str, instants: np.ndarray) -> np.ndarray:
        c = self.closes.get(key)
        inst = np.asarray(instants, dtype="int64")
        return np.zeros(len(inst), dtype=bool) if c is None else inst >= c

    def asof(self, key: str, instants: np.ndarray) -> Quotes:
        q = self.capped.asof(key, instants)
        res = self.resolved(key, instants)
        if not res.any():
            return q
        last = self.uncapped.asof(key, instants)
        return Quotes(
            np.where(res, last.p, q.p),
            np.where(res, last.age_s, q.age_s),
            np.where(res, last.clipped, q.clipped),
        )


def _resolved(book, key: str, instants: np.ndarray) -> np.ndarray:
    if isinstance(book, ResolvingBook):
        return book.resolved(key, instants)
    return np.zeros(len(instants), dtype=bool)


def asof_long(book: PriceBook, keys: list[str], instants: np.ndarray) -> pd.DataFrame:
    """Long as-of table: one row per (instant, key) with p and age_s (NaN = missing)."""
    parts = []
    for k in keys:
        q = book.asof(k, instants)
        parts.append(
            pd.DataFrame(
                {
                    "i": np.arange(len(instants)),
                    "key": k,
                    "p": q.p,
                    "age_s": q.age_s,
                    "resolved": _resolved(book, k, instants),
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------------------------ stocks


def build_daily(bars: dict[str, pd.DataFrame], sessions: pd.DataFrame) -> pd.DataFrame:
    """One row per (session, ticker): close_ts (real close, early closes included), adjusted
    open and close (same auto_adjust frame), close-to-close log return. A session with no bar
    has NaN close and return, and so has the next session's return (the previous close is
    unknown): no forward-fill."""
    base = sessions[["session", "close_s"]].copy()
    base["close_ts"] = utc(base["close_s"]).to_numpy()
    out = []
    for tk in sorted(bars):
        b = bars[tk]
        px = op = pd.Series(dtype="float64")
        if len(b):
            day = pd.DatetimeIndex(b["ts"]).tz_convert(ET).date
            px = pd.Series(b["close"].to_numpy(), index=day)
            px = px[~px.index.duplicated()]
            if "open" in b:
                op = pd.Series(b["open"].to_numpy(), index=day)
                op = op[~op.index.duplicated()]
        df = base[["session", "close_ts"]].copy()
        df["ticker"] = tk
        df["adj_close"] = df["session"].map(px).astype("float64")
        df["adj_open"] = df["session"].map(op).astype("float64")
        valid = df["adj_close"] > 0
        df.loc[~valid, "adj_close"] = np.nan
        df.loc[~(df["adj_open"] > 0), "adj_open"] = np.nan
        with np.errstate(invalid="ignore", divide="ignore"):
            df["ret"] = np.log(df["adj_close"] / df["adj_close"].shift(1))
        df["missing"] = df["adj_close"].isna()
        out.append(df)
    return pd.concat(out, ignore_index=True)


def build_odds_daily(book: PriceBook, keys: list[str], sessions: pd.DataFrame) -> pd.DataFrame:
    """Per session and signal: p as-of the real close, its age, and dp vs the previous session's
    reading (missing if either reading is missing)."""
    inst = sessions["close_s"].to_numpy(dtype="int64")
    long = asof_long(book, keys, inst)
    out = pd.DataFrame(
        {
            "session": sessions["session"].to_numpy()[long["i"]],
            "close_ts": utc(inst[long["i"]]).to_numpy(),
            "signal": long["key"],
            "p": long["p"],
            "age_s": long["age_s"],
            "resolved": long["resolved"],
        }
    )
    out["dp"] = out.groupby("signal", sort=False)["p"].diff()
    return out.sort_values(["signal", "session"]).reset_index(drop=True)


def build_hourly(
    bars: dict[str, pd.DataFrame], sessions: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Regular-session 1h bars stamped at bar END with the within-bar log return (no overnight
    return). Returns (panel, unmatched bars). Bars off the expected grid are never shifted."""
    table = bar_table(sessions)
    panels, odd = [], []
    for tk in sorted(bars):
        b = bars[tk].assign(ticker=tk)
        stamped, unmatched = restamp_bars(b, table)
        stamped["ret"] = bar_log_returns(stamped)
        panels.append(
            pd.DataFrame(
                {
                    "ticker": tk,
                    "session": stamped["session"],
                    "bar_start_ts": utc(stamped["start_s"]).to_numpy(),
                    "bar_end_ts": utc(stamped["end_s"]).to_numpy(),
                    "open": stamped["open"],
                    "close": stamped["close"],
                    "ret": stamped["ret"],
                    "nan_bar": stamped["nan_bar"],
                }
            )
        )
        odd.append(unmatched[["ticker", "ts"]] if len(unmatched) else unmatched.iloc[:0])
    panel = pd.concat(panels, ignore_index=True).sort_values(["ticker", "bar_end_ts"])
    return panel.reset_index(drop=True), pd.concat(odd, ignore_index=True)


def build_odds_hourly(book: PriceBook, keys: list[str], sessions: pd.DataFrame) -> pd.DataFrame:
    """Per signal, p as-of each expected bar end; dp vs the previous bar end of the same session
    (the first bar of a session has no dp)."""
    bars = bar_table(sessions)
    inst = bars["end_s"].to_numpy(dtype="int64")
    long = asof_long(book, keys, inst)
    out = pd.DataFrame(
        {
            "session": bars["session"].to_numpy()[long["i"]],
            "bar_end_ts": utc(inst[long["i"]]).to_numpy(),
            "signal": long["key"],
            "p": long["p"],
            "age_s": long["age_s"],
            "resolved": long["resolved"],
        }
    )
    out = out.sort_values(["signal", "bar_end_ts"])
    out["dp"] = out.groupby(["signal", "session"], sort=False)["p"].diff()
    return out.reset_index(drop=True)


def build_night(
    fut5m: dict[str, pd.DataFrame], book: PriceBook, keys: list[str], cfg: ElectionConfig
) -> pd.DataFrame:
    """Futures 5-minute bars stamped at bar END (start + 5 min; futures have no XNYS session)
    around the H3 window, with odds as-of each bar end (fid-1 points only, cap 10 min) and the
    5-minute dp against the previous consecutive bar (after a market's close, A1: last traded
    price, so dp = 0). `in_window` marks the H3 window itself."""
    lo, hi = cfg.h3_window
    m = cfg.h3_margin_s
    parts = []
    for tk in sorted(fut5m):
        b = fut5m[tk]
        if not len(b):
            continue
        start = epoch_seconds(b["ts"])
        end = start + BAR_5M_S
        keep = (end > lo - m) & (end <= hi + m)
        d = pd.DataFrame({"ticker": tk, "start_s": start[keep], "end_s": end[keep]})
        o, c = b["open"].to_numpy()[keep], b["close"].to_numpy()[keep]
        with np.errstate(invalid="ignore", divide="ignore"):
            d["ret"] = np.where((o > 0) & (c > 0), np.log(c / o), np.nan)
        d["open"], d["close"] = o, c
        parts.append(d.sort_values("end_s"))
    head = ["ticker", "bar_start_ts", "bar_end_ts", "in_window", "open", "close", "ret"]
    cols = head + [c for k in keys for c in (k, f"age_{k}", f"d{k}", f"res_{k}")]
    if not parts:
        return pd.DataFrame(columns=cols)
    out = pd.concat(parts, ignore_index=True)
    inst = out["end_s"].to_numpy(dtype="int64")
    for k in keys:
        q = book.asof(k, inst)
        out[k], out[f"age_{k}"] = q.p, q.age_s
        out[f"res_{k}"] = _resolved(book, k, inst)
        consecutive = out.groupby("ticker")["end_s"].diff() == BAR_5M_S
        out[f"d{k}"] = out.groupby("ticker")[k].diff().where(consecutive)
    out["in_window"] = (out["end_s"] > lo) & (out["end_s"] <= hi)
    out["bar_start_ts"] = utc(out["start_s"]).to_numpy()
    out["bar_end_ts"] = utc(out["end_s"]).to_numpy()
    return out[cols].reset_index(drop=True)


def build_vol(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily closes of the vol indices and ^NDX, keyed by their ET trading date."""
    parts = []
    for tk in sorted(bars):
        b = bars[tk]
        if len(b):
            day = pd.DatetimeIndex(b["ts"]).tz_convert(ET).date
            parts.append(pd.DataFrame({"date": day, "ticker": tk, "close": b["close"].to_numpy()}))
    cols = ["date", "ticker", "close"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def build_moratorium(book: PriceBook, states: list[str], sessions: pd.DataFrame) -> pd.DataFrame:
    """Per session, per-state p as-of the close, the cross-state mean over the states with a
    reading, how many there were, and the mean of per-state changes (same-state pairs only)."""
    inst = sessions["close_s"].to_numpy(dtype="int64")
    out = pd.DataFrame(
        {"session": sessions["session"].to_numpy(), "close_ts": utc(inst).to_numpy()}
    )
    dps = []
    for s in states:
        q = book.asof(s, inst)
        out[f"p_{s}"], out[f"age_{s}"] = q.p, q.age_s
        dps.append(out[f"p_{s}"].diff())
    p = out[[f"p_{s}" for s in states]]
    out["mean_p"] = p.mean(axis=1)
    out["n_states"] = p.notna().sum(axis=1)
    out["mean_dp"] = pd.concat(dps, axis=1).mean(axis=1)
    first = out["n_states"].gt(0).idxmax() if (out["n_states"] > 0).any() else len(out)
    return out.iloc[first:].reset_index(drop=True)


# ------------------------------------------------------------------------------------ driver


def load_points(cfg: ElectionConfig, raw_dir: Path) -> dict[str, pd.DataFrame]:
    """CLOB points per signal / state name."""
    out = {}
    for name, m in {**cfg.signals, **cfg.moratorium}.items():
        out[name] = ing.read_clob_points(raw_dir, m.token_id)
    return out


def load_bars(raw_dir: Path, tickers: list[str], interval: str) -> dict[str, pd.DataFrame]:
    return {tk: ing.read_yf_bars(raw_dir, tk, interval) for tk in tickers}


def build_all(cfg: ElectionConfig, raw_dir: Path, clean_dir: Path) -> dict:
    """Build every table from raw, write parquet + coverage.json, return the coverage dict."""
    from poly_actor.election.coverage import coverage_report

    sessions = sessions_in(cfg)
    pts = load_points(cfg, raw_dir)
    sig_pts = {k: pts[k] for k in SIGNALS}
    mor_pts = {k: pts[k] for k in cfg.moratorium}
    sig = list(SIGNALS)
    closes = {k: cfg.signals[k].closed_s for k in sig}  # A1 resolved-market rule
    eq = cfg.equity_tickers
    hourly, unmatched = build_hourly(load_bars(raw_dir, eq, "1h"), sessions)
    tables = {
        "daily": build_daily(load_bars(raw_dir, eq, "1d"), sessions),
        "odds_daily": build_odds_daily(
            build_book(sig_pts, cfg.max_age["daily"], closes=closes), sig, sessions
        ),
        "hourly": hourly,
        "odds_hourly": build_odds_hourly(
            build_book(sig_pts, cfg.max_age["hourly"], closes=closes), sig, sessions
        ),
        "night_5m": build_night(
            load_bars(raw_dir, cfg.futures, "5m"),
            build_book(sig_pts, cfg.max_age["night"], fid=1, closes=closes),
            sig,
            cfg,
        ),
        "vol_daily": build_vol(load_bars(raw_dir, cfg.vol_indices, "1d")),
        "moratorium_daily": build_moratorium(
            build_book(mor_pts, cfg.max_age["daily"]), list(cfg.moratorium), sessions
        ),
    }
    clean_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(clean_dir / f"{name}.parquet", index=False)
    cov = coverage_report(cfg, tables, sessions, unmatched, pts)
    (clean_dir / "coverage.json").write_text(
        json.dumps(cov, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return cov

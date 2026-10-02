"""Assemble the hourly UTC panel of one pair (pure; inputs are already-loaded frames).

One row per window (start, end], stamped by `ts_end` (UTC). Inside XNYS sessions the rows are the
stock bars; outside sessions they are whole UTC hours (see `grid`). Every value in a row uses only
observations stamped at or before `ts_end`:
- signal_level / signal_change: Polymarket as-of levels spliced across rolls (`splice`);
- ret_<TICKER>: equity bar log(close/open) (known at the bar end); NaN outside session bars;
- ret_BTC-USD: log of the as-of spot at `ts_end` over the as-of spot at `ts_start`
  (hourly bars, close known at the bar end, so at a :30 stamp the latest close is up to 30
  minutes old);
- overnight_gap_<TICKER> / pm_overnight_change on the first bar row of each session.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from poly_actor.align.consts import OUTAGE_WINDOWS_UTC
from poly_actor.align.evaluate import Evaluator
from poly_actor.align.events import Event
from poly_actor.align.prices import PriceBook
from poly_actor.align.splice import spliced_signal
from poly_actor.align.stocks import bar_log_returns, session_gap_returns
from poly_actor.ingest.common import to_epoch

SPOT_SUFFIX = "-USD"


@dataclass(frozen=True)
class PairInputs:
    """Everything `build_panel` needs for one pair."""

    pair_id: str
    tickers: list[str]  # real symbols: equities plus any 24/7 spot series (e.g. BTC-USD)
    events: list[Event]
    evaluator: Evaluator
    pm_book: PriceBook
    spot_book: PriceBook
    rows: pd.DataFrame  # `grid.build_row_grid` output
    sessions: pd.DataFrame  # `grid.load_sessions` output
    bars: dict[str, pd.DataFrame]  # ticker -> end-stamped equity bars (`grid.restamp_bars`)
    short_days: set  # session dates with missing bars for any equity of the pair


def _ts(seconds: np.ndarray) -> pd.DatetimeIndex:
    return pd.to_datetime(seconds, unit="s", utc=True)


def outage_mask(start_s: np.ndarray, end_s: np.ndarray) -> np.ndarray:
    """True where the window (start, end] overlaps a known upstream outage."""
    mask = np.zeros(len(end_s), dtype=bool)
    for lo, hi in OUTAGE_WINDOWS_UTC:
        mask |= (start_s < to_epoch(hi)) & (end_s > to_epoch(lo))
    return mask


def spot_returns(spot: PriceBook, key: str, start_s: np.ndarray, end_s: np.ndarray) -> np.ndarray:
    """log(spot at end / spot at start), each an as-of lookup (<= the instant)."""
    last, first = spot.asof(key, end_s).p, spot.asof(key, start_s).p
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((last > 0) & (first > 0), np.log(last / first), np.nan)


def overnight_pm_change(is_session_bar: np.ndarray, is_open: np.ndarray, change: np.ndarray):
    """Sum of spliced PM changes over the non-session rows between the previous session's close
    and each session open, placed on the open row. NaN when any change in between is missing
    or there is no previous session. Returns (sum, n_missing)."""
    seg = np.cumsum(is_session_bar)
    frame = pd.DataFrame({"seg": seg, "change": change})[~is_session_bar]
    grouped = frame.groupby("seg")["change"]
    total = grouped.apply(lambda c: c.sum(min_count=len(c))).rename("total")
    missing = grouped.apply(lambda c: int(c.isna().sum())).rename("missing")
    prior = seg - 1  # rows before this open share the segment count of the previous close
    has_prior = is_open & (prior >= 1)
    out_sum = np.full(len(change), np.nan)
    out_missing = np.zeros(len(change), dtype="int64")
    sums = pd.Series(prior).map(total).to_numpy(dtype="float64")
    miss = pd.Series(prior).map(missing).to_numpy(dtype="float64")
    out_sum[has_prior] = sums[has_prior]
    out_missing[has_prior] = np.nan_to_num(miss[has_prior], nan=0).astype("int64")
    return out_sum, out_missing


def _add_ticker_columns(panel: pd.DataFrame, inp: PairInputs) -> None:
    """ret_<TICKER> for every ticker and overnight_gap_<TICKER> for equities (in place)."""
    rows = inp.rows
    start_s, end_s = rows["start_s"].to_numpy(), rows["end_s"].to_numpy()
    for ticker in inp.tickers:
        if ticker.endswith(SPOT_SUFFIX):
            panel[f"ret_{ticker}"] = spot_returns(inp.spot_book, ticker, start_s, end_s)
            continue
        bars = inp.bars[ticker].copy()
        bars["ret"] = bar_log_returns(bars)
        by_end = bars.set_index("end_s")["ret"]
        values = pd.Series(end_s).map(by_end).to_numpy(dtype="float64")
        panel[f"ret_{ticker}"] = np.where(rows["is_session_bar"], values, np.nan)
        gaps = session_gap_returns(bars, inp.sessions).set_index("session")["gap_ret"]
        mapped = rows["session"].map(gaps).to_numpy(dtype="float64")
        panel[f"overnight_gap_{ticker}"] = np.where(rows["is_session_open"], mapped, np.nan)


def build_panel(inp: PairInputs) -> pd.DataFrame:
    """Hourly UTC panel for one pair. See the module docstring for column semantics."""
    rows = inp.rows
    start_s = rows["start_s"].to_numpy(dtype="int64")
    end_s = rows["end_s"].to_numpy(dtype="int64")
    signal = spliced_signal(inp.events, inp.evaluator, inp.pm_book, inp.spot_book, start_s, end_s)
    panel = pd.DataFrame(
        {
            "ts_end": _ts(end_s),
            "ts_start": _ts(start_s),
            "window_minutes": rows["window_minutes"].to_numpy(),
            "is_session_bar": rows["is_session_bar"].to_numpy(),
            "is_session_open": rows["is_session_open"].to_numpy(),
            "session": rows["session"].to_numpy(),
        }
    )
    panel = pd.concat([panel, signal], axis=1)
    panel["outage_mask"] = outage_mask(start_s, end_s)
    panel["short_day"] = rows["session"].isin(inp.short_days).to_numpy()
    _add_ticker_columns(panel, inp)
    total, n_missing = overnight_pm_change(
        rows["is_session_bar"].to_numpy(),
        rows["is_session_open"].to_numpy(),
        panel["signal_change"].to_numpy(dtype="float64"),
    )
    panel["pm_overnight_change"] = total
    panel["pm_overnight_n_missing"] = n_missing
    equity_returns = [f"ret_{t}" for t in inp.tickers if not t.endswith(SPOT_SUFFIX)]
    panel["both_trading"] = (
        panel["is_session_bar"]
        & panel[equity_returns].notna().all(axis=1)
        & panel["signal_level"].notna()
        & panel["signal_change"].notna()
    )
    return panel

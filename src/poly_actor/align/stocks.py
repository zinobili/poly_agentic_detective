"""Stock-side features: bar log returns, opening gaps and short-day flags (pure).

Returns are over the bar's own window: log(close / open) of the end-stamped bar, known at its
end. The opening gap of a session is log(open of the first bar / close of the previous
session's last bar); it needs both bars to exist (Yahoo holes give NaN, never a fill).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def bar_log_returns(stamped: pd.DataFrame) -> pd.Series:
    """log(close/open) per bar; NaN for all-NaN bars or non-positive prices."""
    open_, close = stamped["open"].to_numpy(), stamped["close"].to_numpy()
    valid = ~stamped["nan_bar"].to_numpy() & (open_ > 0) & (close > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(valid, np.log(close / open_), np.nan)
    return pd.Series(ret, index=stamped.index)


def session_gap_returns(stamped: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Opening gap per (session): log(first bar open / previous session's last bar close).

    `stamped`: one ticker's end-stamped bars (session, start_s, end_s, open, close, nan_bar).
    `sessions`: session, open_s, close_s (consecutive XNYS sessions). Returns columns session,
    gap_ret (NaN when the first bar of this session or the last bar of the previous one is
    missing or all-NaN)."""
    good = stamped[~stamped["nan_bar"]]
    first = good.merge(sessions[["session", "open_s"]], on="session")
    first = first[first["start_s"] == first["open_s"]].set_index("session")["open"]
    last = good.merge(sessions[["session", "close_s"]], on="session")
    last = last[last["end_s"] == last["close_s"]].set_index("session")["close"]
    out = sessions[["session"]].copy()
    prev_session = sessions["session"].shift(1)
    open_now = out["session"].map(first)
    close_prev = prev_session.map(last)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["gap_ret"] = np.where(
            (open_now > 0) & (close_prev > 0), np.log(open_now / close_prev), np.nan
        )
    return out


def short_day_sessions(gap_table: pd.DataFrame, tickers: list[str]) -> set:
    """Session dates on which any of `tickers` has fewer bars than expected (from
    `ingest.stocks.stock_gap_table`, kind == 'xnys_session')."""
    sel = gap_table[(gap_table["kind"] == "xnys_session") & gap_table["ticker"].isin(tickers)]
    return set(sel["date"])

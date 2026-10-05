"""Time grid: XNYS sessions, bar re-stamping and the tiled row grid of the panel.

Yahoo 1h equity bars are START-stamped (09:30, 10:30, ... 15:30 ET). A bar is only known at its
END, so every bar is re-stamped to its end: start+1h, except the last bar of a session, which
ends at the official close (16:00 ET; the 15:30 bar is 30 minutes long). On early-close
sessions (13:00 ET) Yahoo omits the 12:30 stub, so the 11:30 bar runs to the close
(`early_closes` from exchange_calendars, never hard-coded hours).

The panel rows tile the timeline without overlap. A row is the half-open window (start, end]
and is stamped by its end. Inside a session the rows are exactly the bars; outside sessions
they are the UTC whole hours, plus one stub row ending at each session open. All instants are
epoch seconds (UTC).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from poly_actor.align.consts import HOUR_S, STUB_BAR_MAX_S

SESSION_COLS = ["session", "open_s", "close_s", "early"]
BAR_COLS = ["session", "start_s", "end_s"]


def epoch_seconds(ts: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Tz-aware timestamps (any unit) -> int64 epoch seconds. Naive input is rejected."""
    idx = pd.DatetimeIndex(ts)
    if idx.tz is None:
        raise ValueError("naive timestamps are not allowed (UTC everywhere)")
    return ((idx - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(dtype="int64")


def load_sessions(start_s: int, end_s: int) -> pd.DataFrame:
    """XNYS sessions overlapping [start_s, end_s] with UTC open/close (thin calendar wrapper).

    Early closes come from `cal.early_closes`. Returns columns session, open_s, close_s, early."""
    import exchange_calendars as xcals

    cal = xcals.get_calendar("XNYS")
    first = pd.Timestamp(start_s - 2 * 86400, unit="s").normalize()
    last = pd.Timestamp(end_s + 2 * 86400, unit="s").normalize()
    sessions = cal.sessions_in_range(first, last)
    early = {d.date() for d in cal.early_closes}
    rows = [
        (s.date(), int(cal.session_open(s).timestamp()), int(cal.session_close(s).timestamp()))
        for s in sessions
    ]
    frame = pd.DataFrame(rows, columns=["session", "open_s", "close_s"])
    frame["early"] = frame["session"].isin(early)
    return frame[SESSION_COLS]


def session_bar_edges(open_s: int, close_s: int, early: bool) -> list[tuple[int, int]]:
    """Expected (start, end) of every Yahoo 1h bar of one session, end-stamped.

    Regular 09:30-16:00 ET: 7 bars, the last 30 minutes long. Early close (13:00 ET): 3 bars; the
    stub starting 30 minutes before the close is omitted and the previous bar ends at the close."""
    starts = list(range(open_s, close_s, HOUR_S))
    if early:
        starts = [s for s in starts if close_s - s > STUB_BAR_MAX_S]
    edges = [(s, min(s + HOUR_S, close_s)) for s in starts]
    if early and edges:
        edges[-1] = (edges[-1][0], close_s)
    return edges


def bar_table(sessions: pd.DataFrame) -> pd.DataFrame:
    """One row per expected equity bar: session, start_s, end_s."""
    rows = [
        (r.session, s, e)
        for r in sessions.itertuples()
        for s, e in session_bar_edges(r.open_s, r.close_s, r.early)
    ]
    return pd.DataFrame(rows, columns=BAR_COLS)


def restamp_bars(bars: pd.DataFrame, table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Start-stamped bars -> end-stamped bars using the expected-bar table.

    `bars`: ticker, ts (tz-aware bar START), open, close, ohlc_all_nan. Returns
    (stamped, unmatched). `stamped` adds start_s, end_s, session and `nan_bar`; bars whose start
    is not an expected bar start (data oddity) go to `unmatched`, never silently shifted."""
    work = bars.copy()
    work["start_s"] = epoch_seconds(work["ts"]) if len(work) else np.array([], dtype="int64")
    merged = work.merge(table, on="start_s", how="left")
    matched = merged["end_s"].notna()
    stamped = merged[matched].copy()
    stamped["end_s"] = stamped["end_s"].astype("int64")
    stamped["nan_bar"] = stamped["ohlc_all_nan"].astype(bool)
    return stamped.reset_index(drop=True), merged[~matched].reset_index(drop=True)


def row_endpoints(start_s: int, end_s: int, sessions: pd.DataFrame) -> np.ndarray:
    """Sorted unique window boundaries in [start_s, end_s]: whole UTC hours outside session
    interiors, plus each session open and every bar end inside it."""
    first_hour = -(-start_s // HOUR_S) * HOUR_S  # ceil to a whole hour
    hours = np.arange(first_hour, end_s + 1, HOUR_S)
    keep = np.ones(len(hours), dtype=bool)
    extra: list[int] = [start_s]
    for r in sessions.itertuples():
        keep &= ~((hours > r.open_s) & (hours < r.close_s))
        extra.append(r.open_s)
        extra.extend(e for _, e in session_bar_edges(r.open_s, r.close_s, r.early))
    points = np.unique(np.concatenate([hours[keep], np.array(extra, dtype="int64")]))
    return points[(points >= start_s) & (points <= end_s)]


def build_row_grid(start_s: int, end_s: int, sessions: pd.DataFrame) -> pd.DataFrame:
    """Tiled panel rows (start_s, end_s] with session flags.

    Columns: start_s, end_s, window_minutes, is_session_bar, is_session_open, session (the ET
    session date for session bars, else None)."""
    points = row_endpoints(start_s, end_s, sessions)
    rows = pd.DataFrame({"start_s": points[:-1], "end_s": points[1:]})
    table = bar_table(sessions)
    bars = table.rename(columns={"start_s": "bar_start_s", "end_s": "end_s"})
    merged = rows.merge(bars, on="end_s", how="left")
    is_bar = merged["bar_start_s"].notna() & (merged["bar_start_s"] == merged["start_s"])
    merged["is_session_bar"] = is_bar
    first_bar = table.groupby("session")["start_s"].min()
    open_starts = set(first_bar.to_numpy())
    merged["is_session_open"] = is_bar & merged["start_s"].isin(open_starts)
    merged["session"] = merged["session"].where(is_bar, None)
    merged["window_minutes"] = (merged["end_s"] - merged["start_s"]) // 60
    cols = ["start_s", "end_s", "window_minutes", "is_session_bar", "is_session_open", "session"]
    return merged[cols].astype({"session": "object"})

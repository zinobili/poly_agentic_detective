"""Active-event assignment and change-splicing of the Polymarket signal (pure).

Rule (config/pairs.yaml `splice_rule`, pre-registration): a level of event A is never
differenced against a level of event B. For a row with window (start, end] the event is the one
active at `end` (use_from < end <= use_until, so a row ending exactly at the roll is the OLD
event's last row); the change is that event's level at `end` minus the SAME event's level at
`start`. When the active event changes inside the window the new event's own change is used and
`roll_hour` is set. Windows that start exactly at a roll time are flagged too (the bar the
pre-registration calls "the bar starting at the roll time").
`pm_obs_ts` is ts_end minus the largest age among the quotes used, i.e. the OLDEST quote.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from poly_actor.align.consts import NO_EVENT, OK, START_UNAVAILABLE
from poly_actor.align.evaluate import Evaluator
from poly_actor.align.events import Event, active_index, roll_times
from poly_actor.align.prices import PriceBook

BOOL_EXTRAS = ("pav_pooled", "cpi_clip_binding", "cpi_has_derived", "edge_mass_strict_ok")
INT_EXTRAS = ("n_up", "n_dip", "n_partial")


def _count_in(sorted_values: np.ndarray, lo: np.ndarray, hi: np.ndarray, closed: str) -> np.ndarray:
    """Number of values v with lo < v <= hi (closed='right') or lo <= v < hi (closed='left')."""
    side = "right" if closed == "right" else "left"
    return np.searchsorted(sorted_values, hi, side=side) - np.searchsorted(
        sorted_values, lo, side=side
    )


def evaluate_rows(
    events: list[Event],
    evaluator: Evaluator,
    book: PriceBook,
    spot: PriceBook,
    event_idx: np.ndarray,
    instants: np.ndarray,
    which: np.ndarray | None = None,
) -> pd.DataFrame:
    """Evaluate `events[event_idx[j]]` at `instants[j]` for every j in `which` (default all rows
    with an active event). Returns a frame indexed by row position j."""
    rows = np.flatnonzero(event_idx >= 0) if which is None else which
    parts = []
    for i in np.unique(event_idx[rows]):
        sel = rows[event_idx[rows] == i]
        res = evaluator(events[i], book, spot, instants[sel])
        res.index = sel
        parts.append(res)
    return pd.concat(parts) if parts else pd.DataFrame()


def spliced_signal(
    events: list[Event],
    evaluator: Evaluator,
    book: PriceBook,
    spot: PriceBook,
    start_s: np.ndarray,
    end_s: np.ndarray,
) -> pd.DataFrame:
    """Signal level, spliced change and event flags per row window (start_s, end_s].

    Columns: event_id, signal_level, signal_reason, signal_change, roll_hour, event_hour,
    pm_obs_ts, pm_obs_age_s, pm_used_tolerance, clipped_p_gt1, plus the evaluator's
    diagnostics (NaN/False where no event)."""
    n = len(end_s)
    active = active_index(events, end_s)
    at_end = evaluate_rows(events, evaluator, book, spot, active, end_s)
    frame = at_end.reindex(range(n))
    for col in BOOL_EXTRAS:
        if col in frame:
            frame[col] = frame[col].fillna(False).astype(bool)
    for col in INT_EXTRAS:
        if col in frame:
            frame[col] = frame[col].fillna(0).astype("int64")
    frame["clipped"] = frame["clipped"].fillna(False).astype(bool)
    frame["used_tol"] = frame["used_tol"].fillna(False).astype(bool)
    frame["reason"] = frame["reason"].where(active >= 0, NO_EVENT)

    level_end = frame["level"].to_numpy(dtype="float64")
    level_start = np.full(n, np.nan)
    # Same event as the previous row: the previous row's end level IS this row's start level.
    reuse = np.zeros(n, dtype=bool)
    reuse[1:] = (active[1:] == active[:-1]) & (active[1:] >= 0)
    level_start[1:][reuse[1:]] = level_end[:-1][reuse[1:]]
    need = np.flatnonzero((active >= 0) & ~reuse)
    at_start = evaluate_rows(events, evaluator, book, spot, active, start_s, which=need)
    if len(at_start):
        level_start[at_start.index.to_numpy()] = at_start["level"].to_numpy(dtype="float64")

    change = level_end - level_start
    reason = frame["reason"].to_numpy(dtype=object)
    lost_start = np.isnan(level_start) & ~np.isnan(level_end)
    reason = np.where(lost_start & (reason == OK), START_UNAVAILABLE, reason)

    rolls = roll_times(events)
    event_times = np.sort(
        np.array([e.event_time_s for e in events if e.event_time_s is not None], dtype="int64")
    )
    age = frame["age_s"].to_numpy(dtype="float64")
    out = pd.DataFrame(
        {
            "event_id": [events[i].id if i >= 0 else None for i in active],
            "signal_level": level_end,
            "signal_reason": reason,
            "signal_change": change,
            "roll_hour": _count_in(rolls, start_s, end_s, "left") > 0,
            "event_hour": _count_in(event_times, start_s, end_s, "right") > 0,
            "pm_obs_ts": pd.to_datetime(end_s - age, unit="s", utc=True),
            "pm_obs_age_s": age,
            "pm_used_tolerance": frame["used_tol"].to_numpy(),
            "clipped_p_gt1": frame["clipped"].to_numpy(),
        }
    )
    extras = [
        c for c in frame.columns if c not in ("level", "reason", "age_s", "clipped", "used_tol")
    ]
    return pd.concat([out, frame[extras].reset_index(drop=True)], axis=1)

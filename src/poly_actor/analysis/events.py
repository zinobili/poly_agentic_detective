"""Event studies: Chart 2 paths (A27 rule 13), random-date bands (rule 11) and the pair-4
descriptive study (rule 5). Pure functions on a `SessionGrid` and per-session series.

Event time is counted in session bars. Bar 0 is the first bar ending after the event; the
event is signed by sign(ΔPM) in the bar before bar 0 and events whose |ΔPM| is below the
threshold are unsigned and excluded (their count is reported). A window that crosses a close
includes that session's opening gap. When every event crosses at the same place (Fed, CPI)
the gap is its own step labelled "gap"; when the crossing varies (BTC), the gap is folded
into the first bar of the new session and marked on that event's path.

Paths are cumulative log returns in percent (x 100). Intervals are 90% BCa over events.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poly_actor.analysis.models import bca_ci
from poly_actor.analysis.sample import SessionGrid

BAND_DRAWS = 1000
BAND_LEVEL = 0.90
MIN_EVENTS = 5  # below this no mean or interval is drawn
PCT = 100.0
GAP = "gap"


@dataclass(frozen=True)
class EventPath:
    session: int  # session index of bar 0
    pos: int  # bar position of bar 0
    sign: float  # +1 / -1
    labels: tuple[str, ...]
    steps: np.ndarray  # per-step log returns (not cumulative)
    gap_marks: tuple[int, ...]  # step indices that include a folded opening gap


def flat_cells(grid: SessionGrid) -> list[tuple[int, int]]:
    s_idx, p_idx = np.nonzero(grid.exists)
    return list(zip(s_idx.tolist(), p_idx.tolist(), strict=True))


def event_path(
    grid: SessionGrid,
    y: np.ndarray,
    gaps: np.ndarray,
    cells: list[tuple[int, int]],
    where: dict[tuple[int, int], int],
    bar0: tuple[int, int],
    pre: int,
    post: int,
    sign: float,
) -> EventPath | None:
    """Steps from bar -pre to bar +post around bar 0 (None when any return is missing)."""
    i0 = where[bar0]
    if i0 - pre < 0 or i0 + post >= len(cells):
        return None
    labels: list[str] = []
    steps: list[float] = []
    prev_s = None
    for rel in range(-pre, post + 1):
        s, p = cells[i0 + rel]
        if prev_s is not None and s != prev_s:
            labels.append(GAP)
            steps.append(gaps[s])
        labels.append(f"{rel:+d}" if rel else "0")
        steps.append(y[s, p])
        prev_s = s
    arr = np.array(steps, dtype="float64")
    if np.isnan(arr).any():
        return None
    return EventPath(bar0[0], bar0[1], sign, tuple(labels), arr, ())


def fold_gaps(path: EventPath) -> EventPath:
    """Merge every explicit gap step into the following bar and mark that bar."""
    labels, steps, marks = list(path.labels), list(path.steps), []
    while GAP in labels:
        i = labels.index(GAP)
        steps[i + 1] += steps[i]
        del labels[i], steps[i]
        marks.append(i)
    return EventPath(
        path.session, path.pos, path.sign, tuple(labels), np.array(steps), tuple(marks)
    )


def gap_first_path(
    grid: SessionGrid, y: np.ndarray, gaps: np.ndarray, session: int, post: int, sign: float
) -> EventPath | None:
    """CPI layout: the opening gap of `session`, then bars 0..post of that session."""
    vals = [gaps[session]] + [y[session, p] for p in range(post + 1)]
    if not grid.exists[session, : post + 1].all():
        return None
    arr = np.array(vals, dtype="float64")
    if np.isnan(arr).any():
        return None
    labels = (GAP, *(f"{p:+d}" if p else "0" for p in range(post + 1)))
    return EventPath(session, 0, sign, labels, arr, ())


def sign_of(x: float, threshold: float) -> float:
    """+1/-1, or 0 when the move is below the threshold or missing (unsigned)."""
    if np.isnan(x) or abs(x) < threshold:
        return 0.0
    return float(np.sign(x))


@dataclass(frozen=True)
class EventStudyOut:
    labels: tuple[str, ...]
    mean: np.ndarray
    ci_low: np.ndarray
    ci_high: np.ndarray
    band_low: np.ndarray | None
    band_high: np.ndarray | None
    paths: np.ndarray  # (n, steps) signed cumulative percent
    gap_marks: list[list[int]]
    event_ts: list[int]
    n_unsigned: int
    n_dropped: int

    def as_contract(self, unit: str) -> dict:
        out = {
            "unit": unit,
            "steps": list(self.labels),
            "mean": _list(self.mean),
            "ci_low": _list(self.ci_low),
            "ci_high": _list(self.ci_high),
            "paths": [_list(p) for p in self.paths],
            "gap_marks": self.gap_marks,
            "n_unsigned": self.n_unsigned,
            "n_dropped": self.n_dropped,
        }
        if self.band_low is not None:
            out["band_low"], out["band_high"] = _list(self.band_low), _list(self.band_high)
        return out


def _list(a: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(a, dtype="float64")]


def cumulative_signed(paths: list[EventPath]) -> np.ndarray:
    return np.stack([p.sign * np.cumsum(p.steps) * PCT for p in paths])


def summarise(
    paths: list[EventPath],
    band: tuple[np.ndarray, np.ndarray] | None,
    event_ts: list[int],
    n_unsigned: int,
    n_dropped: int,
) -> EventStudyOut | None:
    """Mean signed cumulative path with a 90% BCa interval; None below MIN_EVENTS."""
    if len(paths) < MIN_EVENTS:
        return None
    cum = cumulative_signed(paths)
    low, high = bca_ci(cum, lambda a: a.mean(axis=0))
    return EventStudyOut(
        paths[0].labels,
        cum.mean(axis=0),
        low,
        high,
        band[0] if band else None,
        band[1] if band else None,
        cum,
        [list(p.gap_marks) for p in paths],
        event_ts,
        n_unsigned,
        n_dropped,
    )


def random_band(
    pool: list[EventPath], n: int, seed: int, draws: int = BAND_DRAWS
) -> tuple[np.ndarray, np.ndarray] | None:
    """90% band of the mean signed path over `draws` random sets of n non-event paths."""
    if len(pool) < n or n < 1:
        return None
    cum = cumulative_signed(pool)
    rng = np.random.default_rng(seed)
    means = np.stack([cum[rng.choice(len(pool), n, replace=False)].mean(0) for _ in range(draws)])
    lo, hi = np.quantile(means, [(1 - BAND_LEVEL) / 2, (1 + BAND_LEVEL) / 2], axis=0)
    return lo, hi


def same_layout(paths: list[EventPath]) -> list[EventPath]:
    """Keep the paths that share the most common step layout (explicit gap steps)."""
    if not paths:
        return paths
    layouts = [p.labels for p in paths]
    common = max(set(layouts), key=layouts.count)
    return [p for p in paths if p.labels == common]


# ---------------------------------------------------------------- pair 4 (rule 5)


def greedy_extremes(values: np.ndarray, k: int, min_gap: int, largest: bool) -> list[int]:
    """Indices of the k largest (or smallest) values, each at least `min_gap` positions from
    every one already chosen; NaN skipped."""
    order = np.argsort(-values if largest else values, kind="stable")
    chosen: list[int] = []
    for i in order:
        if np.isnan(values[i]):
            continue
        if all(abs(int(i) - j) >= min_gap for j in chosen):
            chosen.append(int(i))
        if len(chosen) == k:
            break
    return chosen


def day_outcomes(
    day_ret: np.ndarray, picks: list[int], days: tuple[int, ...] = (0, 1)
) -> np.ndarray:
    """(n_picks, len(days)) day returns in percent; NaN where the day is outside the sample."""
    out = np.full((len(picks), len(days)), np.nan)
    for r, i in enumerate(picks):
        for c, d in enumerate(days):
            if 0 <= i + d < len(day_ret):
                out[r, c] = day_ret[i + d] * PCT
    return out

"""Chart 2 event studies on real-shaped inputs (A27 rule 13) and the pair-4 descriptive study
(rule 5). Thin layer over `events`; pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from poly_actor.analysis import events as ev
from poly_actor.analysis.models import bca_ci
from poly_actor.analysis.sample import SessionGrid

FED_WINDOW = (3, 6)  # bars -3..+6
FED_SIGN_MIN = 0.5  # bp of Δdovishness
CPI_POST = 5  # bars 0..+5 after the gap
CPI_SIGN_MIN = 0.005  # pp of implied CPI
BTC_EVENTS = 20
BTC_WINDOW = (3, 6)  # same window as Fed (A27 gives none for BTC; see the build report)
BAND_SEED = 20261006


def flat_index(grid: SessionGrid) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    cells = ev.flat_cells(grid)
    return cells, {c: i for i, c in enumerate(cells)}


def _signed_paths(
    grid, y, gaps, bar0s, threshold, pre, post, cells, where, fold
) -> tuple[list[ev.EventPath], int, int]:
    paths, unsigned, dropped = [], 0, 0
    for bar0 in bar0s:
        i0 = where[bar0]
        prev = cells[i0 - 1] if i0 > 0 else None
        sign = ev.sign_of(grid.x[prev], threshold) if prev else 0.0
        if sign == 0.0:
            unsigned += 1
            continue
        path = ev.event_path(grid, y, gaps, cells, where, bar0, pre, post, sign)
        if path is None:
            dropped += 1
            continue
        paths.append(ev.fold_gaps(path) if fold else path)
    return paths, unsigned, dropped


def bar_study(
    grid: SessionGrid,
    y: np.ndarray,
    gaps: np.ndarray,
    bar0s: list[tuple[int, int]],
    pool_bar0s: list[tuple[int, int]],
    threshold: float,
    window: tuple[int, int],
    fold: bool,
    seed: int = BAND_SEED,
) -> ev.EventStudyOut | ev.TooFewEvents:
    """Fed/BTC layout: bars -pre..+post around bar 0, gaps explicit (Fed) or folded (BTC).
    The random-date band draws, for each event, a non-event path at the same bar position."""
    cells, where = flat_index(grid)
    pre, post = window
    paths, unsigned, dropped = _signed_paths(
        grid, y, gaps, bar0s, threshold, pre, post, cells, where, fold
    )
    if not fold:
        kept = ev.same_layout(paths)
        dropped += len(paths) - len(kept)
        paths = kept
    pool, _, _ = _signed_paths(grid, y, gaps, pool_bar0s, threshold, pre, post, cells, where, fold)
    if not fold and paths:
        pool = [p for p in pool if p.labels == paths[0].labels]
    band = matched_band(pool, [p.pos for p in paths], seed)
    times = [int(grid.ts_end[p.session, p.pos]) for p in paths]
    return _summary(paths, band, times, unsigned, dropped, len(bar0s))


def _summary(
    paths: list[ev.EventPath],
    band: tuple[np.ndarray, np.ndarray] | None,
    times: list[int],
    unsigned: int,
    dropped: int,
    n_candidates: int,
) -> ev.EventStudyOut | ev.TooFewEvents:
    """The event study, or the counts that explain why there is none."""
    out = ev.summarise(paths, band, times, unsigned, dropped)
    if out is not None:
        return out
    return ev.TooFewEvents(n_candidates, len(paths), unsigned, dropped)


def matched_band(
    pool: list[ev.EventPath], positions: list[int], seed: int, draws: int = ev.BAND_DRAWS
) -> tuple[np.ndarray, np.ndarray] | None:
    """90% band of the mean path over random sets that match each event's bar position."""
    by_pos: dict[int, list[int]] = {}
    for i, p in enumerate(pool):
        by_pos.setdefault(p.pos, []).append(i)
    if not positions or any(pos not in by_pos for pos in positions):
        return None
    cum = ev.cumulative_signed(pool)
    rng = np.random.default_rng(seed)
    means = np.empty((draws, cum.shape[1]))
    for d in range(draws):
        pick = [by_pos[pos][rng.integers(len(by_pos[pos]))] for pos in positions]
        means[d] = cum[pick].mean(axis=0)
    lo, hi = np.quantile(means, [(1 - ev.BAND_LEVEL) / 2, (1 + ev.BAND_LEVEL) / 2], axis=0)
    return lo, hi


def cpi_study(
    grid: SessionGrid,
    y: np.ndarray,
    gaps: np.ndarray,
    release_sessions: list[int],
    pool_sessions: list[int],
    seed: int = BAND_SEED,
) -> ev.EventStudyOut | ev.TooFewEvents:
    """CPI layout: the opening gap, then bars 0..+5 of the release session. Signed by the PM
    change in the bar before bar 0 (the previous session's last bar)."""
    cells, where = flat_index(grid)

    def build(sessions):
        out, unsigned, dropped = [], 0, 0
        for s in sessions:
            if (s, 0) not in where or where[(s, 0)] == 0:
                dropped += 1
                continue
            prev = cells[where[(s, 0)] - 1]
            sign = ev.sign_of(grid.x[prev], CPI_SIGN_MIN)
            if sign == 0.0:
                unsigned += 1
                continue
            path = ev.gap_first_path(grid, y, gaps, s, CPI_POST, sign)
            if path is None:
                dropped += 1
                continue
            out.append(path)
        return out, unsigned, dropped

    paths, unsigned, dropped = build(release_sessions)
    pool, _, _ = build(pool_sessions)
    band = ev.random_band(pool, len(paths), seed) if paths else None
    times = [int(grid.ts_end[p.session, 0]) for p in paths]
    return _summary(paths, band, times, unsigned, dropped, len(release_sessions))


def btc_events(grid: SessionGrid, k: int = BTC_EVENTS) -> list[tuple[int, int]]:
    """Bar-0 cells of the k largest |Δln ladder| moves on rule-1 cells, greedy, one per
    session. Bar 0 is the bar after the move (the first bar ending after it)."""
    cells, where = flat_index(grid)
    s_idx, p_idx = np.nonzero(grid.row_ok)
    size = np.abs(grid.x[s_idx, p_idx])
    chosen: list[tuple[int, int]] = []
    used: set[int] = set()
    for i in np.argsort(-size, kind="stable"):
        s, p = int(s_idx[i]), int(p_idx[i])
        if s in used:
            continue
        j = where[(s, p)] + 1
        if j >= len(cells):
            continue
        chosen.append(cells[j])
        used.add(s)
        if len(chosen) == k:
            break
    return chosen


# ---------------------------------------------------------------- pair 4


@dataclass(frozen=True)
class RecessionDays:
    sessions: np.ndarray  # dates
    close_ts: np.ndarray  # epoch s
    dp: np.ndarray  # ΔP(Yes), 16:00 -> 16:00 ET (session close to session close)
    dlogit: np.ndarray
    day_ret: dict[str, np.ndarray]  # close-to-close log return per ticker


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 0.01, 0.99)
    return np.log(q / (1 - q))


def recession_days(panel: pd.DataFrame, tickers: tuple[str, ...]) -> RecessionDays:
    """Daily PM change between consecutive session closes (spliced changes summed; NaN if any
    hour in between is missing) and close-to-close returns (gap + session bars)."""
    p = panel.sort_values("ts_end").reset_index(drop=True)
    bars = p[p["is_session_bar"].astype(bool)]
    close_idx = bars.groupby("session")["ts_end"].idxmax()
    sessions = np.array(close_idx.index)
    close_rows = close_idx.to_numpy()
    change = p["signal_change"].to_numpy(dtype="float64")
    level = p["signal_level"].to_numpy(dtype="float64")
    row_dlogit = _logit(level) - _logit(level - change)
    dp = np.full(len(sessions), np.nan)
    dl = np.full(len(sessions), np.nan)
    for i in range(1, len(sessions)):
        seg = slice(close_rows[i - 1] + 1, close_rows[i] + 1)
        c, lg = change[seg], row_dlogit[seg]
        if len(c) and not np.isnan(c).any():
            dp[i], dl[i] = c.sum(), lg.sum()
    day_ret = {}
    for t in tickers:
        gap = bars.groupby("session")[f"overnight_gap_{t}"].max()  # one value on the open row
        bar_sum = bars.groupby("session")[f"ret_{t}"].sum(min_count=1)
        bar_nan = bars.groupby("session")[f"ret_{t}"].apply(lambda r: r.isna().any())
        val = (gap + bar_sum).where(~bar_nan)
        day_ret[t] = val.reindex(sessions).to_numpy(dtype="float64")
    close_ts = (
        (p.loc[close_rows, "ts_end"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    ).to_numpy()
    return RecessionDays(sessions, close_ts, dp, dl, day_ret)


RECESSION_PICKS = 10
RECESSION_MIN_GAP = 2  # trading days between selected days
RECESSION_TICKERS = ("SPY", "IWM", "TLT")
SPREAD = "IWM-SPY"


def recession_study(days: RecessionDays, measure: str = "dp") -> dict:
    """The 10 largest rises and 10 largest falls (>= 2 trading days apart), and the day-0 and
    day+1 moves of each ticker and the IWM-SPY spread, with 90% BCa intervals. No p-values."""
    values = days.dp if measure == "dp" else days.dlogit
    rets = dict(days.day_ret)
    rets[SPREAD] = days.day_ret["IWM"] - days.day_ret["SPY"]
    out = {"measure": measure, "groups": {}}
    for name, largest in (("rises", True), ("falls", False)):
        picks = ev.greedy_extremes(values, RECESSION_PICKS, RECESSION_MIN_GAP, largest)
        group = {
            "dates": [str(days.sessions[i]) for i in picks],
            "close_ts": [int(days.close_ts[i]) for i in picks],
            "pm_change": [float(values[i]) for i in picks],
            "tickers": {},
        }
        for t, r in rets.items():
            vals = ev.day_outcomes(r, picks)
            ok = ~np.isnan(vals).any(axis=1)
            entry = {"days": [0, 1], "values": vals.tolist(), "n": int(ok.sum())}
            if ok.sum() >= ev.MIN_EVENTS:
                lo, hi = bca_ci(vals[ok], lambda a: a.mean(axis=0))
                entry |= {
                    "mean": vals[ok].mean(axis=0).tolist(),
                    "ci_low": np.asarray(lo).tolist(),
                    "ci_high": np.asarray(hi).tolist(),
                }
            group["tickers"][t] = entry
        out["groups"][name] = group
    return out

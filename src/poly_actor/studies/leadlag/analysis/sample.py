"""Sample and lag rules of prereg A27 rule 1 (pure functions; no I/O).

Every session is laid out on its full EXPECTED bar grid (7 bars on a regular XNYS session, 3 on
an early close; missing Yahoo bars stay as empty cells). Lags are taken on that grid BEFORE any
filtering, so a lag that lands on a hole is NaN and is never replaced by the previous bar, and a
lag never crosses into the previous session.

A row enters a regression only if the row itself AND every row that supplies one of its PM
regressors pass the filter (A27 rule 1):

    both_trading, not roll_hour, not event_hour, not outage_mask, not clipped_p_gt1,
    pm_obs_age_s <= 1800 s

`both_trading` is split into a stock side (every equity return of the pair present, no outage)
and a PM side (signal level and change present, no outage). The split lets the session-shift
placebos move the PM side to another session while the stock side stays put (A27 rules 11-12,
as amended by A28 item 1).

Arrays are (S, P): S sessions in date order, P = 7 bar positions. Flattening row-major gives
time order. Timestamps are epoch seconds (UTC).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

MAX_BARS = 7  # bars of a regular XNYS session (09:30-16:00 ET, the last one 30 min)
MAX_PM_AGE_S = 1800.0  # A27 rule 1
ROBUST_PM_AGE_S = 900.0  # A27 rule 10: age-900 run, reported only

# Sign that turns the panel's `signal_change` into the pre-registered regressor.
# Fed: dovishness = minus the expected change in bp (prereg Pair 1).
SIGNAL_SIGN = {
    "fed_decision": -1.0,
    "bitcoin_monthly_ladder": 1.0,
    "us_cpi_inflation": 1.0,
    "us_recession": 1.0,
}


@dataclass(frozen=True)
class SessionGrid:
    """One pair's session bars on the expected grid. All arrays are (S, P)."""

    sessions: np.ndarray  # (S,) datetime.date, ascending
    ts_end: np.ndarray  # int64 epoch s; -1 where the position does not exist
    exists: np.ndarray  # bool: the session has a bar at this position
    stock_ok: np.ndarray  # bool: every equity return present, not in an outage
    pm_ok: np.ndarray  # bool: PM side of the A27 rule-1 filter
    x: np.ndarray  # float: PM change in analysis units (NaN where missing)
    returns: dict[str, np.ndarray]  # ticker -> float log return (NaN where missing)
    event_id: np.ndarray  # object: active PM event per cell (None where missing)

    @property
    def n_sessions(self) -> int:
        return len(self.sessions)

    @property
    def row_ok(self) -> np.ndarray:
        """The full A27 rule-1 filter of each cell."""
        return self.stock_ok & self.pm_ok


def equity_tickers(panel: pd.DataFrame) -> list[str]:
    """Tickers with session-bar returns (24/7 spot series such as BTC-USD excluded)."""
    return [
        c.removeprefix("ret_")
        for c in panel.columns
        if c.startswith("ret_") and not c.endswith("-USD")
    ]


def pm_side_ok(panel: pd.DataFrame, max_age_s: float = MAX_PM_AGE_S) -> pd.Series:
    """PM side of the rule-1 filter, per panel row."""
    return (
        panel["signal_level"].notna()
        & panel["signal_change"].notna()
        & ~panel["outage_mask"].astype(bool)
        & ~panel["roll_hour"].astype(bool)
        & ~panel["event_hour"].astype(bool)
        & ~panel["clipped_p_gt1"].astype(bool)
        & (panel["pm_obs_age_s"] <= max_age_s)
    )


def stock_side_ok(panel: pd.DataFrame) -> pd.Series:
    """Stock side of `both_trading`: every equity return present, no outage."""
    rets = [f"ret_{t}" for t in equity_tickers(panel)]
    return panel[rets].notna().all(axis=1) & ~panel["outage_mask"].astype(bool)


def build_grid(panel: pd.DataFrame, pair_id: str, max_age_s: float = MAX_PM_AGE_S) -> SessionGrid:
    """Lay a panel's session bars on the expected (session, position) grid.

    The panel grid already holds every expected bar of every XNYS session (step 4), including
    bars Yahoo did not return, so the position of a bar is its rank within its session."""
    bars = panel[panel["is_session_bar"].astype(bool)].sort_values("ts_end", kind="stable")
    bars = bars.reset_index(drop=True)
    sessions = np.array(sorted(bars["session"].unique()))
    s_idx = np.searchsorted(sessions, bars["session"].to_numpy())
    pos = bars.groupby("session").cumcount().to_numpy()
    if pos.max(initial=0) >= MAX_BARS:
        raise ValueError(f"a session has more than {MAX_BARS} bars")
    shape = (len(sessions), MAX_BARS)

    def put(values: np.ndarray, fill, dtype) -> np.ndarray:
        out = np.full(shape, fill, dtype=dtype)
        out[s_idx, pos] = values
        return out

    ts = ((bars["ts_end"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
    sign = SIGNAL_SIGN[pair_id]
    returns = {
        t: put(bars[f"ret_{t}"].to_numpy(dtype="float64"), np.nan, "float64")
        for t in equity_tickers(panel)
    }
    return SessionGrid(
        sessions=sessions,
        ts_end=put(ts.astype("int64"), -1, "int64"),
        exists=put(np.ones(len(bars), dtype=bool), False, bool),
        stock_ok=put(stock_side_ok(bars).to_numpy(), False, bool),
        pm_ok=put(pm_side_ok(bars, max_age_s).to_numpy(), False, bool),
        x=put(sign * bars["signal_change"].to_numpy(dtype="float64"), np.nan, "float64"),
        returns=returns,
        event_id=put(bars["event_id"].to_numpy(dtype=object), None, object),
    )


def lag(arr: np.ndarray, k: int, fill) -> np.ndarray:
    """Value of the cell k positions EARLIER in the same session (k < 0: later).

    Cells whose lag falls outside the session get `fill`. Never crosses a session boundary."""
    out = np.full_like(arr, fill)
    if k == 0:
        return arr.copy()
    if k > 0:
        out[:, k:] = arr[:, :-k]
    else:
        out[:, :k] = arr[:, -k:]
    return out


def shift_sessions(grid: SessionGrid, k: int) -> SessionGrid:
    """Circular session shift of the PM side: session s receives the PM series of session
    s + k (mod S), matched by bar position. Unmatched positions drop out because the donor or
    the receiver has no valid cell there. The stock side stays in place."""
    return replace(
        grid,
        pm_ok=np.roll(grid.pm_ok, -k, axis=0),
        x=np.roll(grid.x, -k, axis=0),
        event_id=np.roll(grid.event_id, -k, axis=0),
    )


def design_mask(grid: SessionGrid, pm_lags: tuple[int, ...], y: np.ndarray) -> np.ndarray:
    """Cells that may enter a regression with PM regressors at `pm_lags` (A27 rule 1).

    The cell itself and every lag cell must pass the full filter and lie in the same session;
    the outcome must be present."""
    ok = grid.row_ok & ~np.isnan(y)
    for k in pm_lags:
        ok &= lag(grid.row_ok, k, False)
    return ok


@dataclass(frozen=True)
class Design:
    """Flattened regression inputs in time order."""

    y: np.ndarray  # (n,)
    X: np.ndarray  # (n, 1 + n_lags + n_controls), first column is the intercept
    session: np.ndarray  # (n,) session index, for clustered SEs
    cells: np.ndarray  # (n, 2) (session index, position)
    names: tuple[str, ...]

    @property
    def n_rows(self) -> int:
        return len(self.y)

    @property
    def n_sessions(self) -> int:
        return int(np.unique(self.session).size)


def build_design(
    grid: SessionGrid,
    y: np.ndarray,
    pm_lags: tuple[int, ...],
    controls: np.ndarray | None = None,
    control_names: tuple[str, ...] = (),
) -> Design:
    """OLS design: intercept, PM change at each lag, optional controls (S, P, m).

    Controls are not PM regressors: they only have to be present (A27 rule 3)."""
    ok = design_mask(grid, pm_lags, y)
    cols = [lag(grid.x, k, np.nan) for k in pm_lags]
    if controls is not None:
        ok &= ~np.isnan(controls).any(axis=2)
        cols += [controls[:, :, j] for j in range(controls.shape[2])]
    s_idx, p_idx = np.nonzero(ok)  # row-major = time order
    X = np.column_stack([np.ones(len(s_idx))] + [c[s_idx, p_idx] for c in cols])
    names = ("const", *(f"pm_lag{k}" for k in pm_lags), *control_names)
    return Design(y[s_idx, p_idx], X, s_idx, np.column_stack([s_idx, p_idx]), names)

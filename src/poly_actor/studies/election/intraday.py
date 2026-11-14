"""H3 (election night, 5-minute) and H4 (who moves first, hourly). Pure functions on the step 8
panels; no I/O.

H4 lag convention (milestone 1): lag k > 0 pairs the stock bar t with the odds change of bar t - k
of the SAME session (odds first); k < 0 pairs it with a later odds change (stocks first). Lags
never cross a session boundary: the session grid is a sessions x positions matrix and shifts
happen along positions only. The first bar of a session has no dP (panel rule).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from poly_actor.core.stats import models
from poly_actor.core.stats.shifts import admissible_shifts
from poly_actor.studies.election import stats as st

LAGS = [-3, -2, -1, 0, 1, 2, 3]
BH_Q = 0.05
BAND_Q = 0.95
MIN_SLOPE_OBS = 10  # fewer complete (y, x) pairs than this -> slope reported as NaN

SESSION_MIN_SHIFT = 5  # sessions; H4 shifts whole sessions (same value as the lead-lag study)


# ---------------------------------------------------------------- H4


def session_matrix(frame: pd.DataFrame, col: str) -> tuple[np.ndarray, list]:
    """(sessions x positions) matrix of `col`; positions are the bar order within the session.
    `frame` has session, bar_end_ts and `col`, one row per expected bar."""
    f = frame.sort_values("bar_end_ts").copy()
    f["pos"] = f.groupby("session").cumcount()
    m = f.pivot(index="session", columns="pos", values=col)
    return m.to_numpy(dtype="float64"), list(m.index)


def lag_within(x: np.ndarray, k: int) -> np.ndarray:
    """out[s, j] = x[s, j - k] when 0 <= j - k < P, else NaN (never crosses sessions)."""
    out = np.full_like(x, np.nan)
    P = x.shape[1]
    if abs(k) >= P:
        return out
    if k >= 0:
        out[:, k:] = x[:, : P - k]
    else:
        out[:, : P + k] = x[:, -k:]
    return out


def _t_slope(y: np.ndarray, x: np.ndarray) -> tuple[float, float, float, int, tuple]:
    ok = ~np.isnan(y) & ~np.isnan(x)
    yy, xx = y[ok], x[ok]
    if len(yy) < MIN_SLOPE_OBS or np.ptp(xx) == 0:
        return np.nan, np.nan, np.nan, int(len(yy)), (np.nan, np.nan)
    X = np.column_stack([np.ones(len(xx)), xx])
    fit = models.ols(X, yy, cov="hac")
    lt = models.lin_test(fit, np.array([0.0, 1.0]), level=st.CI_LEVEL)
    return lt.estimate, lt.t, lt.p_two, fit.n, (lt.ci_low, lt.ci_high)


def residualise(y: np.ndarray, Z: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Residual of y on [1, Z] over rows where all are finite (NaN elsewhere)."""
    ok = ~np.isnan(y) & ~np.isnan(Z).any(axis=1)
    X = np.column_stack([np.ones(ok.sum()), Z[ok]])
    beta, *_ = np.linalg.lstsq(X, y[ok], rcond=None)
    out = np.full(len(y), np.nan)
    out[ok] = y[ok] - X @ beta
    return out, beta.tolist()


def lag_scan(
    y: np.ndarray, x: np.ndarray, lags: list[int] = LAGS, shift: int = 0
) -> list[tuple[float, float, float, int, tuple]]:
    """Per lag: slope of y (S x P) on x lagged within session, after rolling the odds side by
    `shift` whole sessions (session s receives session s + shift)."""
    xs = np.roll(x, -shift, axis=0) if shift else x
    return [_t_slope(y.ravel(), lag_within(xs, k).ravel()) for k in lags]


def h4(y: np.ndarray, x: np.ndarray) -> dict:
    """Per-lag HAC slopes, BH over the 7 lags, session-shift band of max |t|, verdict."""
    rows = lag_scan(y, x)
    p = [r[2] for r in rows]
    reject, adj = models.bh(np.nan_to_num(p, nan=1.0), BH_Q)
    shifts = admissible_shifts(y.shape[0], SESSION_MIN_SHIFT)
    maxt = [np.nanmax(np.abs([r[1] for r in lag_scan(y, x, shift=int(j))])) for j in shifts]
    band = float(np.quantile(maxt, BAND_Q)) if len(maxt) else float("nan")
    tvals = [r[1] for r in rows]
    return {
        "lags": LAGS,
        "rows": [
            {
                "lag": k,
                "b10_pct": r[0] * st.PER_10PTS_PCT,
                "ci10_pct": [r[4][0] * st.PER_10PTS_PCT, r[4][1] * st.PER_10PTS_PCT],
                "t": r[1],
                "p_hac": r[2],
                "p_bh": float(adj[i]),
                "bh_reject": bool(reject[i]),
                "n": r[3],
                "beyond_band": bool(abs(r[1]) > band),
            }
            for i, (k, r) in enumerate(zip(LAGS, rows, strict=True))
        ],
        "band_max_abs_t_95": band,
        "n_shifts": int(len(shifts)),
        "min_shift_sessions": SESSION_MIN_SHIFT,
        "verdict": st.h4_verdict(LAGS, tvals, [bool(v) for v in reject]),
    }


# ---------------------------------------------------------------- H3


def night_frame(night: pd.DataFrame, instruments: dict[str, str]) -> pd.DataFrame:
    """Regular 5-minute grid (bar end) over the night table: one return column per instrument,
    the spreads, dp_sen (from the NQ rows; odds are as-of the same bar ends for every future),
    in_window, fresh and resolved flags."""
    lo, hi = night["bar_end_ts"].min(), night["bar_end_ts"].max()
    grid = pd.DatetimeIndex(pd.date_range(lo, hi, freq="5min"), name="bar_end_ts")
    out = pd.DataFrame(index=grid)
    for name, tk in instruments.items():
        g = night[night["ticker"] == tk].set_index("bar_end_ts")
        out[name] = g["ret"].reindex(grid)
    out["NQ-ES"] = out["NQ"] - out["ES"]
    out["RTY-ES"] = out["RTY"] - out["ES"]
    ref = night[night["ticker"] == instruments["NQ"]].set_index("bar_end_ts").reindex(grid)
    out["dp_sen"] = ref["dp_sen"]
    out["p_sen"], out["p_house"] = ref["p_sen"], ref["p_house"]
    out["age_p_sen"], out["res_p_sen"] = ref["age_p_sen"], ref["res_p_sen"].fillna(False)
    out["in_window"] = ref["in_window"].fillna(False).astype(bool)
    return out


def h3(frame: pd.DataFrame, fresh_s: int) -> dict:
    """Joint distributed-lag regression ret_t = a + sum_k b_k dP_{t-k}, k = -3..3, in-window bars
    (lags may reach into the margin bars), Newey-West HAC with the rule-of-thumb lag."""
    w = frame["in_window"].to_numpy()
    lagged = np.column_stack([frame["dp_sen"].shift(k).to_numpy() for k in LAGS])
    win = frame[w]
    fresh = (win["age_p_sen"] <= fresh_s) & ~win["res_p_sen"].astype(bool)
    out = {
        "lags": LAGS,
        "n_window_bars": int(w.sum()),
        "share_fresh_odds": float(fresh.mean()),
        "share_resolved": float(win["res_p_sen"].astype(bool).mean()),
        "label": "descriptive only (one night; NQ path seen before the freeze)",
        "instruments": {},
    }
    for name in ["NQ", "ES", "RTY", "NQ-ES", "RTY-ES"]:
        y = frame[name].to_numpy()
        ok = w & ~np.isnan(y) & ~np.isnan(lagged).any(axis=1)
        X = np.column_stack([np.ones(ok.sum()), lagged[ok]])
        fit = models.ols(X, y[ok], cov="hac")
        rows = []
        for i, k in enumerate(LAGS):
            v = np.zeros(X.shape[1])
            v[i + 1] = 1.0
            lt = models.lin_test(fit, v, level=st.CI_LEVEL)
            rows.append(
                {
                    "lag": k,
                    "b10_pct": lt.estimate * st.PER_10PTS_PCT,
                    "ci10_pct": [lt.ci_low * st.PER_10PTS_PCT, lt.ci_high * st.PER_10PTS_PCT],
                    "t": lt.t,
                    "p_hac": lt.p_two,
                }
            )
        out["instruments"][name] = {"n_bars": int(ok.sum()), "rows": rows}
    return out

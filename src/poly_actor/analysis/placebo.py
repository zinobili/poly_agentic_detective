"""Chart 1 cross-correlation, its simultaneous noise band and the session-shift placebos
(A27 rules 11-12 as amended by A28 item 1). Pure functions on a `SessionGrid`.

Lag k > 0 pairs the stock return at bar t with the PM change at bar t - k of the same session
(PM first); k < 0 pairs it with a later PM change (stock first). Both cells must pass the full
rule-1 filter (`sample.design_mask`).

Session shift j: session s receives the PM side of session s + j (mod S), bars matched by
position; the rule-1 filter is recomputed after the shift. Admissible shifts are every j with
min(j, S - j) >= 5, all enumerated (no random draws). All shifts are computed at once with FFT
circular cross-correlations; `xcorr` and `xcorr_t` are the direct (reference) computations.

A28 item 1 (studentized band). At each lag the band statistic is the heteroskedasticity-robust
t = sum (x - xbar)(y - ybar) / sqrt(sum (x - xbar)^2 (y - ybar)^2), and the band is the 95th
percentile of max|t| over the admissible shifts. Chart 1 still draws r; "clear link" and the
exploratory "stocks first" label are read from |t| against the band. The Fed shift placebo
statistic is the HAC t of b0 + b1 + b2 (`shift_placebo(..., stat="hac_t")`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poly_actor.analysis import models
from poly_actor.analysis.sample import (
    SessionGrid,
    design_mask,
    lag,
)

XCORR_LAGS = tuple(range(-6, 7))  # A27 rule 12
MIN_SHIFT = 5  # sessions (A27 rules 11-12)
BAND_QUANTILE = 0.95
BAND_STAT = "robust_t"  # A28 item 1: the band applies to the robust t per lag, not to r


def admissible_shifts(n_sessions: int, min_shift: int = MIN_SHIFT) -> np.ndarray:
    j = np.arange(1, n_sessions)
    return j[np.minimum(j, n_sessions - j) >= min_shift]


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    xc, yc = x - x.mean(), y - y.mean()
    den = np.sqrt((xc @ xc) * (yc @ yc))
    return float(xc @ yc / den) if den > 0 else float("nan")


def _robust_t(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    xc, yc = x - x.mean(), y - y.mean()
    den = np.sqrt(np.sum(xc * xc * yc * yc))
    return float(xc @ yc / den) if den > 0 else float("nan")


def _per_lag(grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...], fn) -> np.ndarray:
    out = []
    for k in lags:
        ok = design_mask(grid, (k,), y)
        out.append(fn(lag(grid.x, k, np.nan)[ok], y[ok]))
    return np.array(out)


def xcorr(grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS) -> np.ndarray:
    """Direct cross-correlation r(k) = corr(y_t, x_{t-k}) on rule-1 cells, one r per lag."""
    return _per_lag(grid, y, lags, _pearson)


def xcorr_t(grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS) -> np.ndarray:
    """Direct robust t per lag on rule-1 cells (A28 item 1); reference for the FFT version."""
    return _per_lag(grid, y, lags, _robust_t)


def _circ(f: np.ndarray, g: np.ndarray) -> np.ndarray:
    """c[j] = sum_s,p f[s,p] g[(s+j) % S, p] for every j (FFT along sessions)."""
    F, G = np.fft.rfft(f, axis=0), np.fft.rfft(g, axis=0)
    return np.fft.irfft(np.conj(F) * G, n=f.shape[0], axis=0).sum(axis=1)


def xcorr_all_shifts(
    grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS
) -> np.ndarray:
    """r(j, k) for every circular session shift j = 0..S-1 and lag k. Shape (S, n_lags)."""
    return xcorr_stats_all_shifts(grid, y, lags)[0]


def xcorr_stats_all_shifts(
    grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS
) -> tuple[np.ndarray, np.ndarray]:
    """(r, robust t) for every circular session shift j = 0..S-1 and lag k, each (S, n_lags).

    Every moment is a receiver part (stock side) times a donor part (PM side), so each one is
    an FFT circular correlation. x and y are centred on their overall means first: r and t do
    not depend on that, and it limits cancellation in the expanded fourth-moment sum."""
    S = grid.n_sessions
    y_ok = grid.stock_ok & ~np.isnan(y)
    y0 = np.where(y_ok, y - (y[y_ok].mean() if y_ok.any() else 0.0), 0.0)
    x_ok = grid.pm_ok & ~np.isnan(grid.x)
    xm = float(grid.x[x_ok].mean()) if x_ok.any() else 0.0
    r_out = np.empty((S, len(lags)))
    t_out = np.empty((S, len(lags)))
    for i, k in enumerate(lags):
        a = (y_ok & lag(grid.stock_ok, k, False)).astype(float)  # receiver side
        b = (grid.pm_ok & lag(grid.pm_ok, k, False)).astype(float)  # donor side
        xv = np.where(b > 0, lag(grid.x, k, np.nan) - xm, 0.0)
        ay, ayy, xx = a * y0, a * y0 * y0, xv * xv
        n = np.rint(_circ(a, b))
        sx, sxx = _circ(a, xv), _circ(a, xx)
        sy, syy = _circ(ay, b), _circ(ayy, b)
        sxy, sxxy, sxyy, sxxyy = _circ(ay, xv), _circ(ay, xx), _circ(ayy, xv), _circ(ayy, xx)
        with np.errstate(invalid="ignore", divide="ignore"):
            num = n * sxy - sx * sy
            den = np.sqrt(np.clip(n * sxx - sx * sx, 0, None) * np.clip(n * syy - sy * sy, 0, None))
            r_out[:, i] = np.where((n >= 3) & (den > 0), num / den, np.nan)
            mx, my = sx / n, sy / n
            # sum (x - mx)^2 (y - my)^2, expanded into the receiver x donor moments
            q = (
                sxxyy
                - 2 * my * sxxy
                + my * my * sxx
                - 2 * mx * sxyy
                + 4 * mx * my * sxy
                - 2 * mx * my * my * sx
                + mx * mx * syy
                - 2 * mx * mx * my * sy
                + n * mx * mx * my * my
            )
            cov = sxy - sx * sy / n
            ok = (n >= 3) & (q > 0)
            t_out[:, i] = np.where(ok, cov / np.sqrt(np.where(ok, q, 1.0)), np.nan)
    return r_out, t_out


@dataclass(frozen=True)
class XcorrResult:
    lags: tuple[int, ...]
    r: tuple[float, ...]  # drawn in Chart 1
    t: tuple[float, ...]  # robust t per lag; the band applies to |t| (A28 item 1)
    band: float  # simultaneous 95% band on |t| (scalar)
    n_shifts: int
    peak_lag: int  # lag of the largest |t|
    clear_link: bool  # peak |t| outside the band
    stocks_first: bool  # peak at a negative lag outside the band, no positive lag outside
    adjacent_outside: bool  # reported only (A27 rule 12)


def xcorr_with_band(
    grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS
) -> XcorrResult:
    """Chart 1 for one ticker: r and robust t per lag, and the scalar simultaneous band on |t|
    (95th percentile of max|t| over the admissible shifts; A28 item 1)."""
    allr, allt = xcorr_stats_all_shifts(grid, y, lags)
    shifts = admissible_shifts(grid.n_sessions)
    band = float(np.nanquantile(np.nanmax(np.abs(allt[shifts]), axis=1), BAND_QUANTILE))
    return summarise_xcorr(lags, allr[0], band, len(shifts), allt[0])


def summarise_xcorr(
    lags: tuple[int, ...],
    r: np.ndarray,
    band: float,
    n_shifts: int,
    t: np.ndarray | None = None,
) -> XcorrResult:
    """Peak, "clear link" and "stocks first" read from |t| against the band (A28 item 1).
    With `t=None` they are read from |r| (used only by unit tests of the labelling logic)."""
    stat = np.asarray(r if t is None else t, dtype=float)
    abss = np.where(np.isnan(stat), -1.0, np.abs(stat))
    peak = int(np.argmax(abss))
    outside = abss > band
    lag_arr = np.array(lags)
    stocks_first = bool(outside[peak] and lags[peak] < 0 and not outside[lag_arr > 0].any())
    adjacent = any(
        0 <= j < len(lags) and outside[j] and stat[j] * stat[peak] > 0 for j in (peak - 1, peak + 1)
    )
    return XcorrResult(
        tuple(int(v) for v in lags),
        tuple(float(v) for v in r),
        tuple(float(v) for v in stat),
        band,
        n_shifts,
        int(lags[peak]),
        bool(outside[peak]),
        stocks_first,
        bool(outside[peak] and adjacent),
    )


def ols_all_shifts(
    grid: SessionGrid,
    y: np.ndarray,
    pm_lags: tuple[int, ...],
    controls: np.ndarray | None = None,
) -> np.ndarray:
    """OLS coefficients under every circular session shift j = 0..S-1, shape (S, k).

    Same design as `sample.build_design` (intercept, PM lags, controls) with the rule-1 filter
    recomputed after each shift. Receiver-side terms (outcome, stock filter, controls) stay in
    place; donor-side terms (PM changes and PM filter) move. Every cross-product factorises
    into a receiver part times a donor part, so all shifts come from FFT correlations."""
    lags0 = tuple(sorted({0, *pm_lags}))
    a = grid.stock_ok & ~np.isnan(y)
    b = np.ones_like(grid.pm_ok)
    for k in lags0:
        a = a & lag(grid.stock_ok, k, False)
        b = b & lag(grid.pm_ok, k, False)
    recv = [np.ones(y.shape)]
    if controls is not None:
        a = a & ~np.isnan(controls).any(axis=2)
        recv += [np.nan_to_num(controls[:, :, j]) for j in range(controls.shape[2])]
    af, bf = a.astype(float), b.astype(float)
    y0 = np.where(a, y, 0.0)
    don = [np.where(b, np.nan_to_num(lag(grid.x, k, np.nan)), 0.0) for k in pm_lags]
    cols = [("r", c) for c in recv[:1]] + [("d", c) for c in don] + [("r", c) for c in recv[1:]]
    m = len(cols)
    xtx = np.empty((grid.n_sessions, m, m))
    xty = np.empty((grid.n_sessions, m))
    for i, (ki, ci) in enumerate(cols):
        xty[:, i] = _circ(af * y0 * ci, bf) if ki == "r" else _circ(af * y0, bf * ci)
        for j in range(i, m):
            kj, cj = cols[j]
            if ki == "r" and kj == "r":
                v = _circ(af * ci * cj, bf)
            elif ki == "d" and kj == "d":
                v = _circ(af, bf * ci * cj)
            else:
                rc, dc = (ci, cj) if ki == "r" else (cj, ci)
                v = _circ(af * rc, bf * dc)
            xtx[:, i, j] = xtx[:, j, i] = v
    out = np.full((grid.n_sessions, m), np.nan)
    n = xtx[:, 0, 0]
    for j in range(grid.n_sessions):
        if n[j] > m:
            out[j] = np.linalg.solve(xtx[j], xty[j])
    return out


def hac_t_all_shifts(
    grid: SessionGrid,
    y: np.ndarray,
    pm_lags: tuple[int, ...],
    controls: np.ndarray | None = None,
    shifts: np.ndarray | None = None,
) -> np.ndarray:
    """HAC t of the sum of the PM-lag coefficients under each shift in `shifts` (default:
    all), NaN elsewhere (A28 item 1). Same design and Newey-West rule as the primary (A27
    rule 2), so shift 0 reproduces the primary t."""
    shifts = np.arange(grid.n_sessions) if shifts is None else shifts
    out = np.full(grid.n_sessions, np.nan)
    # Receiver side (stays in place): outcome, stock filter at the row and every PM lag, controls.
    a = grid.stock_ok & ~np.isnan(y)
    for k in pm_lags:
        a = a & lag(grid.stock_ok, k, False)
    if controls is not None:
        a = a & ~np.isnan(controls).any(axis=2)
    # Donor side (moves with the shift): PM filter at the row and every PM lag, lagged changes.
    b = grid.pm_ok.copy()
    for k in pm_lags:
        b = b & lag(grid.pm_ok, k, False)
    don = np.stack([lag(grid.x, k, np.nan) for k in pm_lags], axis=2)
    w = np.r_[0.0, np.ones(len(pm_lags)), np.zeros(0 if controls is None else controls.shape[2])]
    for j in shifts:
        ok = a & np.roll(b, -int(j), axis=0)
        s_idx, p_idx = np.nonzero(ok)  # row-major = time order, as in `build_design`
        n = len(s_idx)
        cols = [np.ones((n, 1)), np.roll(don, -int(j), axis=0)[s_idx, p_idx]]
        if controls is not None:
            cols.append(controls[s_idx, p_idx])
        X = np.hstack(cols)
        if n <= X.shape[1]:
            continue
        fit = models.ols(X, y[s_idx, p_idx], cov="hac")
        se = float(np.sqrt(w @ fit.cov @ w))  # same t as `models.lin_test`, without scipy
        out[j] = float(w @ fit.beta) / se if se > 0 else 0.0
    return out


def shift_placebo(
    grid: SessionGrid,
    y: np.ndarray,
    pm_lags: tuple[int, ...],
    controls: np.ndarray | None = None,
    stat: str = "hac_t",
) -> dict:
    """Primary PM statistic on the real alignment and under every admissible session shift;
    one-sided permutation p (A27 rule 11).

    stat="hac_t" (Fed; A28 item 1): the HAC t of the sum of the PM-lag coefficients.
    stat="coef": the raw sum of the OLS coefficients (the A27 statistic). BTC keeps it: its
    shift placebo is reported only (XLU gates BTC), and A28 amends the Fed placebo only."""
    shifts = admissible_shifts(grid.n_sessions)
    if stat == "hac_t":
        values = hac_t_all_shifts(grid, y, pm_lags, controls, np.concatenate([[0], shifts]))
    elif stat == "coef":
        betas = ols_all_shifts(grid, y, pm_lags, controls)
        values = betas[:, 1 : 1 + len(pm_lags)].sum(axis=1)
    else:
        raise ValueError(f"unknown placebo statistic {stat!r}")
    sims = values[shifts]
    return {
        "statistic": stat,
        "observed": float(values[0]),
        "n_shifts": int(len(sims)),
        "p90_of_shifts": float(np.nanquantile(sims, 0.90)),
        "permutation_p": permutation_p(float(values[0]), sims),
    }


def permutation_p(observed: float, sims: np.ndarray) -> float:
    """One-sided (upper) permutation p, real alignment counted: (1 + #{sim >= obs}) / (1 + m)."""
    sims = sims[~np.isnan(sims)]
    return float((1 + np.sum(sims >= observed)) / (1 + len(sims)))

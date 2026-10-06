"""Chart 1 cross-correlation, its simultaneous noise band and the session-shift placebos
(A27 rules 11-12). Pure functions on a `SessionGrid`.

Lag k > 0 pairs the stock return at bar t with the PM change at bar t - k of the same session
(PM first); k < 0 pairs it with a later PM change (stock first). Both cells must pass the full
rule-1 filter (`sample.design_mask`).

Session shift j: session s receives the PM side of session s + j (mod S), bars matched by
position; the rule-1 filter is recomputed after the shift. Admissible shifts are every j with
min(j, S - j) >= 5, all enumerated (no random draws). All shifts are computed at once with FFT
circular cross-correlations; `xcorr` is the direct (reference) computation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poly_actor.analysis.sample import SessionGrid, design_mask, lag

XCORR_LAGS = tuple(range(-6, 7))  # A27 rule 12
MIN_SHIFT = 5  # sessions (A27 rules 11-12)
BAND_QUANTILE = 0.95
FED_PLACEBO_P = 0.10  # placebo passes if the shift permutation p < 0.10 (A27 rule 11)


def admissible_shifts(n_sessions: int, min_shift: int = MIN_SHIFT) -> np.ndarray:
    j = np.arange(1, n_sessions)
    return j[np.minimum(j, n_sessions - j) >= min_shift]


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    xc, yc = x - x.mean(), y - y.mean()
    den = np.sqrt((xc @ xc) * (yc @ yc))
    return float(xc @ yc / den) if den > 0 else float("nan")


def xcorr(grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS) -> np.ndarray:
    """Direct cross-correlation r(k) = corr(y_t, x_{t-k}) on rule-1 cells, one r per lag."""
    out = []
    for k in lags:
        ok = design_mask(grid, (k,), y)
        out.append(_pearson(lag(grid.x, k, np.nan)[ok], y[ok]))
    return np.array(out)


def _circ(f: np.ndarray, g: np.ndarray) -> np.ndarray:
    """c[j] = sum_s,p f[s,p] g[(s+j) % S, p] for every j (FFT along sessions)."""
    F, G = np.fft.rfft(f, axis=0), np.fft.rfft(g, axis=0)
    return np.fft.irfft(np.conj(F) * G, n=f.shape[0], axis=0).sum(axis=1)


def xcorr_all_shifts(
    grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS
) -> np.ndarray:
    """r(j, k) for every circular session shift j = 0..S-1 and lag k. Shape (S, n_lags)."""
    S = grid.n_sessions
    y_ok = grid.stock_ok & ~np.isnan(y)
    y0 = np.where(y_ok, y, 0.0)
    out = np.empty((S, len(lags)))
    for i, k in enumerate(lags):
        a = (y_ok & lag(grid.stock_ok, k, False)).astype(float)  # receiver side
        b = (grid.pm_ok & lag(grid.pm_ok, k, False)).astype(float)  # donor side
        xv = np.where(b > 0, lag(grid.x, k, np.nan), 0.0)
        ay = a * y0
        n = _circ(a, b)
        sx, sxx = _circ(a, xv), _circ(a, xv * xv)
        sy, syy = _circ(ay, b), _circ(ay * y0, b)
        sxy = _circ(ay, xv)
        n = np.rint(n)
        with np.errstate(invalid="ignore", divide="ignore"):
            num = n * sxy - sx * sy
            den = np.sqrt(np.clip(n * sxx - sx * sx, 0, None) * np.clip(n * syy - sy * sy, 0, None))
            out[:, i] = np.where((n >= 3) & (den > 0), num / den, np.nan)
    return out


@dataclass(frozen=True)
class XcorrResult:
    lags: tuple[int, ...]
    r: tuple[float, ...]
    band: float  # simultaneous 95% band (scalar)
    n_shifts: int
    peak_lag: int
    clear_link: bool  # peak |r| outside the band
    stocks_first: bool  # peak at a negative lag outside the band, no positive lag outside
    adjacent_outside: bool  # reported only (A27 rule 12)


def xcorr_with_band(
    grid: SessionGrid, y: np.ndarray, lags: tuple[int, ...] = XCORR_LAGS
) -> XcorrResult:
    """Chart 1 for one ticker: r per lag and the scalar simultaneous band."""
    allr = xcorr_all_shifts(grid, y, lags)
    shifts = admissible_shifts(grid.n_sessions)
    band = float(np.nanquantile(np.nanmax(np.abs(allr[shifts]), axis=1), BAND_QUANTILE))
    r = allr[0]
    return summarise_xcorr(lags, r, band, len(shifts))


def summarise_xcorr(
    lags: tuple[int, ...], r: np.ndarray, band: float, n_shifts: int
) -> XcorrResult:
    absr = np.where(np.isnan(r), -1.0, np.abs(r))
    peak = int(np.argmax(absr))
    outside = absr > band
    lag_arr = np.array(lags)
    stocks_first = bool(outside[peak] and lags[peak] < 0 and not outside[lag_arr > 0].any())
    adjacent = any(
        0 <= j < len(lags) and outside[j] and r[j] * r[peak] > 0 for j in (peak - 1, peak + 1)
    )
    return XcorrResult(
        tuple(int(v) for v in lags),
        tuple(float(v) for v in r),
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


def shift_placebo(
    grid: SessionGrid,
    y: np.ndarray,
    pm_lags: tuple[int, ...],
    controls: np.ndarray | None = None,
) -> dict:
    """Primary PM statistic (sum of the PM-lag OLS coefficients) on the real alignment and
    under every admissible session shift; one-sided permutation p (A27 rule 11)."""
    betas = ols_all_shifts(grid, y, pm_lags, controls)
    stat = betas[:, 1 : 1 + len(pm_lags)].sum(axis=1)
    sims = stat[admissible_shifts(grid.n_sessions)]
    return {
        "observed": float(stat[0]),
        "n_shifts": int(len(sims)),
        "p90_of_shifts": float(np.nanquantile(sims, 0.90)),
        "permutation_p": permutation_p(float(stat[0]), sims),
    }


def permutation_p(observed: float, sims: np.ndarray) -> float:
    """One-sided (upper) permutation p, real alignment counted: (1 + #{sim >= obs}) / (1 + m)."""
    sims = sims[~np.isnan(sims)]
    return float((1 + np.sum(sims >= observed)) / (1 + len(sims)))

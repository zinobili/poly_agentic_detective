"""Estimators and decision rules of the election study (pure numpy/scipy; no I/O).

Ids follow docs/election/preregistration.md. Reuses `poly_actor.analysis.models` (OLS with
Newey-West HAC, linear tests, BH, Spearman, Fisher CI) without modifying it.

Implementation choices where the pre-registration is silent (stated in the step 9 report):
- Circular-shift permutation (H1): the PM change series of the complete-case sample is rolled by
  j rows, j drawn uniformly with replacement from {j : min(j, n - j) >= 20}, 1,000 draws. The
  statistic is |HAC t| of b; p = (1 + #{|t_j| >= |t_obs|}) / (1 + 1,000).
- Label permutation (H2): 10,000 random permutations of the AR labels; p = (1 + hits) / 10,001.
- H2b "top decile of the sample to date": |dP_t| >= the 90% quantile (linear interpolation) of
  |dP_s| over usable sessions s <= t; dP_t = 0 is never selected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

from poly_actor.analysis import models

SEED = 20261113
HAC_LAG_DAILY = 5
N_SHIFTS = 1000
MIN_SHIFT = 20
N_LABEL_PERMS = 10_000
CI_LEVEL = 0.90
ALPHA = 0.05
POWER = 0.80
PER_10PTS_PCT = 10.0  # b (log return per 1.0 of P) -> % per +10 probability points
MDE_BOUND_PCT = 0.5  # verdict table: MDE <= 0.5% per 10 points -> "bounded"
DIFF_ALPHA = 0.10  # verdict table: b_AI - b_placebo significant at 0.10
H2B_ALPHA = 0.10
WARMUP = 120
TOP_Q = 0.90


def rng(offset: int = 0) -> np.random.Generator:
    """Fixed-seed generator; each test gets its own stream so results do not depend on order."""
    return np.random.default_rng(SEED + offset)


# ---------------------------------------------------------------- H1 regression


@dataclass(frozen=True)
class BetaFit:
    b: float
    se: float
    t: float
    p_hac: float
    ci_low: float
    ci_high: float
    n: int
    r2: float
    partial_r2: float
    coef: tuple[float, ...]  # (a, b, controls...)

    def per10(self) -> dict:
        """Effect in % log return per +10 probability points, with the 90% CI."""
        k = PER_10PTS_PCT
        return {"b10_pct": self.b * k, "ci10_pct": [self.ci_low * k, self.ci_high * k]}


def design(x: np.ndarray, Z: np.ndarray | None) -> np.ndarray:
    cols = [np.ones(len(x)), x]
    if Z is not None and Z.size:
        cols += list(np.atleast_2d(Z.T)) if Z.ndim == 2 else [Z]
    return np.column_stack(cols)


def _ssr(X: np.ndarray, y: np.ndarray) -> float:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    u = y - X @ beta
    return float(u @ u)


def beta_fit(
    y: np.ndarray, x: np.ndarray, Z: np.ndarray | None = None, hac_lag: int = HAC_LAG_DAILY
) -> BetaFit:
    """y = a + b x + Z c + e, Newey-West HAC (`hac_lag`), 90% CI on b."""
    X = design(x, Z)
    fit = models.ols(X, y, cov="hac", hac_lag=hac_lag)
    w = np.zeros(X.shape[1])
    w[1] = 1.0
    lt = models.lin_test(fit, w, level=CI_LEVEL)
    yc = y - y.mean()
    ssr_full = _ssr(X, y)
    ssr_restr = _ssr(np.delete(X, 1, axis=1), y)
    return BetaFit(
        b=lt.estimate,
        se=lt.se,
        t=lt.t,
        p_hac=lt.p_two,
        ci_low=lt.ci_low,
        ci_high=lt.ci_high,
        n=fit.n,
        r2=1.0 - ssr_full / float(yc @ yc) if yc @ yc > 0 else float("nan"),
        partial_r2=(ssr_restr - ssr_full) / ssr_restr if ssr_restr > 0 else float("nan"),
        coef=tuple(float(v) for v in fit.beta),
    )


def admissible_shifts(n: int, min_shift: int = MIN_SHIFT) -> np.ndarray:
    j = np.arange(1, n)
    return j[np.minimum(j, n - j) >= min_shift]


def circular_perm_p(
    y: np.ndarray,
    x: np.ndarray,
    Z: np.ndarray | None,
    gen: np.random.Generator,
    n_shifts: int = N_SHIFTS,
    min_shift: int = MIN_SHIFT,
    hac_lag: int = HAC_LAG_DAILY,
) -> tuple[float, int]:
    """Two-sided circular-shift permutation p of b (statistic |HAC t|). Returns (p, distinct
    admissible shifts)."""
    shifts = admissible_shifts(len(x), min_shift)
    if not len(shifts):
        return float("nan"), 0
    t_obs = abs(beta_fit(y, x, Z, hac_lag).t)
    draws = gen.choice(shifts, size=n_shifts, replace=True)
    cache: dict[int, float] = {}
    hits = 0
    for j in draws:
        j = int(j)
        if j not in cache:
            cache[j] = abs(beta_fit(y, np.roll(x, j), Z, hac_lag).t)
        hits += cache[j] >= t_obs - 1e-12
    return (1 + hits) / (1 + n_shifts), len(shifts)


def mde(se: float, alpha: float = ALPHA, power: float = POWER) -> float:
    """Minimum detectable |b| at `power`, two-sided `alpha`, normal approximation."""
    return (stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)) * se


def h1_block(y: np.ndarray, x: np.ndarray, Z: np.ndarray | None, gen: np.random.Generator) -> dict:
    """Full H1-style row: HAC fit, 90% CI, permutation p, MDE (all per +10 points too)."""
    f = beta_fit(y, x, Z)
    p_perm, n_adm = circular_perm_p(y, x, Z, gen)
    out = asdict(f)
    out["coef"] = list(f.coef)
    out |= f.per10()
    out["se10_pct"] = f.se * PER_10PTS_PCT
    out["p_perm"] = p_perm
    out["n_shifts"] = N_SHIFTS
    out["n_distinct_shifts"] = n_adm
    out["mde10_pct"] = mde(f.se) * PER_10PTS_PCT
    return out


# ---------------------------------------------------------------- Wald: equal b across baskets


def wald_equal_b(Y: np.ndarray, x: np.ndarray, Z: np.ndarray | None, hac_lag: int) -> dict:
    """Wald test that the coefficient on x is equal across the columns of Y (same regressors),
    with a joint Newey-West covariance of the stacked scores. chi2 with (m - 1) df."""
    X = design(x, Z)
    n, k = X.shape
    m = Y.shape[1]
    bread = np.linalg.inv(X.T @ X)
    B = bread @ X.T @ Y  # k x m
    U = Y - X @ B
    G = np.concatenate([X * U[:, [i]] for i in range(m)], axis=1)  # n x (k m)
    meat = G.T @ G
    for j in range(1, hac_lag + 1):
        w = 1.0 - j / (hac_lag + 1.0)
        g = G[j:].T @ G[:-j]
        meat += w * (g + g.T)
    Bd = np.kron(np.eye(m), bread)
    V = Bd @ meat @ Bd
    idx = [i * k + 1 for i in range(m)]
    bvec = B[1, :]
    Vb = V[np.ix_(idx, idx)]
    R = np.zeros((m - 1, m))
    for i in range(m - 1):
        R[i, 0], R[i, i + 1] = 1.0, -1.0
    d = R @ bvec
    W = float(d @ np.linalg.solve(R @ Vb @ R.T, d))
    return {"wald": W, "df": m - 1, "p": float(stats.chi2.sf(W, m - 1)), "b": bvec.tolist()}


# ---------------------------------------------------------------- H2 cross-section


def per_stock_betas(R: np.ndarray, x: np.ndarray, Z: np.ndarray) -> np.ndarray:
    """OLS coefficients (k x N) of every column of R on [1, x, Z] (point estimates only)."""
    X = design(x, Z)
    B, *_ = np.linalg.lstsq(X, R, rcond=None)
    return B


def abnormal(r: np.ndarray, B: np.ndarray, z: np.ndarray) -> np.ndarray:
    """AR_i = r_i - sum_j c_ij z_j (controls only; no intercept, no x term)."""
    return r - z @ B[2:, :]


def _rank_corr_many(ra: np.ndarray, rb_perm: np.ndarray) -> np.ndarray:
    a = ra - ra.mean()
    bp = rb_perm - rb_perm.mean(axis=1, keepdims=True)
    return (bp @ a) / np.sqrt((a @ a) * (bp * bp).sum(axis=1))


def label_perm(
    b: np.ndarray, ar: np.ndarray, gen: np.random.Generator, n_perm: int = N_LABEL_PERMS
) -> dict:
    """Spearman rho(b, AR) with label-permutation p (one-sided > 0 and two-sided) and the
    Fisher-z 90% CI."""
    rho = models.spearman(b, ar)
    ra, rb = models.midranks(b), models.midranks(ar)
    perms = np.argsort(gen.random((n_perm, len(rb))), axis=1)
    sims = _rank_corr_many(ra, rb[perms])
    lo, hi = models.fisher_ci(rho, len(b), CI_LEVEL)
    return {
        "rho": rho,
        "n": int(len(b)),
        "p_one": float((1 + (sims >= rho - 1e-12).sum()) / (1 + n_perm)),
        "p_two": float((1 + (np.abs(sims) >= abs(rho) - 1e-12).sum()) / (1 + n_perm)),
        "ci90": [lo, hi],
        "n_perm": n_perm,
    }


def walk_forward(
    dp: np.ndarray,
    R: np.ndarray,
    Z: np.ndarray,
    warmup: int = WARMUP,
    top_q: float = TOP_Q,
) -> list[dict]:
    """H2b. Rows are usable pre-election sessions in time order. For every row t >= warmup with
    |dP_t| in the top decile of |dP| to date, estimate b_i on rows < t only and record
    sign(dP_t) * rho(b_i, AR_i,t). `n_est` is the number of estimation rows (= t)."""
    out = []
    a = np.abs(dp)
    for t in range(warmup, len(dp)):
        if dp[t] == 0 or a[t] < np.quantile(a[: t + 1], top_q):
            continue
        B = per_stock_betas(R[:t], dp[:t], Z[:t])
        ar = abnormal(R[t], B, Z[t])
        rho = models.spearman(B[1], ar)
        out.append({"row": t, "n_est": t, "dp": float(dp[t]), "signed_rho": np.sign(dp[t]) * rho})
    return out


def one_sided_t(values: list[float]) -> dict:
    v = np.asarray(values, dtype="float64")
    if len(v) < 2:
        return {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None, "t": None, "p": None}
    r = stats.ttest_1samp(v, 0.0, alternative="greater")
    return {
        "n": int(len(v)),
        "mean": float(v.mean()),
        "t": float(r.statistic),
        "p": float(r.pvalue),
    }


# ---------------------------------------------------------------- multiple testing + verdicts


def holm(pvalues: list[float], alpha: float = ALPHA) -> dict:
    """Holm step-down. Returns reject flags and the threshold each p was compared with (None if
    the step-down stopped before reaching it)."""
    p = np.asarray(pvalues, dtype="float64")
    m = len(p)
    order = np.argsort(p, kind="stable")
    reject = np.zeros(m, dtype=bool)
    thr: list[float | None] = [None] * m
    for rank, i in enumerate(order):
        thr[i] = alpha / (m - rank)
        if p[i] < thr[i]:
            reject[i] = True
        else:
            break
    return {"reject": reject.tolist(), "threshold": thr, "alpha": alpha}


H1_AI = "AI carried a partisan beta"
H1_SHARED = "Election beta, not AI-specific"
H1_BOUNDED = "No partisan beta (bounded)"
H1_NOISY = "Too noisy to tell"
H2_YES = "Betas predicted the election-night winners"
H2_NO = "Betas did not predict election night"


def h2_passes(h2_reject: bool, rho: float) -> bool:
    return bool(h2_reject and rho > 0)


def h1_verdict(
    h1_reject: bool,
    diff_p: float,
    mde10_pct: float,
    h2_pass: bool,
    h2b_p: float | None,
) -> tuple[str, str]:
    """Pre-registered verdict table, H1 rows (mechanical)."""
    h2b_pass = h2b_p is not None and h2b_p < H2B_ALPHA
    if h1_reject and diff_p < DIFF_ALPHA:
        return H1_AI, "High" if (h2_pass and h2b_pass) else "Medium"
    if h1_reject:
        return H1_SHARED, "Medium"
    if mde10_pct <= MDE_BOUND_PCT:
        return H1_BOUNDED, "Medium"
    return H1_NOISY, "Low"


def h2_verdict(h2_pass: bool, h2b_p: float | None) -> tuple[str, str]:
    """Pre-registered verdict table, H2 rows (mechanical)."""
    if h2_pass:
        return H2_YES, "Medium" if (h2b_p is not None and h2b_p < H2B_ALPHA) else "Low"
    return H2_NO, "Low"


def h4_verdict(lags: list[int], t: list[float], reject: list[bool]) -> str:
    """'odds first' only if a positive lag is BH-significant and no lag <= 0 has a larger |t|;
    'moves with' if lag 0 is BH-significant and largest; 'stocks first' if a negative lag is;
    otherwise 'no detectable ordering'."""
    if not any(reject):
        return "no detectable ordering"
    at = np.abs(np.asarray(t, dtype="float64"))
    k = lags[int(np.nanargmax(at))]
    if not reject[lags.index(k)]:
        return "no detectable ordering"
    if k > 0:
        return "odds first"
    return "moves with" if k == 0 else "stocks first"


# ---------------------------------------------------------------- misc


def logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 0.01, 0.99)
    return np.log(q / (1 - q))

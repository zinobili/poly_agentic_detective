"""Estimators and tests used by step 6 (pure numpy/scipy; no I/O).

OLS with Newey-West HAC, session-clustered and HC1 covariances; tests of linear combinations
with t(df) p-values; partial correlation from t; Benjamini-Hochberg; Spearman with an exact
permutation p; Fisher-z and BCa intervals; the sign test.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy import stats

CI_LEVEL = 0.90  # two-sided intervals reported with every effect (A27 rules 2-5)
ONE_SIDED_ALPHA = 0.05


# ---------------------------------------------------------------- OLS and covariances


@dataclass(frozen=True)
class OlsFit:
    beta: np.ndarray
    cov: np.ndarray
    df: int
    n: int
    cov_kind: str


def nw_lag(n: int) -> int:
    """Newey-West rule of thumb floor(4 (T/100)^(2/9)) (A27 rule 2)."""
    return int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def _bread(X: np.ndarray) -> np.ndarray:
    return np.linalg.inv(X.T @ X)


def ols(
    X: np.ndarray,
    y: np.ndarray,
    cov: str = "hac",
    groups: np.ndarray | None = None,
    hac_lag: int | None = None,
) -> OlsFit:
    """OLS with covariance 'hac' (Newey-West, Bartlett kernel; rows taken as adjacent in the
    given order), 'cluster' (by `groups`, CR1) or 'hc1'."""
    n, k = X.shape
    if n <= k:
        raise ValueError(f"too few rows ({n}) for {k} regressors")
    bread = _bread(X)
    beta = bread @ X.T @ y
    u = y - X @ beta
    if cov == "hac":
        L = nw_lag(n) if hac_lag is None else hac_lag
        Xu = X * u[:, None]
        meat = Xu.T @ Xu
        for j in range(1, L + 1):
            w = 1.0 - j / (L + 1.0)
            g = Xu[j:].T @ Xu[:-j]
            meat += w * (g + g.T)
        V = bread @ meat @ bread
    elif cov == "cluster":
        if groups is None:
            raise ValueError("cluster covariance needs groups")
        Xu = X * u[:, None]
        _, inv = np.unique(groups, return_inverse=True)
        sums = np.zeros((inv.max() + 1, k))
        np.add.at(sums, inv, Xu)
        G = sums.shape[0]
        c = G / (G - 1) * (n - 1) / (n - k)
        V = c * bread @ (sums.T @ sums) @ bread
    elif cov == "hc1":
        Xu = X * u[:, None]
        V = n / (n - k) * bread @ (Xu.T @ Xu) @ bread
    else:
        raise ValueError(f"unknown covariance {cov!r}")
    df = (np.unique(groups).size - 1) if cov == "cluster" else n - k
    return OlsFit(beta, V, int(df), n, cov)


@dataclass(frozen=True)
class LinTest:
    """Test of w'beta. `p_upper` is the one-sided p for H1: w'beta > 0."""

    estimate: float
    se: float
    t: float
    df: int
    p_upper: float
    p_two: float
    ci_low: float
    ci_high: float

    @property
    def p_lower(self) -> float:
        return 1.0 - self.p_upper


def lin_test(fit: OlsFit, w: np.ndarray, level: float = CI_LEVEL) -> LinTest:
    est = float(w @ fit.beta)
    se = float(math.sqrt(w @ fit.cov @ w))
    t = est / se if se > 0 else 0.0
    dist = stats.t(fit.df)
    half = dist.ppf(0.5 + level / 2.0) * se
    return LinTest(
        est, se, t, fit.df, float(dist.sf(t)), float(2 * dist.sf(abs(t))), est - half, est + half
    )


def weights(names: tuple[str, ...], terms: tuple[str, ...]) -> np.ndarray:
    """Selector vector summing the named coefficients."""
    return np.array([1.0 if n in terms else 0.0 for n in names])


def t_to_r(t: float, df: int) -> float:
    """Partial correlation implied by a t statistic (the unit of the A27 MDEs)."""
    return float(t / math.sqrt(t * t + df))


def bound_r(test: LinTest, upper: bool = True) -> float:
    """One-sided 95% bound of the effect in partial-correlation units (A27 rules 5, 10)."""
    crit = stats.t(test.df).ppf(1.0 - ONE_SIDED_ALPHA)
    return t_to_r(test.t + crit if upper else test.t - crit, test.df)


# ---------------------------------------------------------------- multiple testing


def bh(pvalues: list[float] | np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg step-up. Returns (reject mask, adjusted p-values)."""
    p = np.asarray(pvalues, dtype="float64")
    m = len(p)
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / np.arange(1, m + 1)
    adj_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    adj = np.empty(m)
    adj[order] = np.minimum(adj_sorted, 1.0)
    passed = p[order] <= q * np.arange(1, m + 1) / m
    reject = np.zeros(m, dtype=bool)
    if passed.any():
        last = np.flatnonzero(passed).max()
        reject[order[: last + 1]] = True
    return reject, adj


# ---------------------------------------------------------------- rank tests


def midranks(x: np.ndarray) -> np.ndarray:
    return stats.rankdata(x, method="average")


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = midranks(np.asarray(x)), midranks(np.asarray(y))
    rx, ry = rx - rx.mean(), ry - ry.mean()
    den = math.sqrt((rx @ rx) * (ry @ ry))
    return float(rx @ ry / den) if den > 0 else 0.0


EXACT_MAX_N = 12
MC_PERMUTATIONS = 200_000


def _exact_dot_distribution(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Counts of sum_i a_i b_pi(i) over all n! permutations (a, b non-negative integers).

    Dynamic programme over subsets of b, one count array (indexed by the partial sum) per
    used-mask. Returns counts indexed by the full sum."""
    n = len(a)
    size = int(np.sort(a)[::-1] @ np.sort(b)[::-1]) + 1
    layer: dict[int, np.ndarray] = {0: np.zeros(size, dtype=np.int64)}
    layer[0][0] = 1
    for i in range(n):
        nxt: dict[int, np.ndarray] = {}
        for mask, counts in layer.items():
            for j in range(n):
                if mask >> j & 1:
                    continue
                add = int(a[i] * b[j])
                tgt = nxt.get(mask | 1 << j)
                if tgt is None:
                    tgt = nxt[mask | 1 << j] = np.zeros(size, dtype=np.int64)
                tgt[add:] += counts[: size - add]
        layer = nxt
    return layer[(1 << n) - 1]


def _tail_hits(sums: np.ndarray, counts: np.ndarray, obs: float, centre: float, alt: str) -> float:
    if alt == "less":
        return float(counts[sums <= obs].sum())
    if alt == "greater":
        return float(counts[sums >= obs].sum())
    return float(counts[np.abs(sums - centre) >= abs(obs - centre) - 1e-9].sum())


def spearman_perm_p(
    x: np.ndarray, y: np.ndarray, alternative: str = "less", seed: int = 0
) -> tuple[float, str]:
    """Permutation p of Spearman's rho. Exact for n <= 12 (midranks, so ties are handled),
    Monte Carlo with a fixed seed above that. Returns (p, method)."""
    rx, ry = midranks(np.asarray(x)), midranks(np.asarray(y))
    n = len(rx)
    a, b = np.rint(2 * rx).astype(int), np.rint(2 * ry).astype(int)  # midranks are k/2
    obs = int(a @ b)
    centre = float(a.sum() * b.sum()) / n
    if n <= EXACT_MAX_N:
        counts = _exact_dot_distribution(a, b)
        sums = np.arange(len(counts))
        return _tail_hits(sums, counts, obs, centre, alternative) / counts.sum(), "exact"
    rng = np.random.default_rng(seed)
    perms = np.argsort(rng.random((MC_PERMUTATIONS, n)), axis=1)
    sims = (b[perms] * a).sum(axis=1)
    hits = _tail_hits(sims, np.ones(len(sims)), obs, centre, alternative)
    return (hits + 1) / (MC_PERMUTATIONS + 1), "monte_carlo"


def fisher_ci(rho: float, n: int, level: float = CI_LEVEL) -> tuple[float, float]:
    """Interval for Spearman's rho, Fisher z with SE sqrt(1.06 / (n - 3)) (A27 review B3)."""
    if n <= 3:
        return (-1.0, 1.0)
    z = math.atanh(max(min(rho, 0.999999), -0.999999))
    half = stats.norm.ppf(0.5 + level / 2.0) * math.sqrt(1.06 / (n - 3))
    return math.tanh(z - half), math.tanh(z + half)


def sign_test(x: np.ndarray, y: np.ndarray) -> tuple[int, int, float]:
    """Releases with sign(x) * sign(y) < 0, zeros dropped; one-sided binomial p (A27 m8).

    Returns (negative count, n used, p)."""
    s = np.sign(x) * np.sign(y)
    used = s != 0
    k, n = int((s[used] < 0).sum()), int(used.sum())
    p = float(stats.binomtest(k, n, 0.5, alternative="greater").pvalue) if n else 1.0
    return k, n, p


# ---------------------------------------------------------------- bootstrap


def bca_ci(
    data: np.ndarray,
    stat: Callable[[np.ndarray], np.ndarray],
    level: float = CI_LEVEL,
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """BCa bootstrap interval over the first axis of `data` (rows = events).

    `stat` maps an (m, ...) array to a statistic array (vectorised over trailing axes).
    Returns (low, high) with the shape of the statistic."""
    data = np.asarray(data, dtype="float64")
    n = data.shape[0]
    rng = np.random.default_rng(seed)
    theta = np.asarray(stat(data))
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = np.stack([np.asarray(stat(data[i])) for i in idx])
    with np.errstate(divide="ignore", invalid="ignore"):
        prop = (boots < theta).mean(axis=0) + 0.5 * (boots == theta).mean(axis=0)
        z0 = stats.norm.ppf(np.clip(prop, 1e-6, 1 - 1e-6))
        jack = np.stack([np.asarray(stat(np.delete(data, i, axis=0))) for i in range(n)])
        d = jack.mean(axis=0) - jack
        num = (d**3).sum(axis=0)
        den = 6.0 * ((d**2).sum(axis=0)) ** 1.5
        acc = np.where(den > 0, num / den, 0.0)
        out = []
        for alpha in (0.5 - level / 2.0, 0.5 + level / 2.0):
            z = stats.norm.ppf(alpha)
            adj = stats.norm.cdf(z0 + (z0 + z) / (1 - acc * (z0 + z)))
            adj = np.nan_to_num(adj, nan=alpha)
            out.append(_quantile_per_cell(boots, adj))
    return out[0], out[1]


def _quantile_per_cell(boots: np.ndarray, q: np.ndarray) -> np.ndarray:
    flat = boots.reshape(boots.shape[0], -1)
    qs = np.broadcast_to(q, boots.shape[1:]).reshape(-1)
    res = np.array([np.quantile(flat[:, j], qs[j]) for j in range(flat.shape[1])])
    return res.reshape(boots.shape[1:])


def spearman_bootstrap_ci(
    x: np.ndarray, y: np.ndarray, level: float = CI_LEVEL, n_boot: int = 5000, seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap interval of Spearman's rho over releases (A27 review M8)."""
    rng = np.random.default_rng(seed)
    n = len(x)
    vals = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        if np.unique(x[i]).size < 2 or np.unique(y[i]).size < 2:
            continue
        vals.append(spearman(x[i], y[i]))
    lo, hi = np.quantile(vals, [0.5 - level / 2.0, 0.5 + level / 2.0])
    return float(lo), float(hi)

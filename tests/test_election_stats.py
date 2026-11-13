"""Step 9 estimators on synthetic data with known answers (hand-off "rules as examples")."""

from __future__ import annotations

import numpy as np
import pytest

from poly_actor.election import intraday as itd
from poly_actor.election import stats as st


def daily_draw(seed: int, b: float, n: int = 330, noise: float = 0.004):
    g = np.random.default_rng(seed)
    dp = np.round(g.standard_t(4, n) * 0.02 / 1.4 / 0.005) * 0.005
    rsp, tlt = g.normal(0, 0.008, n), g.normal(0, 0.006, n)
    y = b * dp + 1.1 * rsp + g.normal(0, noise, n)
    return y, dp, np.column_stack([rsp, tlt])


# ---------------------------------------------------------------- H1


def test_h1_planted_beta_recovered_and_permutation_detects_it():
    # sd(dP) ~ 0.02, so b sd(dP) / noise * sqrt(330) ~ 3.6: theoretical HAC power ~ 95%
    hits, within = 0, 0
    for seed in range(50):
        y, dp, Z = daily_draw(seed, 0.03, noise=0.003)
        f = st.beta_fit(y, dp, Z)
        within += abs(f.b - 0.03) <= 2 * f.se
        p, _ = st.circular_perm_p(y, dp, Z, st.rng(seed))
        hits += p < 0.05
    assert within >= 45  # ~95% coverage of a 2-se band
    assert hits >= 40  # >= 80% of 50 seeds


def test_h1_noise_rejects_at_nominal_rate():
    hits = 0
    for seed in range(100):
        y, dp, Z = daily_draw(1000 + seed, 0.0)
        p, _ = st.circular_perm_p(y, dp, Z, st.rng(seed), n_shifts=400)
        hits += p < 0.05
    assert 0 <= hits <= 14


def test_circular_shifts_respect_the_minimum():
    sh = st.admissible_shifts(330)
    assert sh.min() == 20 and sh.max() == 310 and len(sh) == 291
    assert st.admissible_shifts(39).size == 0


def test_placebo_with_same_beta_gives_election_beta_not_ai_specific():
    g = np.random.default_rng(7)
    n = 330
    dp = np.round(g.standard_t(4, n) * 0.02 / 1.4 / 0.005) * 0.005
    rsp, tlt = g.normal(0, 0.008, n), g.normal(0, 0.006, n)
    Z = np.column_stack([rsp, tlt])
    y_ai = 0.05 * dp + rsp + g.normal(0, 0.004, n)
    y_pl = 0.05 * dp + rsp + g.normal(0, 0.004, n)
    ai = st.h1_block(y_ai, dp, Z, st.rng(1))
    diff = st.h1_block(y_ai - y_pl, dp, Z, st.rng(3))
    assert abs(diff["b"]) < 2 * diff["se"]
    hm = st.holm([ai["p_perm"], 0.5])
    assert hm["reject"][0]
    v, c = st.h1_verdict(hm["reject"][0], diff["p_perm"], ai["mde10_pct"], False, None)
    assert diff["p_perm"] >= 0.10 and (v, c) == (st.H1_SHARED, "Medium")


def test_mde_is_2_8_se():
    assert st.mde(1.0) == pytest.approx(2.8016, abs=1e-3)


def test_partial_r2_matches_t_identity_under_ols():
    y, dp, Z = daily_draw(3, 0.05)
    f = st.beta_fit(y, dp, Z)
    assert 0 < f.partial_r2 < f.r2 < 1


# ---------------------------------------------------------------- Holm and verdict table


def test_holm_003_004_neither_rejected():
    h = st.holm([0.03, 0.04])
    assert h["reject"] == [False, False] and h["threshold"][0] == 0.025


def test_holm_both_rejected_when_small():
    assert st.holm([0.01, 0.04])["reject"] == [True, True]


@pytest.mark.parametrize(
    "h1_rej, diff_p, mde, h2_pass, h2b_p, expected",
    [
        (True, 0.05, 0.3, False, None, (st.H1_AI, "Medium")),
        (True, 0.05, 0.3, True, 0.05, (st.H1_AI, "High")),
        (True, 0.05, 0.3, True, 0.20, (st.H1_AI, "Medium")),
        (True, 0.40, 0.3, True, 0.05, (st.H1_SHARED, "Medium")),
        (False, 0.01, 0.4, False, None, (st.H1_BOUNDED, "Medium")),
        (False, 0.01, 0.5, False, None, (st.H1_BOUNDED, "Medium")),
        (False, 0.30, 0.8, False, None, (st.H1_NOISY, "Low")),
    ],
)
def test_h1_verdict_table(h1_rej, diff_p, mde, h2_pass, h2b_p, expected):
    assert st.h1_verdict(h1_rej, diff_p, mde, h2_pass, h2b_p) == expected


def test_h1_p030_mde08_is_too_noisy():
    h = st.holm([0.30, 0.9])
    assert st.h1_verdict(h["reject"][0], 0.5, 0.8, False, None) == (st.H1_NOISY, "Low")


@pytest.mark.parametrize(
    "rej, rho, h2b_p, expected",
    [
        (True, 0.4, 0.05, (st.H2_YES, "Medium")),
        (True, 0.4, 0.30, (st.H2_YES, "Low")),
        (True, 0.4, None, (st.H2_YES, "Low")),
        (True, -0.4, 0.05, (st.H2_NO, "Low")),
        (False, 0.4, 0.05, (st.H2_NO, "Low")),
    ],
)
def test_h2_verdict_table(rej, rho, h2b_p, expected):
    assert st.h2_verdict(st.h2_passes(rej, rho), h2b_p) == expected


# ---------------------------------------------------------------- H2 cross-section


def test_cross_section_planted_rank_correlation_found():
    g = np.random.default_rng(11)
    b = g.normal(0, 0.05, 29)
    ar = b * 0.245 + g.normal(0, 0.004, 29)
    r = st.label_perm(b, ar, st.rng(0))
    assert r["rho"] > 0.5 and r["p_one"] < 0.01 and r["p_two"] < 0.02
    assert r["ci90"][0] < r["rho"] < r["ci90"][1]


def test_cross_section_shuffled_betas_give_uniform_p():
    g = np.random.default_rng(12)
    ps = []
    for i in range(200):
        b = g.normal(0, 0.05, 29)
        ar = g.permutation(b) * 0.245 + g.normal(0, 0.004, 29)
        ps.append(st.label_perm(b, ar, st.rng(i), n_perm=1000)["p_one"])
    ps = np.array(ps)
    assert 0.0 <= (ps < 0.05).mean() <= 0.10 and 0.4 < ps.mean() < 0.6


def test_abnormal_return_removes_controls_only():
    B = np.array([[0.1], [5.0], [1.2], [0.3]])  # a, b, c, d
    assert st.abnormal(np.array([0.05]), B, np.array([0.02, -0.01]))[0] == pytest.approx(
        0.05 - 1.2 * 0.02 + 0.3 * 0.01
    )


# ---------------------------------------------------------------- H2b (no look-ahead)


def _wf_data(seed=5, n=300, N=29):
    g = np.random.default_rng(seed)
    dp = np.round(g.standard_t(4, n) * 0.02 / 1.4 / 0.005) * 0.005
    Z = np.column_stack([g.normal(0, 0.008, n), g.normal(0, 0.006, n)])
    R = Z[:, :1] + g.normal(0, 0.01, (n, N))
    return dp, R, Z


def test_walk_forward_estimates_on_rows_before_t_only():
    dp, R, Z = _wf_data()
    days = st.walk_forward(dp, R, Z)
    assert days and all(d["n_est"] == d["row"] >= st.WARMUP for d in days)


def test_walk_forward_day_t_is_not_in_its_own_estimation():
    """Plant a huge day-t outlier that would make b_i ~ AR_i,t if day t leaked in. Each selected
    day has a different random pattern v; with no leak the mean signed rho is ~0."""
    dp, R, Z = _wf_data(seed=9)
    g = np.random.default_rng(1)
    base = st.walk_forward(dp, R, Z)
    rows = [d["row"] for d in base]
    R2 = R.copy()
    for t in rows:
        R2[t] += np.sign(dp[t]) * 50 * abs(dp[t]) * g.normal(0, 1, R.shape[1])
    rhos = [d["signed_rho"] for d in st.walk_forward(dp, R2, Z)]
    assert abs(np.mean(rhos)) < 0.25  # a leak gives ~ +1


def test_walk_forward_top_decile_to_date_and_zero_never_selected():
    dp = np.r_[np.full(130, 0.01), 0.0, 0.05, 0.005]
    R = np.random.default_rng(0).normal(0, 0.01, (len(dp), 5))
    Z = np.random.default_rng(1).normal(0, 0.01, (len(dp), 2))
    rows = [d["row"] for d in st.walk_forward(dp, R, Z)]
    assert 131 in rows and 130 not in rows and 132 not in rows
    assert all(r >= st.WARMUP for r in rows)


# ---------------------------------------------------------------- Wald


def test_wald_equal_b_size_and_power():
    g = np.random.default_rng(3)
    n = 330
    x = g.normal(0, 0.02, n)
    Z = g.normal(0, 0.008, (n, 2))
    same = np.column_stack([0.05 * x + g.normal(0, 0.01, n) for _ in range(4)])
    diff = np.column_stack([b * x + g.normal(0, 0.01, n) for b in (0.0, 0.0, 0.0, 0.3)])
    assert st.wald_equal_b(same, x, Z, 5)["p"] > 0.05
    assert st.wald_equal_b(diff, x, Z, 5)["p"] < 0.001


# ---------------------------------------------------------------- H4 lags


def test_hourly_lag_plus1_at_first_bar_is_not_formed():
    x = np.array([[np.nan, 1.0, 2.0], [np.nan, 3.0, 4.0]])  # first bar has no dP (panel rule)
    lag1 = itd.lag_within(x, 1)
    assert np.isnan(lag1[1, 0]) and np.isnan(lag1[1, 1])  # never the previous session's 2.0
    assert lag1[1, 2] == 3.0
    lagm1 = itd.lag_within(x, -1)
    assert lagm1[0, 2] != lagm1[0, 2] and lagm1[0, 1] == 2.0  # bar 1 pairs with bar 2's dP


def test_h4_planted_odds_first_and_stocks_first():
    g = np.random.default_rng(4)
    S, P = 300, 7
    x = g.normal(0, 0.01, (S, P))
    x[:, 0] = np.nan
    for lag, word in ((1, "odds first"), (-1, "stocks first"), (0, "moves with")):
        y = 0.3 * np.nan_to_num(itd.lag_within(x, lag)) + g.normal(0, 0.003, (S, P))
        out = itd.h4(y, x)
        best = max(out["rows"], key=lambda r: abs(r["t"]))
        assert best["lag"] == lag and out["verdict"] == word


def test_h4_noise_no_ordering():
    g = np.random.default_rng(6)
    x = g.normal(0, 0.01, (200, 7))
    x[:, 0] = np.nan
    out = itd.h4(g.normal(0, 0.003, (200, 7)), x)
    assert out["verdict"] == "no detectable ordering"


def test_walk_forward_decile_uses_only_sessions_to_date():
    # row 125 is a top-decile move given rows <= 125, but not given the (later, larger) rows
    dp = np.r_[np.full(125, 0.01), 0.02, np.full(75, 0.10)]
    g = np.random.default_rng(2)
    rows = [
        d["row"]
        for d in st.walk_forward(dp, g.normal(0, 0.01, (201, 5)), g.normal(0, 0.01, (201, 2)))
    ]
    assert 125 in rows

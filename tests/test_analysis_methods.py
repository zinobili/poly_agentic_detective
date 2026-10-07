"""Unit tests of the step 6 building blocks, each against an independent oracle or a
hand-computed example."""

from __future__ import annotations

import itertools
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import analysis_synth as synth
from poly_actor.analysis import cpi, events, models, placebo, primary, sample, studies, verdict
from poly_actor.analysis.verdict import Facts

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------- models


def test_newey_west_lag_rule():
    assert models.nw_lag(2404) == 8 and models.nw_lag(1321) == 7


def test_hac_with_zero_lags_equals_hc0():
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(200), rng.standard_normal(200)])
    y = X @ [0.1, 0.5] + rng.standard_normal(200) * (1 + np.abs(X[:, 1]))
    fit = models.ols(X, y, "hac", hac_lag=0)
    u = y - X @ fit.beta
    bread = np.linalg.inv(X.T @ X)
    hc0 = bread @ (X.T * u**2) @ X @ bread
    assert np.allclose(fit.cov, hc0)


def test_lin_test_one_sided_p_matches_t_distribution():
    rng = np.random.default_rng(1)
    X = np.column_stack([np.ones(300), rng.standard_normal(300)])
    y = 0.2 * X[:, 1] + rng.standard_normal(300)
    lt = models.lin_test(models.ols(X, y, "hc1"), np.array([0.0, 1.0]))
    assert lt.p_upper < 0.01 and lt.p_two == pytest.approx(2 * lt.p_upper)
    assert lt.ci_low < lt.estimate < lt.ci_high


def test_t_to_r_matches_the_mde_design():
    # MDE r ~ (1.645 + 0.842) / sqrt(n): at n = 2404 the partial r of t = 2.487 is ~0.0507
    assert models.t_to_r(2.487, 2400) == pytest.approx(0.0507, abs=5e-4)


def test_exact_spearman_p_matches_brute_force_with_ties():
    x = np.array([1.0, 2.0, 2.0, 4.0, 5.0, 6.0, 7.0])
    y = np.array([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0])
    p, method = models.spearman_perm_p(x, y, "less")
    r = models.spearman(x, y)
    brute = np.mean(
        [models.spearman(x, y[list(q)]) <= r + 1e-12 for q in itertools.permutations(range(7))]
    )
    assert method == "exact" and p == pytest.approx(brute)


def test_fisher_interval_width_at_n_11():
    lo, hi = models.fisher_ci(0.0, 11)
    assert lo == pytest.approx(-0.536, abs=2e-3) and hi == pytest.approx(0.536, abs=2e-3)


def test_sign_test_drops_zeros():
    k, n, p = models.sign_test(np.array([1, -1, 0, 2]), np.array([-1, 1, 5, -3]))
    assert (k, n) == (3, 3) and p == pytest.approx(0.125)


def test_bca_interval_covers_the_mean_of_a_normal_sample():
    rng = np.random.default_rng(3)
    hits = 0
    for _ in range(100):
        data = rng.standard_normal((20, 1))
        lo, hi = models.bca_ci(data, lambda a: a.mean(axis=0), n_boot=500)
        hits += lo[0] < 0 < hi[0]
    assert 80 <= hits <= 97  # nominal 90%


# ---------------------------------------------------------------- grid, lags, shifts


def test_fft_cross_correlation_equals_direct_for_every_shift():
    grid = synth.to_grid(synth.make(4, n_sessions=60))
    y = grid.returns["TLT"]
    allr = placebo.xcorr_all_shifts(grid, y)
    for j in (0, 7, 31):
        direct = placebo.xcorr(sample.shift_sessions(grid, j), y)
        assert np.allclose(allr[j], direct, equal_nan=True)


def test_fft_robust_t_equals_direct_for_every_shift():
    """A28 item 1: the studentized band statistic, FFT over all shifts vs the direct loop."""
    grid = synth.to_grid(synth.make(4, n_sessions=60, realistic=True))
    y = grid.returns["TLT"]
    _, allt = placebo.xcorr_stats_all_shifts(grid, y)
    for j in (0, 7, 31):
        direct = placebo.xcorr_t(sample.shift_sessions(grid, j), y)
        assert np.allclose(allt[j], direct, equal_nan=True, atol=1e-10)


def test_robust_t_hand_example():
    """t = sum xc*yc / sqrt(sum xc^2 yc^2). x = (1, 2, 3), y = (1, 2, 4): xc = (-1, 0, 1),
    yc = (-4/3, -1/3, 5/3), numerator 3, denominator sqrt(41/9), t = 9 / sqrt(41)."""
    t = placebo._robust_t(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 4.0]))
    assert t == pytest.approx(9 / np.sqrt(41))


def test_hac_t_placebo_equals_build_design_loop_and_the_primary():
    """A28 item 1: the Fed shift statistic is the HAC t of b0+b1+b2; shift 0 is the primary t
    and every shift equals a fresh `build_design` + `ols` + `lin_test` on the shifted grid."""
    grid = synth.to_grid(synth.make(7, n_sessions=60))
    y = grid.returns["TLT"]
    ts = placebo.hac_t_all_shifts(grid, y, primary.FED_LAGS, shifts=np.array([0, 9, 30]))
    _, reg = primary.fed_regression(grid)
    assert ts[0] == pytest.approx(reg.tests["sum"].t, rel=1e-10)
    for j in (9, 30):
        d = sample.build_design(sample.shift_sessions(grid, j), y, primary.FED_LAGS)
        fit = models.ols(d.X, d.y, cov="hac")
        w = models.weights(d.names, ("pm_lag0", "pm_lag1", "pm_lag2"))
        assert ts[j] == pytest.approx(models.lin_test(fit, w).t, rel=1e-10)
    assert np.isnan(ts[1])  # shifts not asked for stay NaN


def test_hac_t_placebo_with_controls_equals_build_design_loop():
    grid = synth.to_grid(synth.make(8, n_sessions=40))
    y = grid.returns["TLT"]
    controls = np.random.default_rng(1).standard_normal((40, 7, 2))
    controls[3, 2, 0] = np.nan
    ts = placebo.hac_t_all_shifts(grid, y, (1,), controls, shifts=np.array([11]))
    d = sample.build_design(sample.shift_sessions(grid, 11), y, (1,), controls)
    lt = models.lin_test(models.ols(d.X, d.y, cov="hac"), np.array([0.0, 1.0, 0.0, 0.0]))
    assert ts[11] == pytest.approx(lt.t, rel=1e-10)


def test_band_is_read_from_t_not_r():
    """A28 item 1: a large r with a small robust t is inside the band, and vice versa."""
    lags = tuple(range(-6, 7))
    r, t = np.zeros(13), np.zeros(13)
    r[lags.index(2)], t[lags.index(2)] = 0.5, 1.0  # big r, small t: inside
    r[lags.index(-1)], t[lags.index(-1)] = 0.05, 4.0  # small r, big t: outside
    out = placebo.summarise_xcorr(lags, r, 3.0, 10, t)
    assert out.clear_link and out.peak_lag == -1 and out.stocks_first
    assert out.r[lags.index(2)] == 0.5 and out.t[lags.index(-1)] == 4.0


def test_fft_ols_equals_loop_for_every_shift():
    grid = synth.to_grid(synth.make(5, n_sessions=60))
    y = grid.returns["TLT"]
    controls = np.random.default_rng(0).standard_normal((60, 7, 2))
    betas = placebo.ols_all_shifts(grid, y, (1, 2), controls)
    for j in (0, 9):
        d = sample.build_design(sample.shift_sessions(grid, j), y, (1, 2), controls)
        assert np.allclose(betas[j], np.linalg.lstsq(d.X, d.y, rcond=None)[0])


def test_admissible_shifts_are_all_enumerated():
    assert placebo.admissible_shifts(12).tolist() == [5, 6, 7]


def test_shift_moves_only_the_pm_side():
    grid = synth.to_grid(synth.make(6, n_sessions=10))
    moved = sample.shift_sessions(grid, 3)
    assert np.array_equal(moved.x[0], grid.x[3], equal_nan=True)
    assert np.array_equal(moved.returns["TLT"], grid.returns["TLT"], equal_nan=True)


def test_band_flags_stocks_first_only_without_a_positive_lag_outside():
    lags = tuple(range(-6, 7))
    r = np.zeros(13)
    r[lags.index(-2)] = 0.3
    assert placebo.summarise_xcorr(lags, r, 0.1, 10).stocks_first
    r[lags.index(3)] = 0.2
    assert not placebo.summarise_xcorr(lags, r, 0.1, 10).stocks_first


def test_spot_controls_are_clock_time_and_cross_the_open():
    grid = synth.to_grid(synth.make(0, n_sessions=3))
    price = {}

    def spot_at(instants):
        return np.array([price.setdefault(int(t), 100.0 + (int(t) // 3600) % 97) for t in instants])

    ctrl = primary.spot_controls(grid, spot_at)
    t = int(grid.ts_end[1, 0])  # first bar of a session: lags reach back before the open
    for k in range(4):
        expect = np.log(spot_at([t - 3600 * k])[0]) - np.log(spot_at([t - 3600 * (k + 1)])[0])
        assert ctrl[1, 0, k] == pytest.approx(expect)


def test_fed_signal_sign_is_dovishness():
    panel = synth.to_panel(synth.make(0, n_sessions=5))
    grid = sample.build_grid(panel, "fed_decision")
    first = panel.iloc[0]
    assert grid.x[0, 0] == pytest.approx(-first["signal_change"])


def test_max_age_filter_and_age_900_grid():
    sy = synth.make(0, n_sessions=5, stale_rate=0.0)
    sy.age[2, 3] = 1200.0
    panel = synth.to_panel(sy)
    assert sample.build_grid(panel, "fed_decision").pm_ok[2, 3]
    assert not sample.build_grid(panel, "fed_decision", sample.ROBUST_PM_AGE_S).pm_ok[2, 3]


# ---------------------------------------------------------------- CPI


def test_same_clock_across_a_dst_switch():
    t1 = int(datetime(2025, 3, 12, 7, 30, tzinfo=ET).timestamp())  # EDT
    t0 = cpi.same_clock(t1, date(2025, 3, 5))  # EST, before the 9 March switch
    assert datetime.fromtimestamp(t0, ET).strftime("%H:%M") == "07:30"
    assert t1 - t0 == 7 * 86400 - 3600


def test_sessions_back_counts_sessions_not_days():
    days = [date(2025, 1, d) for d in (2, 3, 6, 7, 8, 9, 10, 13)]
    assert cpi.sessions_back(days, date(2025, 1, 13), 5) == date(2025, 1, 6)


def _vtab(level, center, valid):
    return pd.DataFrame(
        {
            "event_id": "E",
            "resolved": True,
            "valid1": valid,
            "level1": level,
            "winning_center": center,
        }
    )


def test_validation_denominator_is_valid_months_and_needs_eight():
    level = np.full(10, 2.5)
    center = np.r_[np.full(6, 2.5), np.full(4, 3.0)]
    valid = np.r_[np.ones(9, bool), False]
    v = cpi.validate(_vtab(level, center, valid))
    assert (v.n_valid, v.n_within, v.passed) == (9, 6, True)
    v7 = cpi.validate(_vtab(level[:7], center[:7], valid[:7]))
    assert not v7.passed  # 6 of 7 within, but fewer than 8 valid months


def test_validation_tolerance_is_one_tenth_inclusive():
    v = cpi.validate(_vtab(np.array([2.6] * 8), np.array([2.5] * 8), np.ones(8, bool)))
    assert v.n_within == 8


def test_placebo_candidates_keep_two_sessions_away():
    days = [date(2025, 1, d) for d in range(1, 21)]
    keep = cpi.placebo_candidates(days, {date(2025, 1, 10)})
    assert date(2025, 1, 8) not in keep and date(2025, 1, 12) not in keep
    assert date(2025, 1, 7) in keep and date(2025, 1, 13) in keep


def test_cpi_drop_largest_removes_one_release_at_n_12():
    proxy = np.arange(12, dtype=float)
    p, o = cpi.drop_largest(proxy, proxy)
    assert len(p) == 11 and 11.0 not in p


# ---------------------------------------------------------------- events


def test_event_path_inserts_the_gap_between_sessions():
    grid = synth.to_grid(synth.make(0, n_sessions=3, hole_rate=0.0))
    cells, where = studies.flat_index(grid)
    gaps = np.array([0.0, 0.01, 0.02])
    path = events.event_path(grid, grid.returns["TLT"], gaps, cells, where, (0, 4), 3, 6, 1.0)
    assert path.labels == ("-3", "-2", "-1", "0", "+1", "+2", "gap", "+3", "+4", "+5", "+6")
    assert path.steps[6] == 0.01
    folded = events.fold_gaps(path)
    assert folded.gap_marks == (6,) and len(folded.steps) == 10
    assert folded.steps[6] == pytest.approx(0.01 + grid.returns["TLT"][1, 0])


def test_unsigned_events_are_counted_not_used():
    grid = synth.to_grid(synth.make(0, n_sessions=40, hole_rate=0.0))
    grid.x[:, 3] = 0.1  # below the 0.5 bp Fed threshold on every bar before bar 0
    out = studies.bar_study(
        grid,
        grid.returns["TLT"],
        np.zeros(40),
        [(s, 4) for s in range(1, 30)],
        [],
        0.5,
        (3, 6),
        fold=False,
    )
    assert out is None  # nothing signed, so no chart


def test_greedy_extremes_keep_two_days_apart():
    v = np.array([5.0, 4.9, 1.0, 4.0, np.nan, 3.0])
    assert events.greedy_extremes(v, 3, 2, largest=True) == [0, 3, 5]


def test_recession_days_sum_spliced_changes_between_closes():
    panel = synth.recession_panel(0)
    days = studies.recession_days(panel, ("SPY", "IWM", "TLT"))
    i = 5
    bars = panel.sort_values("ts_end")
    day = days.sessions[i]
    expect = bars.loc[bars["session"] == day, "signal_change"].sum()
    assert days.dp[i] == pytest.approx(expect)
    assert np.isnan(days.dp[0])


# ---------------------------------------------------------------- verdict rules (A27 rule 7)


BASE = dict(sufficient=True, p_one=0.5, p_two=1.0, upper_r=0.01, lower_r=-0.05)


@pytest.mark.parametrize(
    ("facts", "label"),
    [
        (Facts(pair="recession"), verdict.DESCRIPTIVE),
        (Facts(pair="fed", sufficient=False), verdict.TOO_EARLY),
        (Facts(pair="cpi", validation_ok=False, **BASE), verdict.TOO_EARLY),
        (Facts(pair="btc", placebo_pass=False, **BASE), verdict.TOO_EARLY),
        (Facts(pair="btc", nocontrol_p=0.01, **BASE), verdict.NO_EXTRA),
        (Facts(pair="fed", **BASE), verdict.NO_HEAD_START),
        (Facts(pair="fed", **{**BASE, "upper_r": 0.06}), verdict.TOO_EARLY),
        (Facts(pair="fed", bh_reject=True, lead_p=0.01, **BASE), verdict.FIRST),
        (Facts(pair="fed", bh_reject=True, lead_p=0.2, **BASE), verdict.SAME),
        (Facts(pair="btc", bh_reject=True, **BASE), verdict.FIRST),
        (Facts(pair="cpi", bh_reject=True, close_proxy_ok=True, **BASE), verdict.FIRST),
        (Facts(pair="cpi", bh_reject=True, close_proxy_ok=False, **BASE), verdict.SAME),
    ],
)
def test_verdict_rows(facts, label):
    assert verdict.verdict(facts)[0] == label


def test_relative_placebo_gates_only_significant_primaries():
    null = Facts(pair="fed", placebo_pass=False, **BASE)
    assert verdict.verdict(null)[0] == verdict.NO_HEAD_START
    assert verdict.verdict(null, literal_placebo=True)[0] == verdict.TOO_EARLY
    sig = Facts(pair="fed", placebo_pass=False, bh_reject=True, lead_p=0.01, **BASE)
    assert verdict.verdict(sig)[1].startswith("Placebo failed")


def test_confidence_levels():
    medium = Facts(
        pair="fed", bh_reject=True, placebo_pass=True, robust_hold=True, bh_q=0.02, **BASE
    )
    assert verdict.confidence(medium)[0] == "Medium"
    high = Facts(**{**medium.__dict__, "bh_q": 0.005, "lower_r": 0.03})
    assert verdict.confidence(high)[0] == "High"
    cpi_high = Facts(**{**high.__dict__, "pair": "cpi"})
    assert verdict.confidence(cpi_high)[0] == "Medium"  # High is unattainable for CPI
    assert verdict.confidence(Facts(pair="fed", sufficient=False))[0] == "Not enough data"
    assert verdict.confidence(Facts(pair="fed", **BASE))[0] == "Low"

"""Step 6 hand-off rows as tests: planted answers on panel-shaped synthetic data.

Every test uses fixed seeds, so its outcome is deterministic.
"""

from __future__ import annotations

import numpy as np
import pytest

import analysis_synth as synth
from poly_actor.analysis import models, placebo, primary, runners, sample, verdict
from poly_actor.analysis.sample import SessionGrid


def fed_outcome(grid: SessionGrid, others=(0.5, 0.5)):
    core = runners.fed_core(grid)
    reject, adj = models.bh([core.p_one, *others], verdict.BH_Q)
    facts = runners.fed_facts(core, bool(reject[0]), float(adj[0]))
    return verdict.verdict(facts)[0], core, facts


# ---------------------------------------------------------------- row 1: planted lead


def test_planted_two_bar_lead_is_recovered():
    """PM leads TLT by 2 bars, beta = 0.1 SD: peak at +2 outside the band, lead-sum p < 0.01,
    verdict "Polymarket moves first", each in >= 90% of 100 seeds (1,000 sessions)."""
    peak, lead, first = 0, 0, 0
    for seed in range(100):
        grid = synth.to_grid(synth.make(seed, n_sessions=1000, betas={2: 0.1}))
        xc = placebo.xcorr_with_band(grid, grid.returns["TLT"])
        peak += xc.peak_lag == 2 and xc.clear_link
        label, core, _ = fed_outcome(grid)
        lead += core.reg.tests["lead"].p_one < 0.01
        first += label == verdict.FIRST
    assert peak >= 90 and lead >= 90 and first >= 90, (peak, lead, first)


def test_chart1_band_power_at_fed_size_is_limited():
    """Documented limitation: at the real Fed size (500 sessions) the simultaneous band flags
    the same 0.1-SD lead in well under 90% of seeds (far lags have few in-session pairs), while
    the primary regression still finds it in most seeds (measured: 41 and 83 of 100)."""
    peak, first = 0, 0
    for seed in range(100):
        grid = synth.to_grid(synth.make(seed, n_sessions=500, betas={2: 0.1}))
        xc = placebo.xcorr_with_band(grid, grid.returns["TLT"])
        peak += xc.peak_lag == 2 and xc.clear_link
        first += fed_outcome(grid)[0] == verdict.FIRST
    assert 25 <= peak <= 60, peak
    assert first >= 75, first


# ---------------------------------------------------------------- row 2: contemporaneous only


def test_contemporaneous_effect_is_not_called_a_lead():
    hits = 0
    for seed in range(200):
        grid = synth.to_grid(synth.make(1000 + seed, n_sessions=500, betas={0: 0.1}))
        hits += fed_outcome(grid)[0] == verdict.FIRST
    assert hits <= 16, hits  # <= 8% of 200


# ---------------------------------------------------------------- row 3: realistic null


@pytest.fixture(scope="module")
def null_runs():
    """1,000 seeds of the realistic null: sparse heavy-tailed PM changes, GARCH-t returns."""
    rejections, exceed = 0, 0
    for seed in range(1000):
        grid = synth.to_grid(synth.make(5000 + seed, n_sessions=500, realistic=True))
        _, reg = primary.fed_regression(grid)
        rejections += reg.tests["sum"].p_one < 0.05
        exceed += placebo.xcorr_with_band(grid, grid.returns["TLT"]).clear_link
    return rejections / 1000, exceed / 1000


def test_realistic_null_rejection_rate(null_runs):
    assert 0.03 <= null_runs[0] <= 0.08, null_runs


@pytest.mark.xfail(
    strict=True,
    reason="OPEN A27 ISSUE (step6_build.md): the session-shift band is anti-conservative when "
    "odds changes and returns share volatility (measured 15.8% vs target 3-7%; 4.3% with "
    "independent volatility). A27 is frozen, so the method is not changed without a decision.",
)
def test_realistic_null_band_exceedance(null_runs):
    assert 0.03 <= null_runs[1] <= 0.07, null_runs


# ---------------------------------------------------------------- row 4: decision bars (B1)


def _decision_drift_grid(seed: int = 0) -> tuple[SessionGrid, np.ndarray]:
    sy = synth.make(seed, n_sessions=300, hole_rate=0.0, stale_rate=0.0)
    fomc = sy.event_hour[:, 4]
    sy.x[fomc, 4] = 50.0 * np.sign(np.random.default_rng(seed).standard_normal(fomc.sum()))
    sy.x[fomc, 5] = 0.0
    sy.returns["TLT"][fomc, 6] = 0.5 * sy.x[fomc, 4]  # post-announcement drift on the 15:30 bar
    return synth.to_grid(sy), fomc


def _decision_rows_in_design(design_mask) -> int:
    grid, fomc = _decision_drift_grid()
    ok = design_mask(grid, primary.FED_LAGS, grid.returns["TLT"])
    return int(ok[fomc, 6].sum())


def test_rows_lagging_onto_decision_bars_are_excluded():
    assert _decision_rows_in_design(sample.design_mask) == 0
    grid, _ = _decision_drift_grid()
    _, reg = primary.fed_regression(grid)
    assert reg.tests["lead"].p_two > 0.01  # the drift does not leak into b1 + b2


def test_mutation_without_lag_window_check_lets_decision_rows_in():
    def no_lag_check(grid, pm_lags, y):
        return (
            grid.row_ok
            & ~np.isnan(y)
            & np.all([~np.isnan(sample.lag(grid.x, k, np.nan)) for k in pm_lags], axis=0)
        )

    assert _decision_rows_in_design(no_lag_check) > 0


# ---------------------------------------------------------------- row 5: Yahoo hole


def test_lag_on_a_yahoo_hole_is_nan_not_the_previous_bar():
    x = np.arange(14, dtype=float).reshape(2, 7)
    x[0, 2] = np.nan  # hole at position 2
    lagged = sample.lag(x, 1, np.nan)
    assert np.isnan(lagged[0, 3])  # not x[0, 1]
    assert np.isnan(lagged[1, 0])  # first bar of a session: no lag from the previous session
    assert lagged[0, 4] == 3.0


def test_rows_whose_lag_is_a_hole_leave_the_design():
    sy = synth.make(0, n_sessions=20, hole_rate=0.0, stale_rate=0.0, fomc_every=1000)
    sy.returns["TLT"][3, 2] = np.nan
    grid = synth.to_grid(sy)
    ok = sample.design_mask(grid, primary.FED_LAGS, grid.returns["TLT"])
    assert not ok[3, 2] and not ok[3, 3] and not ok[3, 4] and ok[3, 5]
    assert not ok[:, :2].any()  # first two bars of every session have NaN lags


# ---------------------------------------------------------------- row 6: BTC spot control


def _btc_grid(
    seed: int, n_sessions: int = 300, tickers: tuple[str, ...] = ("IBIT",)
) -> tuple[SessionGrid, np.ndarray]:
    rng = np.random.default_rng(seed)
    sy = synth.make(
        seed,
        n_sessions=n_sessions,
        tickers=tickers,
        pair_id="bitcoin_monthly_ladder",
        hole_rate=0.0,
        fomc_every=1000,
    )
    S, P = sy.exists.shape
    spot = rng.standard_normal((S, P + 4))  # 4 pre-open clock hours, then the session hours
    in_session = spot[:, 4:]
    sy.x = np.where(sy.exists, in_session + rng.standard_normal((S, P)), np.nan)
    prev = spot[:, 3 : 3 + P]
    sy.returns["IBIT"] = np.where(
        sy.exists, in_session + 0.4 * prev + rng.standard_normal((S, P)), np.nan
    )
    controls = np.stack([spot[:, 4 - k : 4 - k + P] for k in range(4)], axis=2)
    return synth.to_grid(sy), controls


def test_btc_odds_that_only_echo_spot_give_no_extra_information():
    no_ctrl, with_ctrl, label_hits = 0, 0, 0
    for seed in range(100):
        grid, controls = _btc_grid(seed)
        core = runners.btc_core(grid, controls)
        no_ctrl += core.reg_nocontrol.tests["lag1"].p_one < 0.01
        with_ctrl += core.reg.tests["lag1"].p_one > 0.10
        reject, adj = models.bh([core.p_one, 0.5, 0.5], verdict.BH_Q)
        facts = runners.btc_facts(core, bool(reject[0]), float(adj[0]))
        label_hits += verdict.verdict(facts)[0] == verdict.NO_EXTRA
    assert no_ctrl >= 90 and label_hits >= 90, (no_ctrl, label_hits)
    assert with_ctrl >= 90, with_ctrl


def test_btc_xlu_placebo_false_failure_rate_is_about_ten_percent():
    """XLU passes if two-sided p > 0.10, so an unrelated XLU fails ~10% of the time by design;
    this caps how often any substantive BTC verdict can be reached under the null."""
    passes = 0
    for seed in range(100):
        grid, controls = _btc_grid(seed, tickers=("IBIT", "XLU"))
        passes += runners.btc_core(grid, controls).xlu.tests["lag1"].p_two > 0.10
    assert 80 <= passes <= 97, passes


# ---------------------------------------------------------------- rows 7-8: BH


def test_bh_step_up_rejects_all_three():
    reject, _ = models.bh([0.02, 0.06, 0.09], 0.10)
    assert reject.tolist() == [True, True, True]  # Holm/Bonferroni would reject none or one


def test_bh_rejects_only_the_first():
    reject, adj = models.bh([0.01, 0.08, 0.5], 0.10)
    assert reject.tolist() == [True, False, False]  # uncorrected 0.10 would also take 0.08
    assert adj[0] == pytest.approx(0.03)


# ---------------------------------------------------------------- row 12: opposite sign


def test_significant_opposite_sign_marks_the_primary_row():
    grid = synth.to_grid(synth.make(7, n_sessions=500, betas={0: -0.15}))
    _, _, facts = fed_outcome(grid)
    assert facts.opposite_sign
    assert verdict.primary_status(facts) == "Failed (opposite sign)"
    assert verdict.verdict(facts)[0] == verdict.NO_HEAD_START

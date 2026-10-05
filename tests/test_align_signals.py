"""Signal formulas as input -> expected-output examples."""

import numpy as np
import pytest

from poly_actor.align import signals


def test_fed_expected_change_is_the_probability_weighted_mean():
    p = np.array([[0.6, 0.4, 0.0]])
    level, other, reason = signals.fed_expected_change(p, np.array([-25.0, 0.0, 25.0]))
    assert level[0] == pytest.approx(-15.0)
    assert reason[0] == "ok" and np.isnan(other[0])


def test_fed_normalises_by_the_sum_of_probabilities():
    level, _, _ = signals.fed_expected_change(np.array([[0.2, 0.1]]), np.array([-25.0, 25.0]))
    assert level[0] == pytest.approx((-25 * 0.2 + 25 * 0.1) / 0.3)
    level, _, _ = signals.fed_expected_change(np.array([[0.3, 0.3]]), np.array([-25.0, 25.0]))
    assert level[0] == pytest.approx(0.0)


def test_fed_zero_mass_hour_is_dropped_not_zero():
    level, _, reason = signals.fed_expected_change(np.zeros((1, 2)), np.array([-25.0, 25.0]))
    assert np.isnan(level[0]) and reason[0] == "zero_mass"


def test_fed_missing_bucket_quote_drops_the_hour():
    level, _, reason = signals.fed_expected_change(
        np.array([[0.5, np.nan]]), np.array([-25.0, 25.0])
    )
    assert np.isnan(level[0]) and reason[0] == "missing_quote"


def test_fed_catch_all_mass_above_a_quarter_drops_the_hour_but_equal_is_kept():
    deltas = np.array([-25.0, 25.0])
    p = np.array([[0.5, 0.5], [0.5, 0.5]])
    level, other, reason = signals.fed_expected_change(p, deltas, np.array([0.25, 0.26]))
    assert reason.tolist() == ["ok", "other_mass_gt_max"]
    assert level[0] == pytest.approx(0.0) and np.isnan(level[1])
    assert other.tolist() == [0.25, 0.26]


def test_cpi_implied_is_weighted_by_bucket_centres():
    p = np.array([[0.0, 0.5, 0.5, 0.0]])
    level, edge, reason = signals.cpi_implied(
        p, np.array([2.4, 2.5, 2.6, 2.7]), np.array([True, False, False, True])
    )
    assert level[0] == pytest.approx(2.55) and edge[0] == 0.0 and reason[0] == "ok"


def test_cpi_edge_mass_above_a_quarter_drops_the_hour():
    p = np.array([[0.25, 0.75], [0.26, 0.74]])
    level, edge, reason = signals.cpi_implied(p, np.array([2.4, 2.5]), np.array([True, False]))
    assert reason.tolist() == ["ok", "edge_mass_gt_max"]
    assert edge.tolist() == pytest.approx([0.25, 0.26])
    assert np.isnan(level[1])


def test_derived_bucket_clip_binds_when_minus_exceeds_plus():
    plus = np.array([[0.30, 0.10], [0.20, 0.10]])
    minus = np.array([[0.20], [0.40]])
    p, binding = signals.derived_bucket(plus, minus)
    assert p.tolist() == pytest.approx([0.2, 0.0])
    assert binding.tolist() == [False, True]


def test_ladder_level_is_the_log_midpoint_of_the_two_strikes():
    log_level, half = signals.log_ladder_level(np.array([100.0]), np.array([25.0]))
    assert np.exp(log_level[0]) == pytest.approx(50.0) and half[0] == pytest.approx(np.log(2))


def test_skew_is_zero_at_the_geometric_midpoint_and_positive_when_spot_is_lower():
    up, dn = np.array([100.0]), np.array([25.0])
    assert signals.skew(up, dn, np.array([50.0]))[0] == pytest.approx(0.0)
    assert signals.skew(up, dn, np.array([40.0]))[0] > 0


def test_ladder_formulas_propagate_nan():
    nan = np.array([np.nan])
    assert np.isnan(signals.log_ladder_level(nan, np.array([25.0]))[0][0])
    assert np.isnan(signals.skew(np.array([100.0]), np.array([25.0]), nan)[0])

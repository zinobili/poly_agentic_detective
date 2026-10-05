"""As-of lookup rules: last observation at or before the instant, never later (look-ahead)."""

import numpy as np
import pandas as pd

from align_synth import obs
from poly_actor.align import consts
from poly_actor.align.prices import PriceBook

HOUR = 3600


def book(frame: pd.DataFrame, max_age_s: int = 3 * HOUR, clip: bool = True) -> PriceBook:
    return PriceBook(frame, max_age_s, clip)


def test_takes_last_observation_at_or_before_instant():
    b = book(obs("a", [100, 200, 300], [0.1, 0.2, 0.3]))
    q = b.asof("a", np.array([199, 200, 250]))
    assert q.p.tolist() == [0.1, 0.2, 0.2]


def test_never_uses_a_later_observation():
    b = book(obs("a", [1000], [0.9]))
    q = b.asof("a", np.array([999]))
    assert np.isnan(q.p[0])


def test_observation_stamped_just_after_the_hour_is_not_used_at_the_hour():
    # fid=60 points are stamped a few seconds after the hour: at the hour itself the previous
    # point (about 1h old) is the latest legal one.
    b = book(obs("a", [0 + 5, HOUR + 5], [0.2, 0.7]))
    q = b.asof("a", np.array([HOUR]))
    assert q.p[0] == 0.2
    assert q.age_s[0] == HOUR - 5


def test_stale_observation_beyond_cap_is_missing_not_forward_filled():
    b = book(obs("a", [0], [0.5]), max_age_s=3 * HOUR)
    q = b.asof("a", np.array([3 * HOUR, 3 * HOUR + 1]))
    assert q.p[0] == 0.5
    assert np.isnan(q.p[1]) and np.isnan(q.age_s[1])


def test_prices_above_one_are_clipped_and_flagged():
    b = book(obs("a", [0, 10], [1.0055, 0.4]))
    q = b.asof("a", np.array([5, 15]))
    assert q.p.tolist() == [1.0, 0.4]
    assert q.clipped.tolist() == [True, False]


def test_unclipped_book_keeps_raw_values():
    b = book(obs("spot", [0], [95000.0]), clip=False)
    assert b.asof("spot", np.array([1])).p[0] == 95000.0


def test_finest_fidelity_wins_on_the_same_timestamp():
    frame = pd.concat([obs("a", [100], [0.3], fidelity=60), obs("a", [100], [0.4], fidelity=1)])
    assert book(frame).asof("a", np.array([100])).p[0] == 0.4


def test_unknown_key_and_empty_frame_give_no_data():
    b = book(obs("a", [], []))
    assert np.isnan(b.asof("a", np.array([5])).p[0])
    assert np.isnan(b.asof("zzz", np.array([5])).p[0])


TOL = consts.PM_STAMP_TOLERANCE_S


def tolerant(frame: pd.DataFrame) -> PriceBook:
    return PriceBook(frame, 3 * HOUR, tolerance_s=TOL)


def test_observation_at_hour_plus_tolerance_minus_one_is_used_and_flagged():
    b = tolerant(obs("a", [HOUR + TOL - 1, 5], [0.7, 0.2]))
    q = b.asof("a", np.array([HOUR]))
    assert q.p[0] == 0.7
    assert q.age_s[0] == -(TOL - 1) and q.used_tolerance[0]


def test_observation_at_hour_plus_tolerance_plus_one_is_not_used():
    b = tolerant(obs("a", [HOUR + TOL + 1, 5], [0.7, 0.2]))
    q = b.asof("a", np.array([HOUR]))
    assert q.p[0] == 0.2 and not q.used_tolerance[0]
    assert q.age_s[0] == HOUR - 5


def test_observation_exactly_at_hour_plus_tolerance_is_used():
    q = tolerant(obs("a", [HOUR + TOL], [0.7])).asof("a", np.array([HOUR]))
    assert q.p[0] == 0.7 and q.age_s[0] == -TOL


def test_strict_book_never_flags_tolerance_use():
    q = book(obs("a", [HOUR + 1], [0.7])).asof("a", np.array([HOUR]))
    assert np.isnan(q.p[0]) and not q.used_tolerance[0]


def test_observation_at_or_before_the_instant_is_not_flagged_even_with_tolerance():
    q = tolerant(obs("a", [HOUR - 10], [0.4])).asof("a", np.array([HOUR]))
    assert q.p[0] == 0.4 and q.age_s[0] == 10 and not q.used_tolerance[0]

"""A22/A25 as-of rules as input -> output examples, plus guards of the pipeline wiring.

Rules: the freshest observation across fidelities wins; only a fid-60 point stamped up to 53 s
after a WHOLE-HOUR instant may be used "from the future"; strict mode never uses any later point.
"""

import numpy as np
import pandas as pd

from align_synth import ep, obs
from poly_actor.align import consts, pipeline
from poly_actor.align.prices import PriceBook

HOUR = 3600
H14 = ep("2025-01-14T14:00:00Z")
H1430 = H14 + 1800


def book(frames: list[pd.DataFrame], tolerance_s: int = consts.PM_STAMP_TOLERANCE_S) -> PriceBook:
    return PriceBook(pd.concat(frames), 3 * HOUR, tolerance_s=tolerance_s)


def test_the_production_tolerance_is_53_seconds():
    assert consts.PM_STAMP_TOLERANCE_S == 53 and consts.TOLERANCE_FIDELITY == 60


def test_fid60_point_40s_after_the_hour_is_used_and_flagged():
    q = book([obs("a", [H14 - HOUR + 5, H14 + 40], [0.2, 0.7])]).asof("a", np.array([H14]))
    assert q.p[0] == 0.7 and q.age_s[0] == -40 and q.used_tolerance[0]


def test_fid60_point_54s_after_the_hour_is_not_used():
    q = book([obs("a", [H14 - HOUR + 5, H14 + 54], [0.2, 0.7])]).asof("a", np.array([H14]))
    assert q.p[0] == 0.2 and not q.used_tolerance[0]


def test_fid10_and_fid1_points_5s_after_the_instant_are_not_used():
    for fid in (10, 1):
        frames = [obs("a", [H1430 - 600], [0.2], fid), obs("a", [H1430 + 5], [0.9], fid)]
        q = book(frames).asof("a", np.array([H1430]))
        assert q.p[0] == 0.2 and q.age_s[0] == 600 and not q.used_tolerance[0]


def test_fid1_point_2s_after_a_whole_hour_is_not_used():
    # the tolerance is for fid-60 only, also at the top of the hour
    frames = [obs("a", [H14 - 58], [0.2], 1), obs("a", [H14 + 2], [0.9], 1)]
    q = book(frames).asof("a", np.array([H14]))
    assert q.p[0] == 0.2 and q.age_s[0] == 58


def test_fid60_point_20s_after_half_hour_is_not_used():
    frames = [obs("a", [H14 + 5], [0.2], 60), obs("a", [H1430 + 20], [0.9], 60)]
    q = book(frames).asof("a", np.array([H1430]))
    assert q.p[0] == 0.2 and q.age_s[0] == 1800 - 5 and not q.used_tolerance[0]


def test_freshest_observation_across_fidelities_wins():
    frames = [obs("a", [H14 + 5], [0.2], 60), obs("a", [H1430 - 240], [0.5], 10)]
    q = book(frames).asof("a", np.array([H1430]))
    assert q.p[0] == 0.5 and q.age_s[0] == 240


def test_tolerant_fid60_beats_an_older_fid10_point_at_the_hour():
    frames = [obs("a", [H14 - 300], [0.3], 10), obs("a", [H14 + 30], [0.8], 60)]
    q = book(frames).asof("a", np.array([H14]))
    assert q.p[0] == 0.8 and q.used_tolerance[0]


def test_strict_mode_never_uses_a_later_point_at_any_fidelity():
    for fid in (60, 10, 1):
        q = book([obs("a", [H14 + 2], [0.9], fid)], tolerance_s=0).asof("a", np.array([H14]))
        assert np.isnan(q.p[0]) and not q.used_tolerance[0]


def test_a_minus_one_second_age_counts_as_tolerance_use():
    q = book([obs("a", [H14 + 1], [0.9])]).asof("a", np.array([H14]))
    assert q.age_s[0] == -1 and q.used_tolerance[0]


def test_spot_book_ignores_a_close_stamped_after_the_instant_even_if_given_a_tolerance():
    # spot series carry no fid-60 rows: a tolerance can never make them look ahead
    spot = pd.DataFrame({"key": "BTC-USD", "t": [H14 - HOUR, H14 + 30], "p": [100.0, 999.0]})
    q = PriceBook(spot, 3 * HOUR, clip=False, tolerance_s=consts.PM_STAMP_TOLERANCE_S).asof(
        "BTC-USD", np.array([H14])
    )
    assert q.p[0] == 100.0 and not q.used_tolerance[0]


def test_spot_bar_starting_at_10_is_stamped_at_its_end_11_not_before():
    bars = pd.DataFrame(
        {
            "ticker": "BTC-USD",
            "ts": pd.to_datetime([ep("2025-01-14T10:00:00Z")], unit="s", utc=True),
            "close": [101.0],
            "ohlc_all_nan": [False],
        }
    )
    o = pipeline.spot_obs(bars, "BTC-USD")
    assert o["t"].tolist() == [ep("2025-01-14T11:00:00Z")]
    b = PriceBook(o, 3 * HOUR, clip=False)
    got = b.asof("BTC-USD", np.array([ep("2025-01-14T10:59:59Z"), ep("2025-01-14T11:00:00Z")]))
    assert np.isnan(got.p[0]) and got.p[1] == 101.0

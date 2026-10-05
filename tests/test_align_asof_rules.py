"""As-of rules (A25, A22 retired by A26) as input -> output examples, plus pipeline wiring guards.

Rules: the freshest observation across fidelities wins, and an observation stamped after the
instant is never used, at any fidelity, at any instant (whole hour or :30).
"""

import numpy as np
import pandas as pd
import pytest

from align_synth import ep, obs
from poly_actor.align import cli, pipeline
from poly_actor.align.prices import PriceBook

HOUR = 3600
H14 = ep("2025-01-14T14:00:00Z")
H1430 = H14 + 1800


def book(frames: list[pd.DataFrame]) -> PriceBook:
    return PriceBook(pd.concat(frames), 3 * HOUR)


def test_fid60_point_40s_after_the_hour_is_not_used():
    # 14:00:40Z point, query 14:00:00Z: take the latest point <= 14:00:00Z
    q = book([obs("a", [H14 - HOUR + 5, H14 + 40], [0.2, 0.7])]).asof("a", np.array([H14]))
    assert q.p[0] == 0.2 and q.age_s[0] == HOUR - 5


def test_fid10_point_at_1420_for_a_1430_query_is_used_with_age_600():
    q = book([obs("a", [H1430 - 600], [0.2], 10)]).asof("a", np.array([H1430]))
    assert q.p[0] == 0.2 and q.age_s[0] == 600


def test_a_point_stamped_after_the_instant_is_never_used_at_any_fidelity():
    for fid in (60, 10, 1):
        for instant in (H14, H1430):
            frames = [obs("a", [instant - 600], [0.2], fid), obs("a", [instant + 2], [0.9], fid)]
            q = book(frames).asof("a", np.array([instant]))
            assert q.p[0] == 0.2 and q.age_s[0] == 600
            lone = book([obs("a", [instant + 1], [0.9], fid)]).asof("a", np.array([instant]))
            assert np.isnan(lone.p[0])


def test_ages_are_never_negative():
    frames = [obs("a", [H14 + 1, H14 - 7], [0.9, 0.1])]
    assert book(frames).asof("a", np.array([H14])).age_s[0] == 7


def test_freshest_observation_across_fidelities_wins():
    frames = [obs("a", [H14 + 5], [0.2], 60), obs("a", [H1430 - 240], [0.5], 10)]
    q = book(frames).asof("a", np.array([H1430]))
    assert q.p[0] == 0.5 and q.age_s[0] == 240


def test_align_run_no_longer_accepts_strict_asof():
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--strict-asof"])
    assert exc.value.code == 2


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

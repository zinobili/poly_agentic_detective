"""Per-pair evaluators on synthetic quotes: Fed, CPI (derived bucket clip) and the BTC ladder."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from align_synth import ep
from poly_actor.align.evaluate import evaluate_btc, evaluate_cpi, evaluate_fed
from poly_actor.align.events import BtcSpec, CpiBucket, Event, FedBucket
from poly_actor.align.prices import PriceBook
from poly_actor.pairs import BtcRung

HOUR = 3600
T0 = ep("2025-06-10T12:00:00Z")
CREATED = datetime(2025, 6, 1, tzinfo=UTC)  # long before T0, so the 24h rung age is met


def flat_book(prices: dict[str, float], at: int = T0 - 60, clip: bool = True) -> PriceBook:
    frame = pd.DataFrame({"key": list(prices), "t": at, "p": list(prices.values()), "fidelity": 60})
    return PriceBook(frame, 3 * HOUR, clip=clip)


def event(**kwargs) -> Event:
    base = {
        "id": "E",
        "use_from_s": T0 - 100 * HOUR,
        "use_until_s": T0 + 100 * HOUR,
        "first_usable_s": T0 - 50 * HOUR,
        "event_time_s": None,
    }
    return Event(**{**base, **kwargs})


def instants(*offsets_s: int) -> np.ndarray:
    return np.array([T0 + o for o in offsets_s], dtype="int64")


def test_fed_evaluator_gives_weighted_bp_and_flags_clipped_price():
    ev = event(
        fed_buckets=(FedBucket("cut", -25.0), FedBucket("hold", 0.0)),
        fed_other_tokens=("other",),
    )
    out = evaluate_fed(
        ev, flat_book({"cut": 1.0055, "hold": 0.4, "other": 0.01}), None, instants(0)
    )
    assert out["level"][0] == pytest.approx(-25.0 * 1.0 / 1.4)
    assert out["clipped"][0] and out["reason"][0] == "ok" and out["other_mass"][0] == 0.01


def test_fed_evaluator_is_before_first_usable_for_early_instants():
    ev = event(fed_buckets=(FedBucket("hold", 0.0),), first_usable_s=T0 + HOUR)
    out = evaluate_fed(ev, flat_book({"hold": 0.5}), None, instants(0))
    assert np.isnan(out["level"][0]) and out["reason"][0] == "before_first_usable"


def test_cpi_derived_bucket_uses_plus_minus_and_reports_when_the_clip_binds():
    buckets = (
        CpiBucket("lo", "low_edge", 2.0, token="lo"),
        CpiBucket("mid", "point", 2.5, token="mid"),
        CpiBucket("rng", "range", 2.75, plus_tokens=("p1",), minus_tokens=("m1",)),
    )
    ev = event(cpi_buckets=buckets)
    ok = evaluate_cpi(
        ev, flat_book({"lo": 0.0, "mid": 0.5, "p1": 0.6, "m1": 0.1}), None, instants(0)
    )
    assert ok["level"][0] == pytest.approx((0.5 * 2.5 + 0.5 * 2.75) / 1.0)
    assert not ok["cpi_clip_binding"][0] and ok["cpi_has_derived"][0]
    bound = evaluate_cpi(
        ev, flat_book({"lo": 0.0, "mid": 0.5, "p1": 0.1, "m1": 0.3}), None, instants(0)
    )
    assert bound["cpi_clip_binding"][0]
    assert bound["level"][0] == pytest.approx(2.5)  # derived bucket clipped to 0


def test_cpi_missing_component_quote_drops_the_hour():
    buckets = (
        CpiBucket("mid", "point", 2.5, token="mid"),
        CpiBucket("rng", "range", 2.75, plus_tokens=("p1",), minus_tokens=("m1",)),
    )
    out = evaluate_cpi(
        event(cpi_buckets=buckets), flat_book({"mid": 0.5, "p1": 0.4}), None, instants(0)
    )
    assert np.isnan(out["level"][0]) and out["reason"][0] == "missing_quote"
    assert not out["cpi_clip_binding"][0]


def rung(slug: str, ladder: str, strike: float, **kwargs) -> BtcRung:
    return BtcRung(slug=slug, ladder=ladder, strike=strike, created=CREATED, **kwargs)


def btc_event(rungs: list[BtcRung]) -> Event:
    spec = BtcSpec(tuple(rungs), {r.slug: f"tok_{r.slug}" for r in rungs})
    return event(btc=spec)


def quotes_for(rungs: list[BtcRung], probs: dict[str, float]) -> PriceBook:
    return flat_book({f"tok_{s}": p for s, p in probs.items()})


def ladder_rungs() -> list[BtcRung]:
    return [
        rung("u100", "up", 100.0),
        rung("u110", "up", 110.0),
        rung("u120", "up", 120.0),
        rung("d90", "dip", 90.0),
        rung("d80", "dip", 80.0),
        rung("d70", "dip", 70.0),
    ]


def test_btc_level_is_the_log_midpoint_of_the_two_half_probability_strikes():
    rungs = ladder_rungs()
    probs = {"u100": 0.8, "u110": 0.4, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    spot = flat_book({"BTC-USD": 95.0}, clip=False)
    out = evaluate_btc(btc_event(rungs), quotes_for(rungs, probs), spot, instants(0))
    k_up = np.exp(np.log(100) + 0.75 * (np.log(110) - np.log(100)))
    k_dn = np.exp(np.log(90) + 0.5 * (np.log(80) - np.log(90)))
    assert out["k_up"][0] == pytest.approx(k_up) and out["k_dn"][0] == pytest.approx(k_dn)
    assert out["level"][0] == pytest.approx((np.log(k_up) + np.log(k_dn)) / 2)
    assert out["skew"][0] == pytest.approx(np.log(k_up) + np.log(k_dn) - 2 * np.log(95.0))
    assert out["reason"][0] == "ok" and not out["pav_pooled"][0]


def test_btc_hour_is_dropped_when_half_is_not_bracketed():
    rungs = ladder_rungs()
    probs = {"u100": 0.4, "u110": 0.3, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    out = evaluate_btc(btc_event(rungs), quotes_for(rungs, probs), flat_book({}), instants(0))
    assert np.isnan(out["level"][0]) and out["reason"][0] == "not_bracketed"


def test_btc_rung_younger_than_24_hours_is_not_used():
    rungs = ladder_rungs()
    young = BtcRung("u100", "up", 100.0, created=datetime.fromtimestamp(T0 - 23 * HOUR, UTC))
    rungs[0] = young
    probs = {"u100": 0.9, "u110": 0.4, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    out = evaluate_btc(btc_event(rungs), quotes_for(rungs, probs), flat_book({}), instants(0))
    # without the 100 rung the up ladder starts at 110 (P 0.4): 0.5 is not bracketed
    assert out["reason"][0] == "not_bracketed" and out["n_up"][0] == 2


def test_btc_touched_strike_counts_as_one_even_with_a_stale_low_quote():
    rungs = ladder_rungs()
    closed = datetime.fromtimestamp(T0 - 5 * HOUR, UTC)
    rungs[0] = rung("u100", "up", 100.0, closed_time=closed, resolved_yes=True)
    probs = {"u100": 0.01, "u110": 0.4, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    out = evaluate_btc(btc_event(rungs), quotes_for(rungs, probs), flat_book({}), instants(0))
    w = (1.0 - 0.5) / (1.0 - 0.4)
    assert out["k_up"][0] == pytest.approx(np.exp(np.log(100) + w * (np.log(110) - np.log(100))))


def test_btc_flags_hours_where_isotonic_pooling_changed_the_ladder():
    rungs = ladder_rungs()
    probs = {"u100": 0.5, "u110": 0.6, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    out = evaluate_btc(btc_event(rungs), quotes_for(rungs, probs), flat_book({}), instants(0))
    assert out["pav_pooled"][0]


def test_btc_hours_before_first_usable_have_no_signal():
    rungs = ladder_rungs()
    ev = btc_event(rungs)
    ev = Event(**{**ev.__dict__, "first_usable_s": T0 + HOUR})
    out = evaluate_btc(ev, quotes_for(rungs, {}), flat_book({}), instants(0, 2 * HOUR))
    assert out["reason"][0] == "before_first_usable"
    assert out["reason"][1] != "before_first_usable"


def test_btc_quote_published_after_the_instant_is_ignored():
    rungs = ladder_rungs()
    probs = {"u100": 0.8, "u110": 0.4, "u120": 0.1, "d90": 0.7, "d80": 0.3, "d70": 0.1}
    frame = pd.DataFrame(
        {
            "key": [f"tok_{s}" for s in probs],
            "t": T0 + 10,  # stamped AFTER the instant
            "p": list(probs.values()),
            "fidelity": 60,
        }
    )
    out = evaluate_btc(btc_event(rungs), PriceBook(frame, 3 * HOUR), flat_book({}), instants(0))
    assert np.isnan(out["level"][0]) and out["reason"][0] == "no_rungs"


def test_cpi_primary_edge_threshold_is_a_quarter_with_strict_flag_at_ten_percent():
    buckets = (
        CpiBucket("lo", "low_edge", 2.0, token="lo"),
        CpiBucket("mid", "point", 2.5, token="mid"),
    )
    ev = event(cpi_buckets=buckets)
    # edge mass 0.2 (kept at 0.25, fails the strict 0.10), 0.3 (dropped)
    out = evaluate_cpi(ev, flat_book({"lo": 0.2, "mid": 0.8}), None, instants(0))
    assert out["reason"][0] == "ok" and not out["edge_mass_strict_ok"][0]
    out = evaluate_cpi(ev, flat_book({"lo": 0.3, "mid": 0.7}), None, instants(0))
    assert out["reason"][0] == "edge_mass_gt_max"
    out = evaluate_cpi(ev, flat_book({"lo": 0.05, "mid": 0.95}), None, instants(0))
    assert out["edge_mass_strict_ok"][0]

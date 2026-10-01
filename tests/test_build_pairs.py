"""Offline unit tests for the pure pair helpers (poly_actor.pairs) and the
hardcoded event-time tables in scripts/build_pairs.py. No network."""

from __future__ import annotations

import importlib.util
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from poly_actor.pairs import (
    BtcRung,
    detect_partial_window,
    direction_from_description,
    et_to_utc,
    flag_created_after_touch,
    is_touched,
    isotonic_fit,
    ladder_crossing,
    monotone_ladder_crossing,
    monotone_ladder_crossing_diag,
    parse_cpi_bucket,
    parse_from_date,
    parse_strike,
    rung_direction,
    select_ladder,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_pairs.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("build_pairs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- et_to_utc ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("ymd", "hm", "expected"),
    [
        (
            (2026, 11, 1),
            (0, 0),
            "2026-11-01T04:00:00Z",
        ),  # midnight before the fall-back (still EDT)
        ((2026, 11, 1), (8, 30), "2026-11-01T13:30:00Z"),  # after fall-back: EST
        ((2027, 3, 14), (3, 0), "2027-03-14T07:00:00Z"),  # 03:00 EDT right after the spring-forward
        ((2027, 3, 14), (0, 0), "2027-03-14T05:00:00Z"),  # before the switch: EST
        ((2026, 3, 8), (8, 30), "2026-03-08T12:30:00Z"),  # US switch day 2026
        ((2025, 10, 24), (8, 30), "2025-10-24T12:30:00Z"),  # shutdown-delayed CPI
        ((2026, 2, 13), (8, 30), "2026-02-13T13:30:00Z"),
        ((2026, 10, 28), (14, 0), "2026-10-28T18:00:00Z"),
        ((2026, 12, 9), (14, 0), "2026-12-09T19:00:00Z"),
    ],
)
def test_et_to_utc(ymd, hm, expected):
    assert et_to_utc(ymd, hm) == expected


# ---- parse_cpi_bucket ---------------------------------------------------------
@pytest.mark.parametrize(
    "q",
    [
        "Will US annual inflation be 2.6% or less in December?",
        "Will annual inflation increase by 2.5% or lower in November?",
        "Will annual inflation be 2.6% or below in May?",
    ],
)
def test_cpi_low_edge_variants(q):
    label, kind, bound, centre = parse_cpi_bucket(q)
    assert kind == "low_edge"
    assert label == f"<={bound}"
    assert centre == pytest.approx(bound - 0.1)


@pytest.mark.parametrize(
    "q",
    [
        "Will US annual inflation be 2.9% or greater in December?",
        "Will annual inflation be 4.0% or more in August?",
        "Will annual inflation be 3.0% or higher in May?",
        "Will annual inflation be 3.0% or above in May?",
    ],
)
def test_cpi_high_edge_variants(q):
    label, kind, bound, centre = parse_cpi_bucket(q)
    assert kind == "high_edge"
    assert label == f">={bound}"
    assert centre == pytest.approx(bound + 0.1)


def test_cpi_dec_2024_or_greater_centre():
    assert parse_cpi_bucket("Will US annual inflation be 2.9% or greater in December?") == (
        ">=2.9",
        "high_edge",
        2.9,
        3.0,
    )


def test_cpi_symbol_and_point_buckets():
    assert parse_cpi_bucket("Will annual inflation increase by ≤2.8% in October?")[1] == "low_edge"
    assert parse_cpi_bucket("Will annual inflation increase by ≥3.2% in October?")[1] == "high_edge"
    assert parse_cpi_bucket("Will annual inflation be 3.0% in July?") == ("3.0", "point", 3.0, 3.0)


def test_cpi_unparseable_raises():
    with pytest.raises(ValueError, match="cannot parse"):
        parse_cpi_bucket("Will something happen?")


# ---- parse_strike / ladder_crossing -----------------------------------------------
def test_parse_strike():
    assert parse_strike("Will Bitcoin reach $90,000 in October?") == 90000.0
    assert parse_strike("Will Bitcoin dip to $80k in October?") == 80000.0
    assert parse_strike("no number") is None


def test_ladder_crossing_interpolates_in_log_strike():
    rungs = [(80000.0, 0.8), (100000.0, 0.2)]
    k = ladder_crossing(rungs)
    w = (0.8 - 0.5) / (0.8 - 0.2)
    assert k == pytest.approx(math.exp(math.log(80000) + w * (math.log(100000) - math.log(80000))))
    assert 80000 < k < 100000


def test_ladder_crossing_exact_rung_and_flat():
    assert ladder_crossing([(90000.0, 0.6), (100000.0, 0.5), (110000.0, 0.1)]) == pytest.approx(
        100000.0
    )
    assert ladder_crossing([(90000.0, 0.5), (100000.0, 0.5)]) == pytest.approx(
        math.sqrt(90000 * 100000)
    )


def test_ladder_crossing_no_extrapolation():
    assert ladder_crossing([(90000.0, 0.3), (100000.0, 0.1)]) is None  # all below 0.5
    assert ladder_crossing([(90000.0, 0.9), (100000.0, 0.7)]) is None  # all above 0.5
    assert ladder_crossing([(90000.0, 0.9)]) is None
    assert ladder_crossing([]) is None


def test_ladder_touched_rung_as_one_keeps_bracket():
    # a touched rung (P=1 after closedTime) still brackets 0.5 with the next rung
    k = ladder_crossing([(80000.0, 1.0), (90000.0, 0.3)])
    assert k is not None
    assert 80000 < k < 90000


# ---- A15: isotonic ladder + relisted rungs -----------------------------------------
def test_isotonic_fit_pools_violators():
    assert isotonic_fit([0.9, 0.3, 0.5, 0.1], increasing=False) == pytest.approx(
        [0.9, 0.4, 0.4, 0.1]
    )
    assert isotonic_fit([0.1, 0.5, 0.3, 0.9], increasing=True) == pytest.approx(
        [0.1, 0.4, 0.4, 0.9]
    )
    assert isotonic_fit([], increasing=True) == []


def test_monotone_crossing_non_monotone_up_ladder():
    # 90k is 0.2 but 95k is 0.6: violates monotonicity; pooled to 0.4 each
    rungs = [(100000.0, 0.1), (90000.0, 0.2), (95000.0, 0.6), (80000.0, 0.9)]
    k = monotone_ladder_crossing(rungs, "up")
    # fit by strike: 80k 0.9, 90k 0.4, 95k 0.4, 100k 0.1 -> first crossing in (80k, 90k)
    w = (0.9 - 0.5) / (0.9 - 0.4)
    assert k == pytest.approx(math.exp(math.log(80000) + w * (math.log(90000) - math.log(80000))))


def test_monotone_crossing_dip_ladder_non_decreasing_in_strike():
    # dip: P grows with strike. 70k noisy-high (0.5) above 75k (0.3)
    rungs = [(60000.0, 0.1), (70000.0, 0.5), (75000.0, 0.3), (80000.0, 0.8)]
    k = monotone_ladder_crossing(rungs, "dip")
    # fit by strike: 0.1, 0.4, 0.4, 0.8 -> walking down from 80k: crossing in (75k, 80k)
    w = (0.8 - 0.5) / (0.8 - 0.4)
    assert k == pytest.approx(math.exp(math.log(80000) + w * (math.log(75000) - math.log(80000))))
    assert 75000 < k < 80000


def test_monotone_crossing_ties_and_no_crossing():
    # duplicate strike averaged (0.8 and 0.4 -> 0.6)
    k = monotone_ladder_crossing([(90000.0, 0.8), (90000.0, 0.4), (100000.0, 0.2)], "up")
    assert k is not None
    assert 90000 < k < 100000
    assert monotone_ladder_crossing([(90000.0, 0.3), (100000.0, 0.1)], "up") is None
    assert monotone_ladder_crossing([(90000.0, 0.9), (100000.0, 0.7)], "up") is None
    assert monotone_ladder_crossing([(90000.0, 0.9), (100000.0, 0.3)], "dip") is None
    assert monotone_ladder_crossing([], "up") is None
    with pytest.raises(ValueError, match="ladder"):
        monotone_ladder_crossing([(1.0, 0.5)], "sideways")


def test_monotone_matches_plain_on_monotone_input():
    up = [(80000.0, 0.8), (100000.0, 0.2)]
    assert monotone_ladder_crossing(up, "up") == pytest.approx(ladder_crossing(up))
    dip = [(60000.0, 0.2), (80000.0, 0.8)]
    assert monotone_ladder_crossing(dip, "dip") == pytest.approx(ladder_crossing(dip[::-1]))


def test_parse_from_date():
    s = "will-bitcoin-reach-65k-in-august-2026-from-august-6"
    assert parse_from_date(s, 2026) == (2026, 8, 6)
    assert parse_from_date("will-bitcoin-dip-to-62pt5k-in-august-2026-from-august-2", 2026) == (
        2026,
        8,
        2,
    )
    assert parse_from_date("will-bitcoin-reach-100k-in-august-2026", 2026) is None
    assert parse_from_date("will-bitcoin-reach-65k-in-june-2026-from-june-8-887", 2026) == (
        2026,
        6,
        8,
    )


def test_ceil_hour(script):
    assert script._ceil_hour("2026-01-14T22:42:10Z") == "2026-01-14T23:00:00Z"
    assert script._ceil_hour("2026-03-11T17:33:00Z") == "2026-03-11T18:00:00Z"
    assert script._ceil_hour("2026-03-11T18:00:00Z") == "2026-03-11T18:00:00Z"


def test_built_yaml_invariants():
    import yaml

    d = yaml.safe_load((SCRIPT.parent.parent / "config" / "pairs.yaml").read_text(encoding="utf-8"))
    pairs = {p["id"]: p for p in d["pairs"]}
    btc = pairs["bitcoin_monthly_ladder"]
    for m in btc["markets"]:
        for r in m["up_ladder"] + m["dip_ladder"]:
            assert not r["relisted"] and r["from_date_utc"] is None
            assert not r["partial_window"] and not r["inactive_excluded"]
            assert r["partial_window_detected_by"] == []
        assert all(r["partial_window"] for r in m["partial_window_rungs"])
        assert all(r["partial_window_detected_by"] for r in m["partial_window_rungs"])
        assert all(r["inactive_excluded"] for r in m["inactive_excluded"])
    s = btc["coverage"]["partial_window_summary"]
    assert s["n_inactive_excluded"] == 4
    assert s["n_months_affected"] == 8
    assert s["per_month"]["2026-02"]["by_description_between"] == 3
    assert s["per_month"]["2026-08"]["by_slug"] == 17
    assert btc["coverage"]["signal_first_active_utc"] == "2024-11-02T15:04:59Z"
    cpi = {m["month"]: m for m in pairs["us_cpi_inflation"]["markets"]}
    assert cpi["2026-01"]["first_usable_utc"] == "2026-01-14T23:00:00Z"
    assert cpi["2026-03"]["first_usable_utc"] == "2026-03-11T18:00:00Z"
    derived = [b for b in cpi["2026-01"]["buckets"] if b.get("derived")][0]
    assert (derived["kind"], derived["width"], derived["center"]) == ("range", 0.2, 2.75)
    assert derived["validation_tolerance"] == pytest.approx(0.1)


# ---- hardcoded event-time tables -------------------------------------------------
def test_fomc_dates_official(script):
    t = script.fomc_event_times_utc()
    assert t["2026-10"]["decision_utc"] == "2026-10-28T18:00:00Z"
    assert t["2026-12"]["decision_utc"] == "2026-12-09T19:00:00Z"
    assert t["2027-01"]["decision_utc"] == "2027-01-27T19:00:00Z"
    assert t["2025-03"]["decision_utc"] == "2025-03-19T18:00:00Z"  # EDT
    assert t["2025-01"]["roll_utc"] == "2025-01-29T20:00:00Z"  # EST + 1h


def test_cpi_release_times(script):
    t = script.cpi_event_times_utc()
    assert t["2025-09"]["release_utc"] == "2025-10-24T12:30:00Z"
    assert t["2026-01"]["release_utc"] == "2026-02-13T13:30:00Z"
    assert t["2026-06"]["release_utc"] == "2026-07-14T12:30:00Z"
    assert t["2026-08"]["release_utc"] == "2026-09-11T12:30:00Z"
    assert t["2026-09"]["release_utc"] == "2026-10-14T12:30:00Z"
    assert t["2024-11"]["release_utc"] == "2024-12-11T13:30:00Z"
    assert "2025-10" not in t  # no BLS release (shutdown)
    assert "2025-10" in script.CPI_EXCLUDED


def test_cache_miss_raises_without_network(script, monkeypatch):
    monkeypatch.setattr(script, "REFETCH", False)
    monkeypatch.setattr(script, "FETCH_SLUGS", set())

    def boom(*a, **k):
        raise AssertionError("network touched")

    monkeypatch.setattr(script.requests, "get", boom)
    with pytest.raises(script.CacheMiss):
        script.get_event("definitely-not-a-cached-slug-xyz")


# ---- A20: time-t BTC rung selection ----------------------------------------------
def _dt(day: int, hour: int = 0, month: int = 2) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def _rung(slug, ladder, strike, created, closed=None, yes=None, inactive=False, partial=()):
    return BtcRung(slug, ladder, float(strike), created, closed, yes, inactive, tuple(partial))


def _feb_dip_60k():
    """2026-02 dip 60k: whole-month rung touched 02-06T04:11; strike re-created 02-06T16:31."""
    return [
        _rung("dip-60k-whole", "dip", 60000, _dt(1) - timedelta(days=1), _dt(6, 4), True),
        _rung(
            "dip-60000-fresh",
            "dip",
            60000,
            datetime(2026, 2, 6, 16, 31, tzinfo=UTC),
            datetime(2026, 3, 1, 8, 12, tzinfo=UTC),
            False,
            partial=("description_between",),
        ),
    ]


def test_feb_2026_dip_60k_touched_whole_plus_fresh_gives_p1_fresh_ignored():
    rungs = _feb_dip_60k()
    quotes = {"dip-60000-fresh": 0.3, "dip-60k-whole": 0.9}
    # before the touch: whole-month rung used; fresh is not (a whole-month rung exists)
    before = select_ladder(rungs, "dip", _dt(5), quotes)
    assert [(x.strike, x.p, x.source) for x in before] == [(60000.0, 0.9, "whole_month")]
    # after the touch (even with a live quote on the fresh rung): P=1, one point, no averaging
    for t in (_dt(6, 5), _dt(6, 20), _dt(20)):
        pts = select_ladder(rungs, "dip", t, quotes)
        assert [(x.strike, x.p, x.source, x.slug) for x in pts] == [(60000.0, 1.0, "touched", None)]
    assert flag_created_after_touch(rungs) == {"dip-60000-fresh"}


def test_touched_dip_strike_implies_higher_dip_strikes_touched():
    rungs = [
        _rung("d60", "dip", 60000, _dt(1), _dt(6, 4), True),
        _rung("d65", "dip", 65000, _dt(1)),
        _rung("d55", "dip", 55000, _dt(1)),
    ]
    quotes = {"d65": 0.7, "d55": 0.2}
    pts = {x.strike: x for x in select_ladder(rungs, "dip", _dt(10), quotes)}
    assert pts[60000.0].p == 1.0 and pts[65000.0].p == 1.0  # 65k touched, its quote ignored
    assert pts[55000.0].p == 0.2 and pts[55000.0].source == "whole_month"  # lower: not implied
    assert is_touched(rungs, "dip", 65000.0, _dt(10))
    assert not is_touched(rungs, "dip", 65000.0, _dt(5))
    assert not is_touched(rungs, "dip", 55000.0, _dt(10))
    # a rung that closed No does not touch anything
    no = [_rung("d60", "dip", 60000, _dt(1), _dt(27), False), _rung("d65", "dip", 65000, _dt(1))]
    assert not is_touched(no, "dip", 65000.0, _dt(28))


def test_touched_up_strike_implies_lower_up_strikes_touched():
    rungs = [
        _rung("u100", "up", 100000, _dt(1), _dt(6, 4), True),
        _rung("u95", "up", 95000, _dt(1)),
        _rung("u110", "up", 110000, _dt(1)),
        _rung("d90", "dip", 90000, _dt(1)),  # the other ladder is unaffected
    ]
    quotes = {"u95": 0.8, "u110": 0.3, "d90": 0.4}
    up = {x.strike: x for x in select_ladder(rungs, "up", _dt(10), quotes)}
    assert up[95000.0].source == "touched" and up[100000.0].source == "touched"
    assert up[110000.0].p == 0.3
    dip = select_ladder(rungs, "dip", _dt(10), quotes)
    assert [(x.strike, x.p) for x in dip] == [(90000.0, 0.4)]


def test_inactive_excluded_even_with_a_quote():
    rungs = [
        _rung("u130-dead", "up", 130000, _dt(1), inactive=True),
        _rung("u130", "up", 130000, _dt(1)),
        _rung("u200-dead", "up", 200000, _dt(1), inactive=True),
    ]
    quotes = {"u130-dead": 0.99, "u130": 0.05, "u200-dead": 0.5}
    pts = select_ladder(rungs, "up", _dt(10), quotes)
    assert [(x.strike, x.p, x.slug) for x in pts] == [(130000.0, 0.05, "u130")]
    # an inactive rung never touches anything either
    dead_yes = [_rung("x", "up", 100000, _dt(1), _dt(2), True, inactive=True)]
    dead_yes.append(_rung("y", "up", 90000, _dt(1)))
    assert not is_touched(dead_yes, "up", 90000.0, _dt(10))


def test_fresh_rung_used_at_untouched_strike_without_whole_month_rung():
    fresh = _rung("u80-fresh", "up", 80000, _dt(6, 16), partial=("slug", "description_creation"))
    rungs = [fresh, _rung("u90", "up", 90000, _dt(1))]
    quotes = {"u80-fresh": 0.6, "u90": 0.2}
    # too young at created + 23h, usable at +24h
    assert [x.strike for x in select_ladder(rungs, "up", _dt(7, 15), quotes)] == [90000.0]
    pts = select_ladder(rungs, "up", _dt(7, 16), quotes)
    assert [(x.strike, x.p, x.source) for x in pts] == [
        (80000.0, 0.6, "partial_window"),
        (90000.0, 0.2, "whole_month"),
    ]
    assert pts[0].partial_window and pts[0].partial_reasons == ("slug", "description_creation")
    # where a whole-month rung exists the fresh one is ignored even if the whole-month is unquoted
    both = [fresh, _rung("u80-whole", "up", 80000, _dt(1))]
    assert select_ladder(both, "up", _dt(7, 16), {"u80-fresh": 0.6}) == []


def test_no_quote_skips_rung_and_closed_no_rung_is_dropped():
    rungs = [_rung("u1", "up", 90000, _dt(1)), _rung("u2", "up", 95000, _dt(1), _dt(8), False)]
    q = {"u1": 0.4, "u2": 0.2}
    assert select_ladder(rungs, "up", _dt(5), {}) == []
    assert [x.strike for x in select_ladder(rungs, "up", _dt(5), q)] == [90000.0, 95000.0]
    assert [x.strike for x in select_ladder(rungs, "up", _dt(9), q)] == [90000.0]
    with pytest.raises(ValueError, match="ladder"):
        select_ladder(rungs, "sideways", _dt(5), {})


def test_no_lookahead_in_touch():
    rungs = [
        _rung("u100", "up", 100000, _dt(1), _dt(6, 4), True),
        _rung("u95", "up", 95000, _dt(1)),
    ]
    assert select_ladder(rungs, "up", _dt(6, 3), {"u95": 0.7, "u100": 0.5})[0].p == 0.7
    assert select_ladder(rungs, "up", _dt(6, 4), {"u95": 0.7})[0].source == "touched"


def test_2026_08_style_fresh_dip_rungs_ignored_after_touch():
    # 62.5k dip touched; fresh 65k..80k dip rungs trade below 1 but are ignored (touched => P=1)
    rungs = [_rung("d62", "dip", 62500, _dt(1, month=8), _dt(2, 3, 8), True)]
    for k in (65000, 70000, 80000):
        rungs.append(_rung(f"d{k}", "dip", k, _dt(2, 4, 8), partial=("description_creation",)))
    quotes = {f"d{k}": 0.4 for k in (65000, 70000, 80000)}
    pts = select_ladder(rungs, "dip", _dt(5, month=8), quotes)
    assert [x.p for x in pts] == [1.0, 1.0, 1.0, 1.0]  # 62.5k itself plus 65k..80k all touched
    k, pooled = monotone_ladder_crossing_diag([(x.strike, x.p) for x in pts], "dip")
    assert k is None and pooled is False


def test_pav_pooled_flag():
    assert monotone_ladder_crossing_diag([(90000.0, 0.8), (100000.0, 0.2)], "up")[1] is False
    assert monotone_ladder_crossing_diag([(90000.0, 0.2), (100000.0, 0.6)], "up")[1] is True


def test_plateau_at_half_returns_geometric_midpoint_of_first_two_rungs():
    k = ladder_crossing([(80000.0, 0.5), (90000.0, 0.5), (100000.0, 0.5), (110000.0, 0.1)])
    assert k == pytest.approx(math.sqrt(80000 * 90000))
    # entered from above 0.5: brackets on the earlier pair and returns the plateau's first rung
    assert ladder_crossing([(70000.0, 0.8), (80000.0, 0.5), (90000.0, 0.5)]) == pytest.approx(
        80000.0
    )


def test_detect_partial_window():
    open_feb = datetime(2026, 2, 1, 14, tzinfo=UTC)
    creation = "x (from the creation of this market to April 30, 11:59 PM ET) y"
    assert detect_partial_window("will-bitcoin-reach-1k-in-april", creation, 2026, open_feb) == [
        "description_creation"
    ]
    assert detect_partial_window(
        "will-bitcoin-reach-65k-in-june-2026-from-june-4", creation, 2026, open_feb
    ) == [
        "slug",
        "description_creation",
    ]
    between = "any candle between February 6 11AM ET and February 28 11:59PM ET, has"
    assert detect_partial_window("s", between, 2026, open_feb) == ["description_between"]
    # whole-event windows are not partial: start on the 1st, or on the event's own open day
    assert (
        detect_partial_window("s", "between February 1, 2026, 00:00 and Feb", 2026, open_feb) == []
    )
    jan2 = datetime(2025, 1, 2, 19, 21, tzinfo=UTC)
    assert detect_partial_window("s", "between January 2, 2025, 11:00 and", 2025, jan2) == []
    assert detect_partial_window("s", None, 2025, jan2) == []


def test_built_yaml_feb_2026_dip_60k_and_inactive_excluded():
    import yaml

    d = yaml.safe_load((SCRIPT.parent.parent / "config" / "pairs.yaml").read_text(encoding="utf-8"))
    months = {
        m["month"]: m for m in {p["id"]: p for p in d["pairs"]}["bitcoin_monthly_ladder"]["markets"]
    }
    slug = "will-bitcoin-dip-to-60000-in-february-694"
    fresh = [r for r in months["2026-02"]["partial_window_rungs"] if r["slug"] == slug]
    assert len(fresh) == 1
    assert set(fresh[0]["partial_window_detected_by"]) == {
        "description_between",
        "created_after_touch",
    }
    assert any(r["strike_usd"] == 60000.0 for r in months["2026-02"]["dip_ladder"])
    assert {r["slug"] for r in months["2025-07"]["inactive_excluded"]} == {
        "will-bitcoin-reach-130k-in-july-381-812-547-858-735",
        "will-bitcoin-reach-200k-in-july-174-515",
    }


def test_built_yaml_inactive_2025_11_dip_100k():
    import yaml

    d = yaml.safe_load((SCRIPT.parent.parent / "config" / "pairs.yaml").read_text(encoding="utf-8"))
    btc = {p["id"]: p for p in d["pairs"]}["bitcoin_monthly_ladder"]
    nov = {m["month"]: m for m in btc["markets"]}["2025-11"]
    assert [r["slug"] for r in nov["inactive_excluded"]] == [
        "will-bitcoin-dip-to-100000-in-november"
    ]


# ---- A21 -------------------------------------------------------------------------
def _btc():
    import yaml

    d = yaml.safe_load((SCRIPT.parent.parent / "config" / "pairs.yaml").read_text(encoding="utf-8"))
    return {p["id"]: p for p in d["pairs"]}["bitcoin_monthly_ladder"]


def test_built_yaml_procedure_states_touch_rule_correctly():
    proc = _btc()["signal"]["per_hour_procedure"][0]
    assert "dip strike K is TOUCHED if any dip rung with strike <= K" in proc
    assert "up strike K is TOUCHED if any up rung with strike >= K" in proc
    assert "strike >= K in that month" not in proc.split("up strike")[0]


def test_direction_from_description():
    high = 'has a final "High" price of $72,500.00 or higher.'
    low = "has a final “Low” price of $85,000 or lower."
    both = 'a final "High" or "Low" price equal to or beyond'
    assert direction_from_description(high) == "up"
    assert direction_from_description(low) == "dip"
    assert direction_from_description(both) is None
    assert direction_from_description(None) is None
    assert rung_direction("Will Bitcoin reach $85,000 in December?", low) == ("dip", True)
    assert rung_direction("Will Bitcoin reach $72,500?", high) == ("up", False)
    assert rung_direction("Will Bitcoin dip to $60,000?", low) == ("dip", False)
    assert rung_direction("Will Bitcoin dip to $60,000?", both) == ("dip", False)
    assert rung_direction("Will Bitcoin reach $90,000?", None) == ("up", False)


def test_built_yaml_a21_direction_overrides_and_usable_months():
    btc = _btc()
    months = {m["month"]: m for m in btc["markets"]}
    flagged: dict[str, set[str]] = {}
    for m in btc["markets"]:
        for k in ("up_ladder", "dip_ladder", "partial_window_rungs", "inactive_excluded"):
            for r in m[k]:
                if r["direction_from_description"]:
                    flagged.setdefault(m["month"], set()).add(r["strike_usd"])
                    assert r["direction"] == "dip"
    assert flagged == {
        "2024-11": {67500.0, 65000.0, 62500.0, 60000.0},
        "2024-12": {90000.0, 85000.0},
    }
    assert months["2024-11"]["usable"] and months["2024-12"]["usable"]
    assert {r["strike_usd"] for r in months["2024-12"]["dip_ladder"]} == {85000.0, 90000.0}
    assert [g["month"] for g in btc["coverage"]["gaps"]] == ["2025-03", "2025-12"]
    assert btc["coverage"]["signal_first_active_utc"] == months["2024-11"]["first_usable_utc"]
    nov = months["2024-11"]
    assert nov["n_partial_window_rungs"] == 1 and nov["n_inactive_excluded"] == 1


def test_whole_month_rung_created_after_t_does_not_suppress_partial_rung():
    partial = _rung("u80-fresh", "up", 80000, _dt(3), partial=("description_creation",))
    whole = _rung("u80-whole", "up", 80000, _dt(10))
    quotes = {"u80-fresh": 0.6, "u80-whole": 0.2}
    pts = select_ladder([partial, whole], "up", _dt(6), quotes)
    assert [(x.p, x.source, x.slug) for x in pts] == [(0.6, "partial_window", "u80-fresh")]
    # once the whole-month rung exists (and is 24h old) it takes over
    pts = select_ladder([partial, whole], "up", _dt(12), quotes)
    assert [(x.p, x.source) for x in pts] == [(0.2, "whole_month")]


def test_between_guard_compares_dates_only_jan31_open_feb1_window_not_partial():
    open_jan31 = datetime(2026, 2, 1, 3, tzinfo=UTC)  # 2026-01-31 22:00 ET
    d = "any candle between February 1, 2026, 00:00 and February 28"
    assert detect_partial_window("s", d, 2026, open_jan31) == []
    # a later start day in the same month is still partial
    d2 = "any candle between February 2, 2026, 00:00 and February 28"
    assert detect_partial_window("s", d2, 2026, open_jan31) == ["description_between"]


def test_rung_created_before_touch_is_not_flagged_created_after_touch():
    rungs = [
        _rung("d60", "dip", 60000, _dt(1), _dt(6, 4), True),
        _rung("d65-early", "dip", 65000, _dt(2)),  # created before the touch at 02-06T04
        _rung("d65-late", "dip", 65000, _dt(6, 5)),
    ]
    assert flag_created_after_touch(rungs) == {"d65-late"}


def test_two_whole_month_rungs_at_one_strike_resolve_to_earliest_created_then_slug():
    rungs = [
        _rung("b", "up", 90000, _dt(2)),
        _rung("a", "up", 90000, _dt(2)),
        _rung("c", "up", 90000, _dt(1)),
    ]
    quotes = {"a": 0.1, "b": 0.2, "c": 0.3}
    pts = select_ladder(rungs, "up", _dt(10), quotes)
    assert [(x.slug, x.p) for x in pts] == [("c", 0.3)]
    rungs = rungs[:2]
    assert [x.slug for x in select_ladder(rungs, "up", _dt(10), quotes)] == ["a"]

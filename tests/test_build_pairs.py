"""Offline unit tests for the pure pair helpers (poly_actor.pairs) and the
hardcoded event-time tables in scripts/build_pairs.py. No network."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from poly_actor.pairs import et_to_utc, ladder_crossing, parse_cpi_bucket, parse_strike

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

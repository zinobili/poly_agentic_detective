"""Official FOMC and BLS CPI announcement-time tables (NOT derived from Gamma endDate/closedTime).

Sources: federalreserve.gov FOMC calendar, bls.gov CPI schedule (incl. the 2025 shutdown revisions).
Native timezone America/New_York (FOMC 14:00 ET statement, CPI 08:30 ET); converted to UTC through
zoneinfo (DST-correct). Resolution: one instant per event. Each time is cross-checked against the
earliest market `closedTime` in the cached dumps; a mismatch aborts the build.
"""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from poly_actor.pairs import et_to_utc
from poly_actor.pairs_build.gamma import GammaClient
from poly_actor.pairs_build.slugs import CPI_MONTHS, FED_MEETINGS
from poly_actor.pairs_build.util import iso, plus_hours

# ---------------------------------------------------------------------------
# FOMC / CPI announcement-time tables (hardcoded official dates; NOT derived
# from Gamma endDate or closedTime).
#
# Round-3 fix: the earlier draft derived 2026-2027 FOMC dates from the UTC day
# of a Gamma endDate set at 23:59 ET, which is the NEXT UTC day, and was off
# by one day for 2026-10 / 2026-12 / 2027-01. That derivation is removed.
# Every date below is the official calendar; `check_event_times_against_closed`
# cross-checks them against the earliest closedTime in the cached dumps.
# ---------------------------------------------------------------------------
# FOMC decision day (2nd meeting day, statement 14:00 ET). Source: official
# calendar https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DECISION_DATES_ET: dict[str, tuple[int, int, int]] = {
    "2024-11": (2024, 11, 7),
    "2024-12": (2024, 12, 18),
    "2025-01": (2025, 1, 29),
    "2025-03": (2025, 3, 19),
    "2025-05": (2025, 5, 7),
    "2025-06": (2025, 6, 18),
    "2025-07": (2025, 7, 30),
    "2025-09": (2025, 9, 17),
    "2025-10": (2025, 10, 29),
    "2025-12": (2025, 12, 10),
    "2026-01": (2026, 1, 28),
    "2026-03": (2026, 3, 18),
    "2026-04": (2026, 4, 29),
    "2026-06": (2026, 6, 17),
    "2026-07": (2026, 7, 29),
    "2026-09": (2026, 9, 16),
    "2026-10": (2026, 10, 28),
    "2026-12": (2026, 12, 9),
    "2027-01": (2027, 1, 27),
}

# BLS CPI release (08:30 ET) keyed by the reference month of the figure.
# Sources: https://www.bls.gov/schedule/news_release/cpi.htm (2026 dates,
# fetched 2026-10-01, incl. Sep-2026 -> 2026-10-14 CONFIRMED), the 2025 BLS
# schedule, and the BLS shutdown-revised dates for 2025-09 (2025-10-24) and
# 2025-11 (2025-12-18). Each of these is additionally cross-checked against
# the earliest closedTime in the cached dumps.
CPI_RELEASE_DATES_ET: dict[str, tuple[int, int, int]] = {
    "2024-11": (2024, 12, 11),
    "2024-12": (2025, 1, 15),
    "2025-01": (2025, 2, 12),
    "2025-02": (2025, 3, 12),
    "2025-03": (2025, 4, 10),
    "2025-04": (2025, 5, 13),
    "2025-05": (2025, 6, 11),
    "2025-06": (2025, 7, 15),
    "2025-07": (2025, 8, 12),
    "2025-08": (2025, 9, 11),
    "2025-09": (2025, 10, 24),  # shutdown-delayed (normally ~Oct 15)
    # 2025-10: NO BLS release (shutdown; see CPI_EXCLUDED)
    "2025-11": (2025, 12, 18),
    "2025-12": (2026, 1, 13),
    "2026-01": (2026, 2, 13),
    "2026-02": (2026, 3, 11),
    "2026-03": (2026, 4, 10),
    "2026-04": (2026, 5, 12),
    "2026-05": (2026, 6, 10),
    "2026-06": (2026, 7, 14),
    "2026-07": (2026, 8, 12),
    "2026-08": (2026, 9, 11),
    "2026-09": (2026, 10, 14),
}
CPI_DATES_UNVERIFIED: set[str] = set()  # month keys not confirmed against the BLS schedule

# Reference months with a Polymarket event but no BLS release: dropped.
CPI_EXCLUDED: dict[str, str] = {
    "2025-10": (
        "BLS did not publish October-2025 CPI (federal shutdown: no October survey data was collected). "
        "Polymarket event october-inflation-annual exists ($282K) but there is no 08:30 ET release to "
        "anchor a roll or event-study window; its resolution (2025-11-22) is a market-rule artifact. "
        "Dropped from the series and from the release-day event study."
    ),
}


def fomc_event_times_utc() -> dict[str, dict[str, str]]:
    out = {}
    for key, ymd in FOMC_DECISION_DATES_ET.items():
        decision = et_to_utc(ymd, (14, 0))
        out[key] = {"decision_utc": decision, "roll_utc": plus_hours(decision, 1)}
    return out


def cpi_event_times_utc() -> dict[str, dict[str, str]]:
    out = {}
    for key, ymd in CPI_RELEASE_DATES_ET.items():
        release = et_to_utc(ymd, (8, 30))
        out[key] = {
            "release_utc": release,
            "roll_utc": plus_hours(release, 1),
            "verified_against_bls": key not in CPI_DATES_UNVERIFIED,
        }
    return out


_NY = ZoneInfo("America/New_York")
CLOSE_LAG_MAX_H = 24  # A16: earliest closedTime must be 0..24h after the hardcoded event time


def _earliest_closed_time(events: list[dict]) -> str | None:
    """Earliest market-level closedTime across the events (UTC ISO) or None."""
    ts = [
        iso(m.get("closedTime"))
        for e in events
        for m in e.get("markets", [])
        if m.get("closedTime")
    ]
    return min(ts) if ts else None


def check_event_times_against_closed(
    gamma: GammaClient,
    label: str,
    times: dict[str, dict[str, str]],
    time_field: str,
    slugs_by_key: dict[str, list[str]],
) -> list[dict]:
    """For each RESOLVED event: the release/decision time must fall on the same
    ET calendar day as, or before, the earliest closedTime, AND (A16, two-sided)
    the earliest closedTime must be 0..24h after the event time. A later ET day or
    a negative lag means the hardcoded time is wrong (the market cannot close
    before the event); a lag over 24h means it is probably the wrong day.
    Prints a warning table of mismatches and returns them (empty list = pass)."""
    bad = []
    gaps_h: list[float] = []
    n_checked = 0
    for key, t in sorted(times.items()):
        events = [e for e in (gamma.get_event(s) for s in slugs_by_key.get(key, [])) if e]
        events = [e for e in events if e.get("closed")]
        if not events:
            continue
        earliest = _earliest_closed_time(events)
        if earliest is None:
            continue
        n_checked += 1
        ev_et = datetime.fromisoformat(t[time_field].replace("Z", "+00:00")).astimezone(_NY).date()
        cl_et = datetime.fromisoformat(earliest.replace("Z", "+00:00")).astimezone(_NY).date()
        ev_dt = datetime.fromisoformat(t[time_field].replace("Z", "+00:00"))
        gap_h = (
            datetime.fromisoformat(earliest.replace("Z", "+00:00")) - ev_dt
        ).total_seconds() / 3600
        gaps_h.append(gap_h)
        if ev_et > cl_et or not (0 <= gap_h <= CLOSE_LAG_MAX_H):
            bad.append(
                {
                    "series": label,
                    "key": key,
                    "event_time_utc": t[time_field],
                    "earliest_closed_utc": earliest,
                    "closed_minus_event_h": round(gap_h, 2),
                }
            )
    print(
        f"  cross-check {label}: {n_checked} resolved events checked, {len(bad)} mismatches; "
        f"closedTime - event time in [{min(gaps_h, default=0):.1f}h, {max(gaps_h, default=0):.1f}h] "
        f"(required 0..{CLOSE_LAG_MAX_H}h)",
        file=sys.stderr,
    )
    if bad:
        print(
            f"  WARNING: event time falls after earliest closedTime, or closedTime is > {CLOSE_LAG_MAX_H}h later:",
            file=sys.stderr,
        )
        for b in bad:
            print(
                f"    {b['series']} {b['key']}: event {b['event_time_utc']} vs closed {b['earliest_closed_utc']} ({b['closed_minus_event_h']}h)",
                file=sys.stderr,
            )
    return bad


def run_time_cross_checks(gamma: GammaClient) -> None:
    """Hard assertion: any mismatch aborts the build (after printing the table)."""
    bad = check_event_times_against_closed(
        gamma,
        "fed",
        fomc_event_times_utc(),
        "decision_utc",
        {k: [v] for k, v in FED_MEETINGS.items()},
    )
    bad += check_event_times_against_closed(
        gamma, "cpi", cpi_event_times_utc(), "release_utc", CPI_MONTHS
    )
    if bad:
        raise SystemExit(f"{len(bad)} event-time cross-check mismatches (see table above)")

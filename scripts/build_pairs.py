"""Regenerate config/pairs.yaml from cached Gamma API dumps.

Step 2 (pick pairs) tooling for milestone 1. This script is the single
source of truth for how `config/pairs.yaml` was built: every market slug,
CLOB token id, volume and date in the yaml traces back to a JSON file in
`data/scratch/step2/` written by this script.

Usage (from repo root):
    .venv/Scripts/python.exe scripts/build_pairs.py              # build only, fully offline from cache
    .venv/Scripts/python.exe scripts/build_pairs.py --refetch     # refresh the whole cache, then build
    .venv/Scripts/python.exe scripts/build_pairs.py --fetch-slugs SLUG [SLUG ...]  # fetch just these events

`--refetch` re-pulls everything from the live Gamma API
(https://gamma-api.polymarket.com): polite (0.5s sleep between calls,
exponential backoff retry on 429/5xx), and paginates every tag-based event
listing to exhaustion (`offset` steps of 100 until a short/empty page comes
back) -- the step-2 validator flagged that un-paginated listings silently
truncated at the API's page-size default (50 or 100), which caused several
real meetings/months to be missed in the first draft. Without `--refetch`,
the script only reads what's already cached in `data/scratch/step2/` (fully
offline, safe to re-run); a cache miss RAISES `CacheMiss` instead of silently
touching the network (use `--fetch-slugs` for a targeted fetch).

`data/scratch/step2/` (not `data/raw/`) is used deliberately: these are
step-2 research/discovery dumps, not the project's immutable ingestion
store. `data/raw/` is reserved for the production `ingest/` modules built in
step 3 (see CLAUDE.md's "Raw data is immutable" rule) and this script must
never write there.

Important data-quality notes baked into this script (see docs/step2_pairs.md
and docs/preregistration.md for the full writeup):
  - Gamma event `endDate` is NOT the announcement/release time for either
    the Fed or CPI series -- it is set some hours (sometimes most of a day)
    *before* the actual 2pm ET FOMC statement / 8:30am ET BLS release. Roll
    timing for both series uses hardcoded tables of the official FOMC / BLS
    dates (ET -> UTC through zoneinfo, DST-correct), not `endDate` and not the
    `closed` flag (which reflects current state and is a look-ahead risk).
    Every hardcoded time is cross-checked against the earliest market
    `closedTime` in the cache; a mismatch aborts the build.
  - Signals are spliced from *changes*, never from level differences taken
    across two different underlying events (see `splice_rule` in the
    emitted yaml).
"""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

from poly_actor.pairs import (
    BtcRung,
    detect_partial_window,
    et_to_utc,
    flag_created_after_touch,
    monotone_ladder_crossing_diag,
    parse_cpi_bucket,
    parse_from_date,
    parse_strike,
    rung_direction,
    select_ladder,
)

GAMMA_BASE = "https://gamma-api.polymarket.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "scratch" / "step2"
CONFIG_OUT = REPO_ROOT / "config" / "pairs.yaml"

REQUEST_TIMEOUT_S = 20
MAX_RETRIES = 4
POLITE_SLEEP_S = 0.5
PAGE_LIMIT = 100
MAX_CALLS = 120

REFETCH = False
FETCH_SLUGS: set[str] = set()  # --fetch-slugs: refresh only these event slugs (targeted, few calls)
_call_count = 0


class CacheMiss(RuntimeError):
    """A required Gamma dump is not cached and no fetch flag was given (never hit the network silently)."""


# ---------------------------------------------------------------------------
# Polite Gamma client: timeout, exponential backoff on 429/5xx, sleep between
# calls, hard call-budget cap.
# ---------------------------------------------------------------------------
def _gamma_get(path: str, params: dict[str, Any]) -> Any:
    global _call_count
    if _call_count >= MAX_CALLS:
        raise RuntimeError(f"hit MAX_CALLS={MAX_CALLS} budget; aborting refetch")
    url = f"{GAMMA_BASE}{path}"
    delay = 1.0
    last_exc: Exception | None = None
    resp = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:
            last_exc = exc
            resp = None
        if resp is not None:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"{resp.status_code} from {url}")
            else:
                break
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    if resp is None:
        raise last_exc
    _call_count += 1
    print(f"  [call {_call_count}] GET {path} {params}", file=sys.stderr)
    time.sleep(POLITE_SLEEP_S)
    resp.raise_for_status()
    return resp.json()


def _dump(name: str, data: Any) -> None:
    (CACHE_DIR / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load(name: str) -> Any:
    p = CACHE_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def paginate_events(tag_slug: str, closed: bool, max_pages: int = 6) -> list[dict]:
    """GET /events?tag_slug=...&closed=...  paginated to exhaustion.

    Fixes the step-2-draft bug: un-paginated calls silently truncated at the
    API's page size (we observed exactly 50 or 100 rows back for several
    tags -- a dead giveaway of truncation, confirmed by this function
    finding more rows once paginated).

    `max_pages` is a safety cap (default 6 pages = 600 events): broad tags
    like "bitcoin" and "economy" turned out to have 1000+ events across
    Polymarket's full history (we hit a server-side 422 past offset 2100 on
    "bitcoin" during development) and are NOT used with this function for
    that reason -- see the module docstring / docs/step2_pairs.md for why
    the Bitcoin and CPI monthly series are discovered via direct per-month
    slug lookups instead of tag pagination. This function is only called on
    tags confirmed small (fed-rates, recession, tariff, general-tariff);
    the cap just stops a surprise blow-up from burning the call budget.
    """
    cache_name = f"gamma_events_{tag_slug}_{str(closed).lower()}_all.json"
    cached = _load(cache_name)
    if cached is not None and not REFETCH:
        return cached
    if not REFETCH:
        raise CacheMiss(f"{cache_name} not cached; rerun with --refetch")
    all_items: list[dict] = []
    offset = 0
    pages = 0
    while pages < max_pages:
        page = _gamma_get(
            "/events",
            {
                "tag_slug": tag_slug,
                "closed": str(closed).lower(),
                "limit": PAGE_LIMIT,
                "offset": offset,
            },
        )
        _dump(f"gamma_events_{tag_slug}_{str(closed).lower()}_offset{offset}.json", page)
        pages += 1
        if not page:
            break
        all_items.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    else:
        print(
            f"  WARNING: {tag_slug} closed={closed} hit max_pages={max_pages} "
            "without an empty page -- listing may be incomplete, tag is "
            "broader than expected",
            file=sys.stderr,
        )
    _dump(cache_name, all_items)
    return all_items


def get_event(slug: str) -> dict | None:
    """GET /events?slug=...  single event, full detail (incl. markets[])."""
    cache_name = f"gamma_event_{slug}_full.json"
    cached = _load(cache_name)
    if cached is not None and not (REFETCH or slug in FETCH_SLUGS):
        return cached[0] if cached else None
    if cached is None and not (REFETCH or slug in FETCH_SLUGS):
        raise CacheMiss(
            f"event {slug!r} not cached ({cache_name}); rerun with --refetch "
            f"(everything) or --fetch-slugs {slug} (just this one)"
        )
    data = _gamma_get("/events", {"slug": slug})
    _dump(cache_name, data)
    return data[0] if data else None


# ---------------------------------------------------------------------------
# Refetch: everything needed to build the 4 pairs.
#
# Discovery method differs by series, deliberately:
#   - Fed: `tag_slug=fed-rates` is small (171 events total) and was fully
#     paginated during development -- every `fed-decision-in-*` and
#     `fed-interest-rates-<month>-<year>` event is confirmed present in that
#     one paginated pull (see gamma_events_fed-rates_{true,false}_all.json).
#     FED_MEETINGS below is the ground-truth slug for each real FOMC meeting,
#     read off that paginated list (NOT guessed).
#   - Bitcoin / CPI: `tag_slug=bitcoin` and `tag_slug=inflation` turned out
#     to be enormous (bitcoin alone has 1000+ events across Polymarket's
#     full history -- we hit a server 422 past offset 2100 trying to
#     paginate it) and include many unrelated one-off markets per country/
#     topic. Exhaustively paginating them is both wasteful (would burn the
#     whole call budget) and noisy (most results aren't the monthly series
#     we want). Since both series follow a strict one-event-per-calendar-
#     month naming convention, we instead enumerate every calendar month in
#     range directly and do a bounded, auditable slug lookup per month --
#     functionally equivalent to "paginate to exhaustion" for a strictly
#     periodic series, at a fraction of the cost.
# ---------------------------------------------------------------------------
TAGS_TO_PAGINATE = [
    ("fed-rates", True),
    ("fed-rates", False),
    ("recession", True),
    ("recession", False),
    ("tariff", True),
    ("tariff", False),
    ("general-tariff", True),
    ("general-tariff", False),
]

# Ground truth: real FOMC meeting (Y, M) -> Gamma event slug, read off the
# fully-paginated fed-rates listing. Covers every meeting from 2024-11
# onward (the ~730-day yfinance 1h lookback window from 2026-10-01 starts
# ~2024-10-01; no per-meeting market exists before 2025-03 under this
# series' naming, and 2024-09 and earlier meetings -- if markets for them
# exist at all -- are outside the yfinance window anyway, so excluded).
FED_MEETINGS: dict[str, str] = {
    "2024-11": "fed-interest-rates-november-2024",
    "2024-12": "fed-interest-rates-december-2024",
    "2025-01": "fed-interest-rates-january-2025",
    "2025-03": "fed-decision-in-march",
    "2025-05": "fed-decision-in-may-2025",
    "2025-06": "fed-decision-in-june",
    "2025-07": "fed-decision-in-july",
    "2025-09": "fed-decision-in-september",
    "2025-10": "fed-decision-in-october",
    "2025-12": "fed-decision-in-december",
    "2026-01": "fed-decision-in-january",
    "2026-03": "fed-decision-in-march-885",
    "2026-04": "fed-decision-in-april",
    "2026-06": "fed-decision-in-june-825",
    "2026-07": "fed-decision-in-july-181",
    "2026-09": "fed-decision-in-september-762",
    "2026-10": "fed-decision-in-october-20260617190323537",
    "2026-12": "fed-decision-in-december-20260729232808632",
    "2027-01": "fed-decision-in-january-20260729233815502",
}

# Bitcoin monthly series: one event per calendar month, Nov-2024 through the
# active Oct-2026 month. Slugs enumerated directly (see rationale above);
# the few irregular ones (year-suffix inconsistently present, one random
# numeric suffix on Oct-2025) were found via the original top-volume pull
# and are hardcoded here as confirmed-working. "candidates" lists are tried
# in order; the first that resolves is used, and a miss on every candidate
# is logged as a genuine gap (used for Feb/Aug-2026 CPI and any BTC month
# that turns out not to exist).
BTC_MONTHS: dict[str, list[str]] = {
    "2024-11": ["what-price-will-bitcoin-hit-in-november"],
    "2024-12": ["what-price-will-bitcoin-hit-in-december"],
    "2025-01": ["what-price-will-bitcoin-hit-in-january"],
    "2025-02": ["what-price-will-bitcoin-hit-in-february"],
    "2025-03": [
        "what-price-will-bitcoin-hit-in-march",
        "what-price-will-bitcoin-hit-in-march-2025",
    ],
    "2025-04": ["what-price-will-bitcoin-hit-in-april"],
    "2025-05": ["what-price-will-bitcoin-hit-in-may"],
    "2025-06": ["what-price-will-bitcoin-hit-in-june"],
    "2025-07": ["what-price-will-bitcoin-hit-in-july"],
    "2025-08": ["what-price-will-bitcoin-hit-in-august"],
    "2025-09": ["what-price-will-bitcoin-hit-in-september"],
    "2025-10": [
        "what-price-will-bitcoin-hit-in-october-985",
        "what-price-will-bitcoin-hit-in-october",
    ],
    "2025-11": ["what-price-will-bitcoin-hit-in-november-2025"],
    "2025-12": ["what-price-will-bitcoin-hit-in-december-2025"],
    "2026-01": ["what-price-will-bitcoin-hit-in-january-2026"],
    "2026-02": ["what-price-will-bitcoin-hit-in-february-2026"],
    "2026-03": ["what-price-will-bitcoin-hit-in-march-2026"],
    "2026-04": ["what-price-will-bitcoin-hit-in-april-2026"],
    "2026-05": ["what-price-will-bitcoin-hit-in-may-2026"],
    "2026-06": ["what-price-will-bitcoin-hit-in-june-2026"],
    "2026-07": ["what-price-will-bitcoin-hit-in-july-2026"],
    "2026-08": ["what-price-will-bitcoin-hit-in-august-2026"],
    "2026-09": ["what-price-will-bitcoin-hit-in-september-2026"],
    "2026-10": ["what-price-will-bitcoin-hit-in-october-2026"],
}

# CPI monthly YoY series: one event per BLS release, keyed by the reference
# month of the figure. 2026-02 exists but has $0 volume (recorded as a gap,
# not silently skipped). 2026-01 and 2026-03 have two companion bucket-split
# events (lower/higher brackets) that must be merged. 2025-10 is NOT in this
# table: BLS never published October-2025 CPI (see CPI_EXCLUDED).
CPI_MONTHS: dict[str, list[str]] = {
    "2024-11": ["november-inflation"],
    "2024-12": ["december-inflation"],
    "2025-01": ["january-inflation-annual"],
    "2025-02": ["february-inflation-annual"],
    "2025-03": ["march-inflation-annual"],
    "2025-04": ["april-inflation-annual"],
    "2025-05": ["may-inflation-annual"],
    "2025-06": ["june-inflation-annual"],
    "2025-07": ["july-inflation-annual-462"],
    "2025-08": ["august-inflation-annual"],
    "2025-09": ["september-inflation-annual"],
    "2025-11": ["november-inflation-annual"],
    "2025-12": ["december-inflation-us-annual"],
    "2026-01": ["january-inflation-us-annual-lower-brackets-817", "january-inflation-us-annual"],
    "2026-02": ["february-inflation-us-annual", "february-inflation-annual-2026"],
    "2026-03": ["march-inflation-us-annual", "march-inflation-us-annual-higher-brackets"],
    "2026-04": ["april-inflation-us-annual"],
    "2026-05": ["may-inflation-us-annual"],
    "2026-06": ["june-inflation-us-annual-20260610151727862"],
    "2026-07": ["july-inflation-us-annual-20260714150613267"],
    "2026-08": ["august-inflation-us-annual-1786474662954"],
    "2026-09": ["september-inflation-us-annual"],
}

RECESSION_SLUGS = ["us-recession-in-2025", "us-recession-by-end-of-2026"]


def fetch_month_series(months: dict[str, list[str]], label: str) -> dict[str, dict | None]:
    """Try each candidate slug for every month key in order; first hit wins.
    Returns {month_key: event_or_None}. A None means every candidate for
    that month was checked and came back empty -- a genuine, logged gap."""
    out: dict[str, dict | None] = {}
    for key, candidates in months.items():
        found = None
        for slug in candidates:
            e = get_event(slug)
            if e is not None:
                found = e
                break
        out[key] = found
        status = found["slug"] if found else "GAP (all candidates empty)"
        print(f"  {label} {key}: {status}", file=sys.stderr)
    return out


def fetch_all_candidates(months: dict[str, list[str]]) -> None:
    """Like fetch_month_series but fetches every candidate slug for months
    that list more than one (used for the CPI companion-event months, where
    we need BOTH bucket-split events, not just the first hit)."""
    for candidates in months.values():
        for slug in candidates:
            get_event(slug)


def refetch_all() -> None:
    print("=== paginating small tag listings ===", file=sys.stderr)
    for tag, closed in TAGS_TO_PAGINATE:
        items = paginate_events(tag, closed)
        print(f"{tag} closed={closed}: {len(items)} events", file=sys.stderr)

    print("=== Fed meetings (ground truth from paginated fed-rates list) ===", file=sys.stderr)
    for key, slug in FED_MEETINGS.items():
        get_event(slug)
        print(f"  {key}: {slug}", file=sys.stderr)

    print("=== Bitcoin monthly series ===", file=sys.stderr)
    fetch_month_series(BTC_MONTHS, "BTC")

    print("=== CPI monthly series (fetching every candidate for merge months) ===", file=sys.stderr)
    fetch_all_candidates(CPI_MONTHS)

    print("=== recession ===", file=sys.stderr)
    for slug in RECESSION_SLUGS:
        get_event(slug)

    print(f"=== done, {_call_count} Gamma calls used (budget {MAX_CALLS}) ===", file=sys.stderr)


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


def _ceil_hour(iso_z: str) -> str:
    """Round a UTC ISO time UP to the next whole hour (unchanged if already on the hour)."""
    dt = datetime.fromisoformat(iso_z.replace("Z", "+00:00"))
    floor = dt.replace(minute=0, second=0, microsecond=0)
    if dt > floor:
        floor += timedelta(hours=1)
    return floor.isoformat().replace("+00:00", "Z")


def _plus_hours(iso_z: str, hours: int) -> str:
    return (
        (datetime.fromisoformat(iso_z.replace("Z", "+00:00")) + timedelta(hours=hours))
        .isoformat()
        .replace("+00:00", "Z")
    )


def fomc_event_times_utc() -> dict[str, dict[str, str]]:
    out = {}
    for key, ymd in FOMC_DECISION_DATES_ET.items():
        decision = et_to_utc(ymd, (14, 0))
        out[key] = {"decision_utc": decision, "roll_utc": _plus_hours(decision, 1)}
    return out


def cpi_event_times_utc() -> dict[str, dict[str, str]]:
    out = {}
    for key, ymd in CPI_RELEASE_DATES_ET.items():
        release = et_to_utc(ymd, (8, 30))
        out[key] = {
            "release_utc": release,
            "roll_utc": _plus_hours(release, 1),
            "verified_against_bls": key not in CPI_DATES_UNVERIFIED,
        }
    return out


_NY = ZoneInfo("America/New_York")
CLOSE_LAG_MAX_H = 24  # A16: earliest closedTime must be 0..24h after the hardcoded event time


def _earliest_closed_time(events: list[dict]) -> str | None:
    """Earliest market-level closedTime across the events (UTC ISO) or None."""
    ts = [
        _iso(m.get("closedTime"))
        for e in events
        for m in e.get("markets", [])
        if m.get("closedTime")
    ]
    return min(ts) if ts else None


def check_event_times_against_closed(
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
        events = [e for e in (get_event(s) for s in slugs_by_key.get(key, [])) if e]
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


def run_time_cross_checks() -> None:
    """Hard assertion: any mismatch aborts the build (after printing the table)."""
    bad = check_event_times_against_closed(
        "fed", fomc_event_times_utc(), "decision_utc", {k: [v] for k, v in FED_MEETINGS.items()}
    )
    bad += check_event_times_against_closed("cpi", cpi_event_times_utc(), "release_utc", CPI_MONTHS)
    if bad:
        raise SystemExit(f"{len(bad)} event-time cross-check mismatches (see table above)")


# ===========================================================================
# BUILD: turn the cached dumps into config/pairs.yaml
# ===========================================================================
TODAY = "2026-10-01"
STOCK_WINDOW_START = "2024-10-01T00:00:00Z"  # yfinance 1h ~730d lookback from TODAY (step 1)
BTC_MIN_EVENT_AGE_H = (
    24  # a BTC event's rungs count only once the event has been open this long (time-t rule)
)
CPI_EDGE_MASS_MAX = 0.10


class _Flow(dict):
    """dict rendered in YAML flow style ({a: 1, b: 2}) to keep long lists compact."""


def _flow_repr(dumper: yaml.SafeDumper, data: _Flow) -> Any:
    return dumper.represent_mapping("tag:yaml.org,2002:map", dict(data), flow_style=True)


yaml.SafeDumper.add_representer(_Flow, _flow_repr)


def _iso(ts: str | None) -> str | None:
    """Normalise any Gamma timestamp to ISO-8601 UTC with a trailing Z."""
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _yes(m: dict) -> tuple[str, float | None]:
    """-> (Yes token id, final/current Yes price or None when Gamma omits it)."""
    outs = json.loads(m["outcomes"])
    toks = json.loads(m["clobTokenIds"])
    i = outs.index("Yes")
    raw = m.get("outcomePrices")
    price = float(json.loads(raw)[i]) if raw else None
    return toks[i], price


def _vol(x: Any) -> float:
    return round(float(x or 0), 2)


def _event(slug: str) -> dict | None:
    return get_event(slug)


# ---- Fed ------------------------------------------------------------------
def classify_fed(question: str) -> tuple[str, int | None, bool]:
    """-> (kind, delta_bp, open_ended). Convention: open-ended buckets ("50+",
    "75+", "25+") use the stated size as delta (e.g. "50+ bps cut" -> -50).
    Catch-all buckets ("another level") get kind 'other', delta None (excluded
    from the score; their mass is tracked as other_mass)."""
    q = question.lower()
    if "no change" in q:
        return "no_change", 0, False
    m = re.search(r"(\d+)(\+)?\s*bps", q)
    if m and "decrease" in q:
        bp = int(m.group(1))
        return f"decrease_{bp}bp", -bp, bool(m.group(2))
    if m and "increase" in q:
        bp = int(m.group(1))
        return f"increase_{bp}bp", bp, bool(m.group(2))
    return "other", None, False


def build_fed() -> dict:
    times = fomc_event_times_utc()
    keys = sorted(FED_MEETINGS)
    meetings = []
    prev_roll = STOCK_WINDOW_START
    for key in keys:
        e = _event(FED_MEETINGS[key])
        if e is None:
            raise RuntimeError(f"missing cached Fed event {FED_MEETINGS[key]}")
        outcomes: dict[str, dict] = {}
        others = []
        for m in e["markets"]:
            tok, price = _yes(m)
            kind, delta, open_ended = classify_fed(m.get("question", ""))
            rec = {
                "slug": m["slug"],
                "token_id_yes": tok,
                "delta_bp": delta,
                "open_ended": open_ended,
                "volume_usd": _vol(m.get("volume")),
                "final_yes_price": price,
            }
            if kind == "other":
                others.append(_Flow(rec))
            else:
                outcomes[kind] = _Flow(rec)
        winner = None
        if e["closed"]:
            cands = {k: v["final_yes_price"] for k, v in outcomes.items()}
            cands.update({f"other_{i}": o["final_yes_price"] for i, o in enumerate(others)})
            winner = max(cands, key=cands.get)
        use_from = max(prev_roll, _iso(e["startDate"]))
        t = times[key]
        if _iso(e["startDate"]) > prev_roll and key != keys[0]:
            print(f"  WARN fed {key}: event starts after previous roll", file=sys.stderr)
        meetings.append(
            {
                "meeting": key,
                "event_slug": e["slug"],
                "decision_time_utc": t["decision_utc"],
                "use_from_utc": use_from,
                "use_until_utc": t["roll_utc"],
                "gamma_start": _iso(e["startDate"]),
                "gamma_end_date_DO_NOT_ROLL_ON": _iso(
                    e["markets"][0].get("endDate") or e["endDate"]
                ),
                "resolved": bool(e["closed"]),
                "resolved_outcome": winner,
                "volume_usd": _vol(e.get("volume")),
                "outcome_set": sorted(outcomes),
                "outcomes": dict(sorted(outcomes.items())),
                "other_outcomes": others,
            }
        )
        prev_roll = t["roll_utc"]
    return {
        "id": "fed_decision",
        "priority": "primary",
        "analysis": "lead_lag_hourly_plus_event_study",
        "description": (
            "Per-FOMC-meeting Polymarket rate-decision events (mutually exclusive buckets: "
            "-75+/-50/-25/no change/+25/+50) vs long-duration Treasuries, broad equities and "
            "financials. One event per official FOMC meeting from 2024-11 to 2027-01 (19 meetings)."
        ),
        "tickers": ["TLT", "SPY", "XLF"],
        "expected_sign": {
            "TLT": "positive",
            "SPY": "positive",
            "XLF": "ambiguous",
        },
        "xlf_plan": "Test XLF return relative to SPY (XLF - SPY), not XLF alone; sign is not pre-specified.",
        "rationale": (
            "The signal is the market-implied expected rate change in bp; dovishness_bp = -expected change "
            "(more cuts priced = more dovish). A rise in dovishness lowers expected policy rates and long "
            "yields, lifting TLT (duration), so expected_sign for TLT is positive against dovishness. SPY "
            "is also positive on average (easier policy, lower discount rate) but weaker and regime "
            "dependent: cuts priced because of recession fear can hurt equities. XLF (banks) is "
            "ambiguous: lower rates compress net interest margins yet ease credit conditions and lift "
            "risk appetite, so no sign is pre-specified; XLF is instead tested relative to SPY "
            "(XLF - SPY) as a rate-sensitivity contrast."
        ),
        "signal": {
            "name": "fed_expected_change_bp",
            "formula": "sum_i(p_i * delta_i) / sum_i(p_i) over the named buckets of the active event",
            "zero_mass": "if sum_i(p_i) == 0 for an hour, drop the hour (no signal; never fill with 0)",
            "delta_bp": {
                "decrease_75bp": -75,
                "decrease_50bp": -50,
                "decrease_25bp": -25,
                "no_change": 0,
                "increase_25bp": 25,
                "increase_50bp": 50,
            },
            "open_ended_convention": (
                "Open-ended buckets ('50+', '75+', '25+') use the stated size as delta "
                "(e.g. a '50+ bps cut' bucket counts as -50bp). This understates tails; documented, "
                "not corrected."
            ),
            "missing_outcomes": "A bucket that does not exist for an event has p = 0 (contributes nothing).",
            "catch_all_bucket": (
                "'Will the FED change rates to another level' (2024-11, 2024-12 events only) has no "
                "defined delta: excluded from numerator and denominator; its price is stored as "
                "other_mass and hours with other_mass > 0.25 are dropped."
            ),
            "dovishness": "dovishness_bp = -fed_expected_change_bp (used for expected_sign above)",
            "p_i": "hourly last trade/mid price of each bucket's Yes token (step 3/4 defines the exact price field)",
        },
        "roll_rule": {
            "rule": (
                "Active event at time t = the event of the next FOMC meeting whose roll time has not "
                "yet passed, i.e. event k is used for use_from_utc <= t < use_until_utc, where "
                "use_until_utc = meeting decision time (14:00 ET -> UTC, DST-aware) + 1 hour. "
                "Consecutive events overlap in calendar time on Polymarket; the 'soonest unresolved "
                "meeting' wins."
            ),
            "never_roll_on": [
                "gamma endDate (hours BEFORE the announcement)",
                "gamma closed flag (current state: look-ahead)",
            ],
            "roll_offset_hours": 1,
            "event_time": "FOMC statement 14:00 America/New_York of the 2nd meeting day",
            "calendar_source": (
                "Official FOMC calendar, https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm, "
                "hardcoded in FOMC_DECISION_DATES_ET (all 19 meetings incl. 2026-10-28, 2026-12-09, "
                "2027-01-27); cross-checked against Gamma closedTime."
            ),
        },
        "splice_rule": SPLICE_RULE,
        "trading_hours_note": TRADING_HOURS_NOTE_US,
        "coverage": {
            "stock_window_start_utc": STOCK_WINDOW_START,
            "signal_first_active_utc": meetings[0]["use_from_utc"],
            "signal_last_active_through": TODAY,
            "gaps": [],
            "note": (
                "No 2025-02 or 2025-04 FOMC meetings exist (official calendar has none). Meetings "
                "before 2024-11 (e.g. fed-interest-rates-september-2024) exist on Gamma but fall "
                "outside the yfinance 1h window and are excluded."
            ),
        },
        "event_times_utc": [
            {"meeting": k, **times[k], "event_slug": FED_MEETINGS[k]} for k in keys
        ],
        "markets": meetings,
    }


# ---- Recession -------------------------------------------------------------
def build_recession() -> dict:
    mk = []
    for slug, period in (("us-recession-in-2025", "2025"), ("us-recession-by-end-of-2026", "2026")):
        e = _event(slug)
        if e is None:
            raise RuntimeError(f"missing cached recession event {slug}")
        m = e["markets"][0]
        tok, price = _yes(m)
        mk.append(
            {
                "period": period,
                "event_slug": e["slug"],
                "slug": m["slug"],
                "token_id_yes": tok,
                "start": _iso(m.get("startDate") or e["startDate"]),
                "end": _iso(m.get("endDate")),
                "closed_time": _iso(m.get("closedTime")),
                "event_level_end_date_stale": _iso(e["endDate"]),
                "resolved": bool(e["closed"]),
                "resolved_outcome": ("no_recession" if price < 0.5 else "recession")
                if e["closed"]
                else None,
                "current_yes_price": None if e["closed"] else price,
                "volume_usd": _vol(e.get("volume")),
            }
        )
    return {
        "id": "us_recession",
        "priority": "secondary",
        "analysis": "event_study",
        "description": (
            "'Will the US enter a recession' (calendar-year horizon) vs equities, small-cap relative "
            "performance and long Treasuries. Effectively one episode (the 2025 market resolved No), "
            "so no lead-lag inference is claimed; event study around large probability moves only."
        ),
        "tickers": ["SPY", "IWM", "TLT", "IWM-SPY"],
        "expected_sign": {
            "SPY": "negative",
            "IWM": "negative",
            "TLT": "positive",
            "IWM-SPY": "negative",
        },
        "rationale": (
            "Rising recession odds are a growth/earnings warning: SPY falls, and small caps (IWM) fall "
            "more because of floating-rate debt and thinner margins, so the IWM-SPY spread should fall. "
            "TLT should rise on flight to quality and expected easing. Signal: change in P(Yes)."
        ),
        "signal": {
            "name": "recession_p_yes",
            "formula": "hourly P(Yes) of the active market; use hourly changes",
        },
        "roll_rule": {
            "rule": (
                "Use us-recession-in-2025 until 2025-10-01T00:00:00Z (pre-registered, one quarter before "
                "its year-end horizon, when its probability collapses toward 0 and stops being informative), "
                "then us-recession-by-end-of-2026. Both markets are open in the overlap (2026 market "
                "opened 2025-09-29). Do not roll on closed_time/endDate."
            ),
            "roll_utc": "2025-10-01T00:00:00Z",
            "roll_offset_hours": 0,
        },
        "event_times_utc": [{"event": "switch_to_2026_market", "roll_utc": "2025-10-01T00:00:00Z"}],
        "splice_rule": SPLICE_RULE,
        "trading_hours_note": TRADING_HOURS_NOTE_US,
        "coverage": {
            "stock_window_start_utc": STOCK_WINDOW_START,
            "signal_first_active_utc": mk[0]["start"],
            "signal_last_active_through": TODAY,
            "gaps": [
                {
                    "from_utc": STOCK_WINDOW_START,
                    "to_utc": mk[0]["start"],
                    "reason": "no recession market exists before the 2025 market opened",
                }
            ],
            "note": (
                "2025 market: closedTime 2026-01-01T09:23:25Z (the event-level endDate of 2026-02-28 is "
                "misleading). 2026 market: market-level endDate 2027-01-31 (event-level 2026-12-31 is "
                "stale). Market-level fields are authoritative."
            ),
        },
        "markets": mk,
    }


# ---- Bitcoin ---------------------------------------------------------------
def build_btc() -> dict:
    months = []
    gaps = []
    for key in sorted(BTC_MONTHS):
        e = None
        for slug in BTC_MONTHS[key]:
            e = _event(slug)
            if e is not None:
                break
        y, mo = int(key[:4]), int(key[5:])
        ny, nm = (y + 1, 1) if mo == 12 else (y, mo + 1)
        month_end = et_to_utc((ny, nm, 1), (0, 0))
        roll = (
            (datetime.fromisoformat(month_end.replace("Z", "+00:00")) + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        if e is None:
            gaps.append(
                {
                    "month": key,
                    "tried": BTC_MONTHS[key],
                    "reason": "no Gamma event under any candidate slug",
                }
            )
            continue
        g_start = _iso(e["startDate"])
        g_start_dt = datetime.fromisoformat(g_start.replace("Z", "+00:00"))
        recs: list[_Flow] = []
        brungs: list[BtcRung] = []
        for m in e["markets"]:
            q = m.get("question", "")
            strike = parse_strike(q)
            tok, price = _yes(m)
            ladder, dir_from_desc = rung_direction(q, m.get("description"))
            direction = "dip" if ladder == "dip" else "reach"
            created = _iso(m["createdAt"])
            closed = _iso(m.get("closedTime"))
            from_d = parse_from_date(m["slug"], y)
            # A21: inactive = active=false and no closedTime in the final snapshot
            # (structure only; a mild look-ahead). Not necessarily a duplicate.
            inactive = (not m.get("active")) and not m.get("closedTime")
            reasons = detect_partial_window(m["slug"], m.get("description"), y, g_start_dt)
            resolved_yes = (price >= 0.5) if (m.get("closed") and price is not None) else None
            recs.append(
                _Flow(
                    {
                        "slug": m["slug"],
                        "token_id_yes": tok,
                        "strike_usd": strike,
                        "direction": direction,
                        "direction_from_description": dir_from_desc,
                        "created_utc": created,
                        "from_date_utc": et_to_utc(from_d, (0, 0)) if from_d else None,
                        "relisted": from_d is not None,
                        "rung_usable_from_utc": _plus_hours(created, BTC_MIN_EVENT_AGE_H),
                        "volume_usd_lifetime_at_pull_DO_NOT_FILTER_ON": _vol(m.get("volume")),
                        "closed_time": closed,
                        "resolved_yes": resolved_yes,
                        "inactive_excluded": inactive,
                        "partial_window": False,
                        "partial_window_detected_by": reasons,
                    }
                )
            )
            brungs.append(
                BtcRung(
                    slug=m["slug"],
                    ladder=ladder,
                    strike=strike,
                    created=datetime.fromisoformat(created.replace("Z", "+00:00")),
                    closed_time=datetime.fromisoformat(closed.replace("Z", "+00:00"))
                    if closed
                    else None,
                    resolved_yes=resolved_yes,
                    inactive=inactive,
                )
            )
        cat = flag_created_after_touch(brungs)
        up, dip, partial_rungs, inactive_rungs = [], [], [], []
        for rec in recs:
            if rec["slug"] in cat:
                rec["partial_window_detected_by"].append("created_after_touch")
            if rec["inactive_excluded"]:
                rec["partial_window_detected_by"] = []
                inactive_rungs.append(rec)
            elif rec["partial_window_detected_by"]:
                rec["partial_window"] = True
                partial_rungs.append(rec)
            else:
                (dip if rec["direction"] == "dip" else up).append(rec)
        up.sort(key=lambda r: r["strike_usd"])
        dip.sort(key=lambda r: -r["strike_usd"])
        partial_rungs.sort(key=lambda r: (r["direction"], r["strike_usd"], r["created_utc"]))
        month_start = et_to_utc((y, mo, 1), (0, 0))
        first_usable = max(month_start, _plus_hours(g_start, BTC_MIN_EVENT_AGE_H))
        lag_h = round(
            (
                datetime.fromisoformat(g_start.replace("Z", "+00:00"))
                - datetime.fromisoformat(month_start.replace("Z", "+00:00"))
            ).total_seconds()
            / 3600,
            1,
        )
        months.append(
            {
                "month": key,
                "event_slug": e["slug"],
                "gamma_start": g_start,
                "month_start_et_midnight_utc": month_start,
                "event_open_lag_hours_after_month_start": max(lag_h, 0.0),
                "first_usable_utc": first_usable,
                "month_end_et_midnight_utc": month_end,
                "roll_utc": roll,
                "gamma_end_date_DO_NOT_ROLL_ON": _iso(
                    e["markets"][0].get("endDate") or e["endDate"]
                ),
                "resolved": bool(e["closed"]),
                "volume_usd": _vol(e.get("volume")),
                "usable": bool(up) and bool(dip),
                "exclusion_reason": None
                if (up and dip)
                else "no whole-month "
                + ("dip" if up else "reach")
                + " rungs (one-sided ladder; no signal)",
                "n_up_rungs": len(up),
                "n_dip_rungs": len(dip),
                "n_partial_window_rungs": len(partial_rungs),
                "partial_window_rungs": partial_rungs,
                "n_inactive_excluded": len(inactive_rungs),
                "inactive_excluded": inactive_rungs,
                "up_ladder": up,
                "dip_ladder": dip,
            }
        )
    for m in months:
        if not m["usable"]:
            gaps.append(
                {
                    "month": m["month"],
                    "event_slug": m["event_slug"],
                    "reason": m["exclusion_reason"],
                }
            )
    gaps.sort(key=lambda g: g["month"])
    usable_months = [m for m in months if m["usable"]]
    first_active = usable_months[0]["first_usable_utc"]
    reason_names = (
        "slug",
        "description_creation",
        "description_between",
        "created_after_touch",
    )
    per_month: dict[str, dict] = {}
    for m in months:
        pw = m["partial_window_rungs"]
        if not pw and not m["n_inactive_excluded"]:
            continue
        per_month[m["month"]] = {
            "n_partial_window": len(pw),
            **{
                f"by_{r}": sum(1 for x in pw if r in x["partial_window_detected_by"])
                for r in reason_names
            },
            "n_inactive_excluded": m["n_inactive_excluded"],
        }
    partial_summary = {
        "n_partial_window_rungs": sum(m["n_partial_window_rungs"] for m in months),
        "n_inactive_excluded": sum(m["n_inactive_excluded"] for m in months),
        "n_whole_month_rungs_kept": sum(m["n_up_rungs"] + m["n_dip_rungs"] for m in months),
        "n_months_affected": sum(1 for v in per_month.values() if v["n_partial_window"]),
        "per_month": per_month,
        "note": (
            "A rung is partial-window if any detector fires (slug -from-<date>, description 'from the "
            "creation of this market', description 'between <date>' later than the event's open day, "
            "created after its strike was already touched; A20). Detectors overlap, so by_* counts do "
            "not sum to n_partial_window. Partial rungs are used ONLY at a strike with no whole-month "
            "rung and not yet touched (select_ladder); inactive rungs never."
        ),
    }
    print(f"  BTC partial-window / inactive: {partial_summary}", file=sys.stderr)
    # Illustrative ladder-implied levels on the cached active-month snapshot.
    snap = _event("what-price-will-bitcoin-hit-in-october-2026")
    sample = None
    if snap:
        snap_open = datetime.fromisoformat(_iso(snap["startDate"]).replace("Z", "+00:00"))
        snap_rungs: list[BtcRung] = []
        snap_quotes: dict[str, float] = {}
        for m in snap["markets"]:
            q = m.get("question", "")
            tok, price = _yes(m)
            s = parse_strike(q)
            if s is None:
                continue
            closed = _iso(m.get("closedTime"))
            inactive = (not m.get("active")) and not m.get("closedTime")
            snap_rungs.append(
                BtcRung(
                    slug=m["slug"],
                    ladder=rung_direction(q, m.get("description"))[0],
                    strike=s,
                    created=datetime.fromisoformat(_iso(m["createdAt"]).replace("Z", "+00:00")),
                    closed_time=datetime.fromisoformat(closed.replace("Z", "+00:00"))
                    if closed
                    else None,
                    resolved_yes=(price >= 0.5)
                    if (m.get("closed") and price is not None)
                    else None,
                    inactive=inactive,
                    partial_reasons=tuple(
                        detect_partial_window(m["slug"], m.get("description"), 2026, snap_open)
                    ),
                )
            )
            if price is not None and not m.get("closed"):
                snap_quotes[m["slug"]] = price
        cat = flag_created_after_touch(snap_rungs)
        snap_rungs = [
            BtcRung(
                **{**r.__dict__, "partial_reasons": (*r.partial_reasons, "created_after_touch")}
            )
            if r.slug in cat
            else r
            for r in snap_rungs
        ]
        t_snap = datetime(2026, 10, 1, 23, 59, 59, tzinfo=UTC)
        upr = [(x.strike, x.p) for x in select_ladder(snap_rungs, "up", t_snap, snap_quotes, 0)]
        dpr = [(x.strike, x.p) for x in select_ladder(snap_rungs, "dip", t_snap, snap_quotes, 0)]
        (k_up, _), (k_dn, _) = (
            monotone_ladder_crossing_diag(upr, "up"),
            monotone_ladder_crossing_diag(dpr, "dip"),
        )
        sample = {
            "event_slug": snap["slug"],
            "note": (
                "Illustrative snapshot of the cached Gamma outcomePrices at pull time (NOT a price-history "
                "look): the A20 time-t rule is applied via select_ladder (touched strikes P=1, one rung per strike, "
                "whole-month before partial-window; no lifetime-volume filter); P(reach K)=0.5 log-interpolated on the up "
                "ladder and P(dip K)=0.5 on the dip ladder."
            ),
            "k_up_star_usd": round(k_up) if k_up else None,
            "k_dip_star_usd": round(k_dn) if k_dn else None,
            "ladder_level_usd": round(math.exp((math.log(k_up) + math.log(k_dn)) / 2))
            if k_up and k_dn
            else None,
            "correction": (
                "The earlier draft said spot was ~$85-87k by crossing 'reach 90k' (0.475) with 'dip 80k' "
                "(0.605). That mixed the two ladders and was wrong; the up-ladder crossing and dip-ladder "
                "crossing are separate quantities."
            ),
        }
    return {
        "id": "bitcoin_monthly_ladder",
        "priority": "primary",
        "analysis": "lead_lag_hourly_vs_spot_baseline",
        "description": (
            "Monthly 'what price will Bitcoin hit in <month>' touch-market ladders (reach $K above / "
            "dip to $K below) vs Bitcoin-linked equities. The question is whether Polymarket adds "
            "information beyond BTC-USD spot, not whether it correlates with BTC."
        ),
        "tickers": ["COIN", "MSTR", "IBIT", "BTC-USD", "XLU"],
        "ticker_roles": {
            "IBIT": "direct target (spot BTC ETF)",
            "COIN": "target",
            "MSTR": "target",
            "BTC-USD": "REQUIRED baseline: yfinance 24/7 spot; every result must be shown with and without controlling for spot returns",
            "XLU": "placebo (utilities; no BTC exposure)",
        },
        "expected_sign": {
            "COIN": "positive",
            "MSTR": "positive",
            "IBIT": "positive",
            "BTC-USD": "positive",
            "XLU": "zero (placebo)",
        },
        "rationale": (
            "A rising ladder-implied BTC level raises COIN (volume/fee revenue), MSTR (leveraged BTC "
            "treasury) and IBIT (spot ETF); IBIT is a direct target, not a control. Because BTC-USD "
            "trades 24/7 and Polymarket ladders are largely a function of spot, the informative test is "
            "incremental: do Polymarket changes predict stock returns after conditioning on BTC-USD "
            "spot returns? XLU is a placebo that should show no relationship."
        ),
        "signal": {
            "name": "btc_ladder_level_and_skew",
            "per_hour_procedure": [
                "A20/A21 RUNG SELECTION (poly_actor.pairs.select_ladder): at hour t a dip strike K is TOUCHED if any dip rung with strike <= K in that month has closed_time <= t and resolved Yes (BTC fell to the lower strike, so it fell to every higher one); an up strike K is TOUCHED if any up rung with strike >= K has closed_time <= t and resolved Yes. A touched strike has P=1 and every rung at that strike (fresh or not) is ignored. For an untouched strike use the whole-month rung if one exists at that strike AT t (created_utc <= t; a whole-month rung created after t does not suppress a partial rung); use a partial-window rung (partial_window=true, partial_window_detected_by lists slug / description_creation / description_between / created_after_touch) only if no whole-month rung exists at that strike. At most ONE rung per strike per hour (no tie-averaging of different questions; ties among eligible rungs of one kind: earliest created_utc, then slug). A rung with no CLOB quote at t is skipped at t. Rung direction comes from the resolution text (final High price = up, final Low price = dip), falling back to the question; rungs where the description overrides the question carry direction_from_description=true (A21). Rungs with active=false and no closedTime in the final snapshot (inactive_excluded; Gamma may still carry a stale outcomePrices) are excluded.",
                f"A rung counts at hour t only if its event has been open for at least {BTC_MIN_EVENT_AGE_H}h (t >= gamma_start + {BTC_MIN_EVENT_AGE_H}h; see first_usable_utc) AND the RUNG ITSELF is at least {BTC_MIN_EVENT_AGE_H}h old (t >= created_utc + {BTC_MIN_EVENT_AGE_H}h = rung_usable_from_utc; A15) AND the rung is open at t (t < closed_time or closed_time null); touched strikes follow the A20 rule above (P=1 from the touching rung's closed_time). NO lifetime-volume filter: lifetime volume is only known at pull time (look-ahead). Step 3 may add cumulative-volume-to-t (computed from trades, if available) as a time-t liquidity filter.",
                "Up-ladder: selected rungs 'reach $K' ordered by K ascending (P non-increasing). Before interpolating, apply isotonic regression (safety net only after A20) (pool-adjacent-violators, unit weights) to the hour's rung probabilities: non-increasing in strike on the up-ladder, non-decreasing in strike on the dip-ladder (A15; poly_actor.pairs.monotone_ladder_crossing). Then take the FIRST crossing of 0.5 walking away from spot and find the strike K_up* by linear interpolation of log(K) in P between the two bracketing rungs. No extrapolation; if 0.5 is not bracketed, drop the hour.",
                "Dip-ladder: rungs 'dip to $K' ordered by K descending; find K_dn* where P=0.5 the same way.",
                "ladder_level = exp((ln K_up* + ln K_dn*)/2); half_width = (ln K_up* - ln K_dn*)/2.",
                "skew = ln K_up* + ln K_dn* - 2*ln(S_t) with S_t = BTC-USD spot (positive = upside rungs further away than downside rungs relative to spot).",
            ],
            "min_event_age_hours": BTC_MIN_EVENT_AGE_H,
            "min_rung_age_hours": BTC_MIN_EVENT_AGE_H,
            "ladder_monotone_fit": "isotonic regression (PAVA) per ladder per hour before the 0.5 crossing (A15)",
            "partial_window_rungs": "recorded per month (partial_window_rungs, with detection methods) and summarised in coverage.partial_window_summary; used only per the A20 fallback rule",
            "pav_pooling_metric": "isotonic regression is only a safety net after A20 selection; step 3 logs the share of hours where PAV pools anything (poly_actor.pairs.monotone_ladder_crossing_diag)",
            "dropped_hours_metric": "step 3 reports the share of hours dropped (0.5 not bracketed, no usable rungs, month-start gap) per month and overall",
            "primary_signal": "hourly change in ln(ladder_level)",
            "why_not_nearest_0.5_reach_threshold": (
                "Touch markets pin to 1 and close within days once touched, and zombie rungs (e.g. $2 of "
                "volume) can sit near 0.5 on stale quotes; a single-rung signal is degenerate."
            ),
        },
        "roll_rule": {
            "rule": (
                "Event for calendar month M is used from the previous month's roll time to roll_utc of "
                "month M, where roll_utc = midnight America/New_York at the end of month M (-> UTC, "
                "DST-aware) + 1 hour. Never roll on gamma endDate or closed flag."
            ),
            "roll_offset_hours": 1,
            "event_time": "00:00 America/New_York on the 1st of the following month",
        },
        "splice_rule": SPLICE_RULE,
        "trading_hours_note": TRADING_HOURS_NOTE_BTC,
        "coverage": {
            "stock_window_start_utc": STOCK_WINDOW_START,
            "signal_first_active_utc": first_active,
            "signal_last_active_through": TODAY,
            "gaps": gaps,
            "partial_window_summary": partial_summary,
            "note": (
                "Months with no Gamma event, or with only one whole-month ladder (none after A21: 2024-11 and 2024-12 have both ladders once rungs titled 'reach' but resolving on a final Low price are classed as dip rungs), have no ladder signal; hours in those months are dropped (no splice "
                "across the gap). MONTH-START GAP: the new month's event opens up to ~2 days after the month "
                "begins (see event_open_lag_hours_after_month_start) and the previous event rolls out at month "
                "end + 1h, so hours between roll_utc and first_usable_utc (event open + 24h) carry no signal "
                "and are dropped; step 3 reports their share."
            ),
        },
        "event_times_utc": [
            {
                "month": m["month"],
                "event_time_utc": m["month_end_et_midnight_utc"],
                "roll_utc": m["roll_utc"],
                "event_slug": m["event_slug"],
            }
            for m in months
        ],
        "sample_ladder_snapshot": sample,
        "markets": months,
    }


# ---- CPI -------------------------------------------------------------------
def _cpi_partition(e: dict) -> dict:
    buckets = []
    for m in e["markets"]:
        tok, price = _yes(m)
        label, kind, bound, center = parse_cpi_bucket(m.get("question", ""))
        buckets.append(
            _Flow(
                {
                    "label": label,
                    "kind": kind,
                    "center": center,
                    "slug": m["slug"],
                    "token_id_yes": tok,
                    "volume_usd": _vol(m.get("volume")),
                    "final_yes_price": price,
                }
            )
        )
    return {
        "event_slug": e["slug"],
        "gamma_start": _iso(e["startDate"]),
        "gamma_end_date_DO_NOT_ROLL_ON": _iso(e["markets"][0].get("endDate") or e["endDate"]),
        "resolved": bool(e["closed"]),
        "volume_usd": _vol(e.get("volume")),
        "n_buckets": len(buckets),
        "buckets": buckets,
    }


def _bk(part: dict, label: str) -> dict:
    for b in part["buckets"]:
        if b["label"] == label:
            return b
    raise KeyError(label)


def _merged(spec: list[tuple]) -> list[dict]:
    """spec items: (part, label) take the bucket as-is; or
    ('derived', label, center, kind, plus[(part,label)], minus[(part,label)], width)."""
    out = []
    for item in spec:
        if item[0] == "derived":
            _, label, center, kind, plus, minus, width = item
            out.append(
                _Flow(
                    {
                        "label": label,
                        "kind": kind,
                        "center": center,
                        "width": width,
                        "validation_tolerance": round(width / 2, 4),
                        "derived": True,
                        "p_formula": "max(0, sum(plus) - sum(minus))",
                        "clip_binding_metric": "step 3 logs the share of hours where the max(0, ...) clip binds (sum(plus) < sum(minus))",
                        "plus_tokens": [_bk(p, lb)["token_id_yes"] for p, lb in plus],
                        "minus_tokens": [_bk(p, lb)["token_id_yes"] for p, lb in minus],
                    }
                )
            )
        else:
            part, label = item
            b = _bk(part, label)
            out.append(_Flow({**b, "from_event": part["event_slug"]}))
    return out


def build_cpi() -> dict:
    times = cpi_event_times_utc()
    months = []
    gaps = [{"month": k, "reason": r} for k, r in sorted(CPI_EXCLUDED.items())]
    prev_roll = STOCK_WINDOW_START
    for key in sorted(CPI_MONTHS):
        events = [e for e in (_event(s) for s in CPI_MONTHS[key]) if e is not None]
        if not events or all(float(e.get("volume") or 0) == 0 for e in events):
            reason = "no Gamma event" if not events else "event exists but has $0 volume"
            gaps.append(
                {
                    "month": key,
                    "tried": CPI_MONTHS[key],
                    "events_found": [e["slug"] for e in events],
                    "reason": reason,
                }
            )
            continue
        parts = [
            _cpi_partition(e) for e in sorted(events, key=lambda e: -float(e.get("volume") or 0))
        ]
        merge_note = None
        if key == "2026-01":
            a = next(p for p in parts if p["event_slug"].endswith("lower-brackets-817"))
            b = next(p for p in parts if p["event_slug"] == "january-inflation-us-annual")
            merged = _merged(
                [
                    (a, "<=2.1"),
                    (a, "2.2"),
                    (a, "2.3"),
                    (a, "2.4"),
                    (a, "2.5"),
                    (a, "2.6"),
                    (
                        "derived",
                        "2.7-2.8",
                        2.75,
                        "range",
                        [(a, ">=2.7")],
                        [(b, "2.9"), (b, "3.0"), (b, "3.1"), (b, ">=3.2")],
                        0.2,
                    ),
                    (b, "2.9"),
                    (b, "3.0"),
                    (b, "3.1"),
                    (b, ">=3.2"),
                ]
            )
            merge_note = (
                "Two companion events with overlapping partitions (lower-brackets-817 is the primary by "
                "volume). Merged into one partition: A's <=2.1..2.6, derived '2.7-2.8' = A(>=2.7) - "
                "B(2.9..>=3.2), then B's 2.9, 3.0, 3.1, >=3.2. B's '<=2.8' is dropped as redundant."
            )
        elif key == "2026-03":
            a = next(p for p in parts if p["event_slug"] == "march-inflation-us-annual")
            b = next(p for p in parts if p["event_slug"].endswith("higher-brackets"))
            merged = _merged(
                [
                    (a, "<=2.0"),
                    (a, "2.1"),
                    (a, "2.2"),
                    (a, "2.3"),
                    (a, "2.4"),
                    (a, "2.5"),
                    (a, "2.6"),
                    (a, "2.7"),
                    (b, "2.8"),
                    (b, "2.9"),
                    (b, "3.0"),
                    (b, "3.1"),
                    (b, "3.2"),
                    (b, "3.3"),
                    (b, ">=3.4"),
                ]
            )
            merge_note = (
                "Primary event march-inflation-us-annual has 9 buckets (<=2.0 ... >=2.8; it resolved in "
                "the >=2.8 edge bucket). The -higher-brackets companion (9 buckets, <=2.6 ... >=3.4, "
                "resolved 3.3) refines A's >=2.8 tail; merged partition uses A's <=2.0..2.7 and B's "
                "2.8..>=3.4 (A's >=2.8 and B's <=2.6 and 2.7 are dropped as redundant)."
            )
        else:
            merged = [
                _Flow({**b, "from_event": parts[0]["event_slug"]}) for b in parts[0]["buckets"]
            ]
        # A18: first_usable_utc for ALL CPI months (avoids a mid-month partition switch; each earlier companion is a complete partition).
        latest_open = max(p["gamma_start"] for p in parts)
        first_usable = max(prev_roll, _ceil_hour(latest_open))
        companion_drop = None
        if len(parts) > 1:
            earliest_open = min(p["gamma_start"] for p in parts)
            companion_drop = {
                "from_utc": max(prev_roll, earliest_open),
                "to_utc": first_usable,
                "reason": "not every companion event is open yet; those hours are dropped (A18)",
            }
        winners = [b for b in merged if not b.get("derived") and b.get("final_yes_price", 0) >= 0.5]
        resolved = all(p["resolved"] for p in parts)
        t = times.get(key)
        entry = {
            "month": key,
            "release_time_utc": t["release_utc"] if t else None,
            "roll_utc": t["roll_utc"] if t else None,
            "use_from_utc": prev_roll,
            "first_usable_utc": first_usable,
            "companion_dropped_hours": companion_drop,
            "resolved": resolved,
            "winning_bucket": winners[-1]["label"] if (resolved and winners) else None,
            "winning_bucket_center": winners[-1]["center"] if (resolved and winners) else None,
            "n_merged_buckets": len(merged),
            "merge_note": merge_note,
            "partitions": [{k: v for k, v in p.items() if k != "buckets"} for p in parts],
            "buckets": merged,
        }
        if t:
            prev_roll = t["roll_utc"]
        months.append(entry)
    return {
        "id": "us_cpi_inflation",
        "priority": "primary",
        "analysis": "release_day_event_study",
        "description": (
            "Monthly US CPI YoY bucket events (one per BLS release) vs long-duration Treasuries and "
            "growth equities. CPI is released 08:30 ET, outside the stock session, and the market-implied "
            "level barely moves between releases, so hourly lead-lag is not attempted: the analysis is a "
            "release-day event study comparing the pre-release implied CPI (and its change over the prior "
            "days) with the open-gap/first-hour returns."
        ),
        "tickers": ["TLT", "QQQ"],
        "expected_sign": {"TLT": "negative", "QQQ": "negative"},
        "rationale": (
            "A higher market-implied CPI raises the odds of higher-for-longer policy, lifting yields: TLT "
            "falls, and long-duration growth stocks (QQQ) fall more than the broad market."
        ),
        "signal": {
            "name": "implied_cpi_yoy",
            "formula": "sum_i(p_i * c_i) / sum_i(p_i) over the merged buckets",
            "zero_mass": "if sum_i(p_i) == 0 for an hour, drop the hour (no signal; never fill with 0)",
            "edge_bucket_centres": "boundary -/+ 0.1 (e.g. '<=2.1' -> 2.0; '>=2.7' -> 2.8)",
            "edge_mass": "edge_mass = (p of low+high edge buckets) / sum_i(p_i); flag stored per hour",
            "drop_rule": f"drop the hour if edge_mass > {CPI_EDGE_MASS_MAX}",
            "validation": (
                "For each resolved month, the implied CPI at release_time_utc - 1h must lie within one "
                "bucket width (0.1pp; for an edge winner, within 0.1pp beyond the boundary) of the winning "
                "bucket's centre in a majority of months, else the method is revised BEFORE any stock "
                "returns are examined. A derived 'range' bucket (2026-01 '2.7-2.8', width 0.2, centre 2.75) "
                "uses tolerance = half its width (0.1pp) (A19)."
            ),
            "companion_events": "merged signal for a month is defined only from first_usable_utc = the hour when every companion event is open; earlier hours are dropped (companion_dropped_hours; A18)",
            "derived_bucket_clip": "p = max(0, sum(plus) - sum(minus)); step 3 logs how often the clip binds (A19)",
        },
        "roll_rule": {
            "rule": (
                "Event for release R is used from the previous release's roll time to R's release time + "
                "1 hour. Release 08:30 America/New_York -> UTC (DST-aware). Never roll on gamma endDate "
                "or closed flag. Between events there may be gaps (an event often opens after the previous "
                "release); those hours carry no signal."
            ),
            "roll_offset_hours": 1,
            "event_time": "BLS CPI release 08:30 America/New_York",
        },
        "splice_rule": SPLICE_RULE,
        "trading_hours_note": TRADING_HOURS_NOTE_US
        + " CPI releases at 08:30 ET: the reaction is measured as the 09:30 ET opening gap and first hourly bar.",
        "coverage": {
            "stock_window_start_utc": STOCK_WINDOW_START,
            "signal_first_active_utc": min(m["partitions"][0]["gamma_start"] for m in months),
            "signal_last_active_through": TODAY,
            "gaps": gaps,
            "excluded_months": CPI_EXCLUDED,
            "note": "2026-02: event exists with $0 volume (unusable). 2025-10: no BLS release (excluded, see excluded_months).",
        },
        "event_times_utc": [
            {"month": k, **v, "event_slugs": CPI_MONTHS[k]} for k, v in sorted(times.items())
        ],
        "markets": months,
    }


SPLICE_RULE = (
    "Signals are spliced from CHANGES, never from levels. Never difference across two different events "
    "(a level in event A and a level in event B are not comparable). At a roll hour, use the NEW event's "
    "own 1-hour change (its price at roll_utc+1h minus its price at roll_utc) and set roll_hour=true so "
    "step 6 can exclude that bar. Any level series is rebuilt only by cumulating the spliced changes."
)
TRADING_HOURS_NOTE_US = (
    "Lead-lag runs only on hours when BOTH markets trade (US regular session 09:30-16:00 ET; yfinance 1h "
    "bars). Overnight/weekend Polymarket moves are compared against the next opening gap separately "
    "(close-to-open return), not folded into hourly lead-lag."
)
TRADING_HOURS_NOTE_BTC = (
    TRADING_HOURS_NOTE_US
    + " BTC-USD and Polymarket trade 24/7 but the equity targets do not: lead-lag on stock targets uses "
    "equity-session hours only, overnight BTC moves are compared against the opening gap, and every "
    "result is controlled for BTC-USD spot returns."
)

GLOBAL_CONVENTIONS = {
    "timestamps": "all tz-aware UTC, ISO-8601 with trailing Z",
    "market_level_fields_authoritative": "Gamma market-level startDate/endDate/closedTime are used over event-level (event-level can be stale, e.g. us-recession).",
    "never_roll_on": [
        "Gamma endDate (set hours BEFORE the real announcement/release)",
        "Gamma closed/closedTime state (current state = look-ahead)",
    ],
    "roll_offset_hours": 1,
    "splice_rule": SPLICE_RULE,
    "roll_hour_flag": "bar starting at roll_utc is flagged roll_hour=true; step 6 excludes it",
    "multiple_testing": "3 primary tests (Fed: TLT hourly lead-lag; BTC: IBIT incremental to spot; CPI: TLT opening gap on release days). us_recession is secondary/descriptive and outside the correction family (docs/preregistration.md)",
}


def build_pairs_yaml() -> None:
    run_time_cross_checks()
    doc = {
        "status": "draft",
        "generated": TODAY,
        "generated_by": "scripts/build_pairs.py (step 2, round 3)",
        "evidence_dir": "data/scratch/step2/",
        "preregistration": "docs/preregistration.md",
        "conventions": GLOBAL_CONVENTIONS,
        "pairs": [build_fed(), build_recession(), build_btc(), build_cpi()],
    }
    text = yaml.dump(doc, Dumper=yaml.SafeDumper, sort_keys=False, allow_unicode=True, width=110)
    text = text.replace(
        "status: draft\n",
        "status: approved  # user approved all 4 pairs 2026-10-01 after validation\n",
        1,
    )
    header = (
        "# config/pairs.yaml -- market<->ticker pair definitions for milestone 1.\n"
        "# GENERATED by scripts/build_pairs.py from data/scratch/step2/*.json. Do not hand-edit;\n"
        "# edit the script and re-run (add --refetch to refresh the Gamma dumps).\n"
        "# Rationale, rejected candidates, open risks: docs/step2_pairs.md.\n"
    )
    CONFIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_OUT.write_text(header + text, encoding="utf-8")
    print(f"wrote {CONFIG_OUT} ({len(text)} chars)", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="re-pull EVERYTHING from the live Gamma API, then build",
    )
    parser.add_argument(
        "--fetch-slugs",
        nargs="+",
        default=[],
        metavar="SLUG",
        help="fetch only these event slugs from Gamma (cache miss or refresh), then build",
    )
    args = parser.parse_args()
    REFETCH = args.refetch
    FETCH_SLUGS = set(args.fetch_slugs)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Offline by default: a cache miss raises CacheMiss instead of touching the network.
    if REFETCH:
        print("--refetch: bypassing cache, re-pulling everything", file=sys.stderr)
        refetch_all()
    build_pairs_yaml()

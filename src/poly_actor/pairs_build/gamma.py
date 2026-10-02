"""Polite, cached Polymarket Gamma client for the pairs build.

`--refetch` re-pulls everything from the live Gamma API (https://gamma-api.polymarket.com):
0.5s sleep between calls, retries with exponential backoff on 429/5xx (shared
`ingest.common.request_json_with_retry`), and every tag listing paginated to exhaustion
(`offset` steps of 100 until a short/empty page). Without it the client only reads the cache in
`data/scratch/step2/` (fully offline); a cache miss RAISES `CacheMiss` rather than silently
touching the network. `data/raw/` is never written here (raw is reserved for step 3 ingestion).
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from poly_actor.ingest.common import request_json_with_retry
from poly_actor.pairs_build.slugs import (
    BTC_MONTHS,
    CPI_MONTHS,
    FED_MEETINGS,
    RECESSION_SLUGS,
    TAGS_TO_PAGINATE,
)

GAMMA_BASE = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT_S = 20
MAX_RETRIES = 4
POLITE_SLEEP_S = 0.5
PAGE_LIMIT = 100
MAX_CALLS = 120


class CacheMiss(RuntimeError):
    """A required Gamma dump is not cached and no fetch flag was given (never hit the network silently)."""


@dataclass
class GammaClient:
    """Explicit build context: cache location, fetch flags, injected HTTP/sleep, call budget."""

    cache_dir: Path
    refetch: bool = False
    fetch_slugs: set[str] = field(default_factory=set)  # refresh only these event slugs
    get: Callable[..., Any] = requests.get
    sleep: Callable[[float], None] = time.sleep
    call_count: int = 0

    def _call(self, path: str, params: dict[str, Any]) -> Any:
        """One polite Gamma GET: call-budget cap, retry/backoff, sleep afterwards."""
        if self.call_count >= MAX_CALLS:
            raise RuntimeError(f"hit MAX_CALLS={MAX_CALLS} budget; aborting refetch")
        data, _raw = request_json_with_retry(
            self.get,
            f"{GAMMA_BASE}{path}",
            params,
            timeout=REQUEST_TIMEOUT_S,
            max_retries=MAX_RETRIES,
            sleep=self.sleep,
        )
        self.call_count += 1
        print(f"  [call {self.call_count}] GET {path} {params}", file=sys.stderr)
        self.sleep(POLITE_SLEEP_S)
        return data

    def _dump(self, name: str, data: Any) -> None:
        (self.cache_dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self, name: str) -> Any:
        p = self.cache_dir / name
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def paginate_events(self, tag_slug: str, closed: bool, max_pages: int = 6) -> list[dict]:
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
        cached = self._load(cache_name)
        if cached is not None and not self.refetch:
            return cached
        if not self.refetch:
            raise CacheMiss(f"{cache_name} not cached; rerun with --refetch")
        all_items: list[dict] = []
        offset = 0
        pages = 0
        while pages < max_pages:
            page = self._call(
                "/events",
                {
                    "tag_slug": tag_slug,
                    "closed": str(closed).lower(),
                    "limit": PAGE_LIMIT,
                    "offset": offset,
                },
            )
            self._dump(f"gamma_events_{tag_slug}_{str(closed).lower()}_offset{offset}.json", page)
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
        self._dump(cache_name, all_items)
        return all_items

    def get_event(self, slug: str) -> dict | None:
        """GET /events?slug=...  single event, full detail (incl. markets[])."""
        cache_name = f"gamma_event_{slug}_full.json"
        cached = self._load(cache_name)
        if cached is not None and not (self.refetch or slug in self.fetch_slugs):
            return cached[0] if cached else None
        if cached is None and not (self.refetch or slug in self.fetch_slugs):
            raise CacheMiss(
                f"event {slug!r} not cached ({cache_name}); rerun with --refetch "
                f"(everything) or --fetch-slugs {slug} (just this one)"
            )
        data = self._call("/events", {"slug": slug})
        self._dump(cache_name, data)
        return data[0] if data else None


def fetch_month_series(
    gamma: GammaClient, months: dict[str, list[str]], label: str
) -> dict[str, dict | None]:
    """Try each candidate slug for every month key in order; first hit wins.
    Returns {month_key: event_or_None}. A None means every candidate for
    that month was checked and came back empty -- a genuine, logged gap."""
    out: dict[str, dict | None] = {}
    for key, candidates in months.items():
        found = None
        for slug in candidates:
            e = gamma.get_event(slug)
            if e is not None:
                found = e
                break
        out[key] = found
        status = found["slug"] if found else "GAP (all candidates empty)"
        print(f"  {label} {key}: {status}", file=sys.stderr)
    return out


def fetch_all_candidates(gamma: GammaClient, months: dict[str, list[str]]) -> None:
    """Like fetch_month_series but fetches every candidate slug for months
    that list more than one (used for the CPI companion-event months, where
    we need BOTH bucket-split events, not just the first hit)."""
    for candidates in months.values():
        for slug in candidates:
            gamma.get_event(slug)


def refetch_all(gamma: GammaClient) -> None:
    print("=== paginating small tag listings ===", file=sys.stderr)
    for tag, closed in TAGS_TO_PAGINATE:
        items = gamma.paginate_events(tag, closed)
        print(f"{tag} closed={closed}: {len(items)} events", file=sys.stderr)

    print("=== Fed meetings (ground truth from paginated fed-rates list) ===", file=sys.stderr)
    for key, slug in FED_MEETINGS.items():
        gamma.get_event(slug)
        print(f"  {key}: {slug}", file=sys.stderr)

    print("=== Bitcoin monthly series ===", file=sys.stderr)
    fetch_month_series(gamma, BTC_MONTHS, "BTC")

    print("=== CPI monthly series (fetching every candidate for merge months) ===", file=sys.stderr)
    fetch_all_candidates(gamma, CPI_MONTHS)

    print("=== recession ===", file=sys.stderr)
    for slug in RECESSION_SLUGS:
        gamma.get_event(slug)

    print(
        f"=== done, {gamma.call_count} Gamma calls used (budget {MAX_CALLS}) ===", file=sys.stderr
    )

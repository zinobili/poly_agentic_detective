"""Recession pair: 'Will the US enter a recession' (calendar-year horizon) markets."""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

from poly_actor.pairs_build.consts import (
    SPLICE_RULE,
    STOCK_WINDOW_START,
    TODAY,
    TRADING_HOURS_NOTE_US,
)
from poly_actor.pairs_build.gamma import GammaClient
from poly_actor.pairs_build.util import iso, vol, yes_token


def _recession_market(gamma: GammaClient, slug: str, period: str) -> dict:
    e = gamma.get_event(slug)
    if e is None:
        raise RuntimeError(f"missing cached recession event {slug}")
    m = e["markets"][0]
    tok, price = yes_token(m)
    return {
        "period": period,
        "event_slug": e["slug"],
        "slug": m["slug"],
        "token_id_yes": tok,
        "start": iso(m.get("startDate") or e["startDate"]),
        "end": iso(m.get("endDate")),
        "closed_time": iso(m.get("closedTime")),
        "event_level_end_date_stale": iso(e["endDate"]),
        "resolved": bool(e["closed"]),
        "resolved_outcome": ("no_recession" if price < 0.5 else "recession")
        if e["closed"]
        else None,
        "current_yes_price": None if e["closed"] else price,
        "volume_usd": vol(e.get("volume")),
    }


RECESSION_STATIC: dict = {
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
}


def _recession_coverage(mk: list[dict]) -> dict:
    return {
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
    }


def build_recession(gamma: GammaClient) -> dict:
    mk = [
        _recession_market(gamma, "us-recession-in-2025", "2025"),
        _recession_market(gamma, "us-recession-by-end-of-2026", "2026"),
    ]
    return {
        **RECESSION_STATIC,
        "coverage": _recession_coverage(mk),
        "markets": mk,
    }

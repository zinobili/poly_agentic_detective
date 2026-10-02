"""Fed pair: per-FOMC-meeting rate-decision events (mutually exclusive buckets)."""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

import re
import sys

from poly_actor.pairs_build.calendars import fomc_event_times_utc
from poly_actor.pairs_build.consts import (
    SPLICE_RULE,
    STOCK_WINDOW_START,
    TODAY,
    TRADING_HOURS_NOTE_US,
)
from poly_actor.pairs_build.gamma import GammaClient
from poly_actor.pairs_build.slugs import FED_MEETINGS
from poly_actor.pairs_build.util import Flow, iso, vol, yes_token


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


def _fed_buckets(e: dict) -> tuple[dict[str, Flow], list[Flow]]:
    """Named outcome buckets by kind, plus the catch-all ('other') buckets."""
    outcomes: dict[str, Flow] = {}
    others: list[Flow] = []
    for m in e["markets"]:
        tok, price = yes_token(m)
        kind, delta, open_ended = classify_fed(m.get("question", ""))
        rec = {
            "slug": m["slug"],
            "token_id_yes": tok,
            "delta_bp": delta,
            "open_ended": open_ended,
            "volume_usd": vol(m.get("volume")),
            "final_yes_price": price,
        }
        if kind == "other":
            others.append(Flow(rec))
        else:
            outcomes[kind] = Flow(rec)
    return outcomes, others


def _fed_winner(e: dict, outcomes: dict[str, Flow], others: list[Flow]) -> str | None:
    if not e["closed"]:
        return None
    cands = {k: v["final_yes_price"] for k, v in outcomes.items()}
    cands.update({f"other_{i}": o["final_yes_price"] for i, o in enumerate(others)})
    return max(cands, key=cands.get)


def _fed_meeting(
    gamma: GammaClient, key: str, t: dict[str, str], prev_roll: str, first: bool
) -> dict:
    e = gamma.get_event(FED_MEETINGS[key])
    if e is None:
        raise RuntimeError(f"missing cached Fed event {FED_MEETINGS[key]}")
    outcomes, others = _fed_buckets(e)
    winner = _fed_winner(e, outcomes, others)
    use_from = max(prev_roll, iso(e["startDate"]))
    if iso(e["startDate"]) > prev_roll and not first:
        print(f"  WARN fed {key}: event starts after previous roll", file=sys.stderr)
    return {
        "meeting": key,
        "event_slug": e["slug"],
        "decision_time_utc": t["decision_utc"],
        "use_from_utc": use_from,
        "use_until_utc": t["roll_utc"],
        "gamma_start": iso(e["startDate"]),
        "gamma_end_date_DO_NOT_ROLL_ON": iso(e["markets"][0].get("endDate") or e["endDate"]),
        "resolved": bool(e["closed"]),
        "resolved_outcome": winner,
        "volume_usd": vol(e.get("volume")),
        "outcome_set": sorted(outcomes),
        "outcomes": dict(sorted(outcomes.items())),
        "other_outcomes": others,
    }


FED_STATIC: dict = {
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
}


def _fed_coverage(meetings: list[dict]) -> dict:
    return {
        "stock_window_start_utc": STOCK_WINDOW_START,
        "signal_first_active_utc": meetings[0]["use_from_utc"],
        "signal_last_active_through": TODAY,
        "gaps": [],
        "note": (
            "No 2025-02 or 2025-04 FOMC meetings exist (official calendar has none). Meetings "
            "before 2024-11 (e.g. fed-interest-rates-september-2024) exist on Gamma but fall "
            "outside the yfinance 1h window and are excluded."
        ),
    }


def build_fed(gamma: GammaClient) -> dict:
    times = fomc_event_times_utc()
    keys = sorted(FED_MEETINGS)
    meetings: list[dict] = []
    prev_roll = STOCK_WINDOW_START
    for key in keys:
        meetings.append(_fed_meeting(gamma, key, times[key], prev_roll, key == keys[0]))
        prev_roll = times[key]["roll_utc"]
    return {
        **FED_STATIC,
        "coverage": _fed_coverage(meetings),
        "event_times_utc": [
            {"meeting": k, **times[k], "event_slug": FED_MEETINGS[k]} for k in keys
        ],
        "markets": meetings,
    }

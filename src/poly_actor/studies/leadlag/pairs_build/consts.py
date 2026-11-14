"""Build-wide constants and the prose blocks shared by every pair in pairs.yaml."""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

TODAY = "2026-10-01"
STOCK_WINDOW_START = "2024-10-01T00:00:00Z"  # yfinance 1h ~730d lookback from TODAY (step 1)
BTC_MIN_EVENT_AGE_H = (
    24  # a BTC event's rungs count only once the event has been open this long (time-t rule)
)
CPI_EDGE_MASS_MAX = 0.10


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

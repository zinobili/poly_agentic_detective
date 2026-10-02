"""Ground-truth Gamma event slugs per series (read off paginated listings, not guessed)."""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

# Slugs: everything needed to build the 4 pairs.
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

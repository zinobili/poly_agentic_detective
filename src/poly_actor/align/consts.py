"""Named constants for alignment. All times are UTC; durations carry their unit in the name."""

from __future__ import annotations

HOUR_S = 3600
MINUTE_S = 60

# Polymarket price staleness cap. fid=60 points arrive roughly hourly (stamped a few seconds
# after the hour), so a strict "at or before" lookup is usually ~1h old (A26: no tolerance). Allow
# one missing hourly point (age up to 3h) and refuse to forward-fill beyond that.
MAX_PM_AGE_S = 3 * HOUR_S
# Same cap for the BTC-USD spot series (hourly bars, close known at bar end).
MAX_SPOT_AGE_S = 3 * HOUR_S

CLIP_LO, CLIP_HI = 0.0, 1.0

# Pre-registered drop thresholds (docs/preregistration.md, config/pairs.yaml).
FED_OTHER_MASS_MAX = 0.25
CPI_EDGE_MASS_MAX = 0.25  # A23 (user decision, coverage-based); the pre-registered 0.10 survives
CPI_EDGE_MASS_STRICT = 0.10  # as the `edge_mass_strict_ok` robustness flag
BTC_MIN_RUNG_AGE_H = 24.0

# yfinance omits the final half-hour stub bar of an early-close session; the previous bar then
# runs to the close (lessons.md: the 11:30 bar ends at 13:00).
STUB_BAR_MAX_S = 30 * MINUTE_S

# Upstream outage during which Polymarket CLOB history is missing (step 3 hand-off).
OUTAGE_WINDOWS_UTC = (("2025-10-29T09:00:00Z", "2025-10-29T14:00:00Z"),)

# Reasons a signal level is missing; "ok" means the level is valid.
OK = "ok"
NO_EVENT = "no_active_event"
BEFORE_USABLE = "before_first_usable"
MISSING_BUCKET = "missing_quote"
ZERO_MASS = "zero_mass"
OTHER_MASS = "other_mass_gt_max"
EDGE_MASS = "edge_mass_gt_max"
NO_RUNGS = "no_rungs"
NOT_BRACKETED = "not_bracketed"
START_UNAVAILABLE = "start_unavailable"

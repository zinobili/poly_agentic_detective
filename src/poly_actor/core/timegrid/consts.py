"""Generic time-grid constants shared by every study. Durations carry their unit in the name."""

from __future__ import annotations

HOUR_S = 3600
MINUTE_S = 60

CLIP_LO, CLIP_HI = 0.0, 1.0  # a probability outside this range is clipped and flagged

# yfinance omits the final half-hour stub bar of an early-close session; the previous bar then
# runs to the close (docs/lessons.md: the 11:30 bar ends at 13:00).
STUB_BAR_MAX_S = 30 * MINUTE_S

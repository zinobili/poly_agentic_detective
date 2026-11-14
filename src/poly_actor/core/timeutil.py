"""Time zone helpers shared by every study. All stored timestamps are tz-aware UTC.

`et_to_utc` converts America/New_York wall-clock times with the IANA database (DST-correct,
including the switch days). Never use date-based offset rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def et_to_utc_dt(ymd: tuple[int, int, int], hour_minute_et: tuple[int, int] = (0, 0)) -> datetime:
    """(Y, M, D) + (H, M) America/New_York wall clock -> tz-aware UTC datetime."""
    y, m, d = ymd
    hh, mm = hour_minute_et
    return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(UTC)


def et_to_utc(ymd: tuple[int, int, int], hour_minute_et: tuple[int, int] = (0, 0)) -> str:
    """Same as `et_to_utc_dt` but ISO-8601 with a trailing Z."""
    return et_to_utc_dt(ymd, hour_minute_et).isoformat().replace("+00:00", "Z")

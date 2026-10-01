"""Pure helpers for the milestone-1 market/ticker pairs (no network, no I/O).

Used by `scripts/build_pairs.py` (step 2) and reused in step 3.

Timezones: `et_to_utc` converts America/New_York wall-clock times to tz-aware UTC
using the IANA database (DST-correct, including the switch days).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_EDGE_WORD = r"(less|lower|below|more|greater|higher|above)"
_LOW_WORDS = {"less", "lower", "below"}


def et_to_utc_dt(ymd: tuple[int, int, int], hour_minute_et: tuple[int, int] = (0, 0)) -> datetime:
    """(Y, M, D) + (H, M) America/New_York wall clock -> tz-aware UTC datetime."""
    y, m, d = ymd
    hh, mm = hour_minute_et
    return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(UTC)


def et_to_utc(ymd: tuple[int, int, int], hour_minute_et: tuple[int, int] = (0, 0)) -> str:
    """Same as `et_to_utc_dt` but ISO-8601 with a trailing Z."""
    return et_to_utc_dt(ymd, hour_minute_et).isoformat().replace("+00:00", "Z")


def parse_strike(q: str) -> float | None:
    """'$90,000' -> 90000.0; '$90k' -> 90000.0; None if no dollar amount."""
    m = re.search(r"\$\s*([\d,\.]+)\s*([kK])?", q)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * 1000 if m.group(2) else v


def ladder_crossing(rungs: list[tuple[float, float]]) -> float | None:
    """rungs = [(strike, P)] ordered so P is non-increasing along the list.
    Log-interpolate the strike where P = 0.5 between the two bracketing rungs.
    No extrapolation: returns None if 0.5 is not bracketed."""
    for (k1, p1), (k2, p2) in zip(rungs, rungs[1:], strict=False):
        if p1 >= 0.5 >= p2:
            if p1 == p2:
                return math.exp((math.log(k1) + math.log(k2)) / 2)
            w = (p1 - 0.5) / (p1 - p2)
            return math.exp(math.log(k1) + w * (math.log(k2) - math.log(k1)))
    return None


def parse_cpi_bucket(q: str) -> tuple[str, str, float, float]:
    """-> (label, kind, bound, center). Edge centres = boundary -/+ 0.1.

    Recognised edge forms: '<=2.1%' / '>=3.2%' symbols, and '2.6% or less|lower|below',
    '2.9% or greater|more|higher|above' (the Dec-2024 'or greater' wording included).
    """
    m = re.search(r"([≤≥])\s*([\d.]+)\s*%", q)
    if m:
        v = float(m.group(2))
        if m.group(1) == "≤":
            return f"<={v}", "low_edge", v, round(v - 0.1, 2)
        return f">={v}", "high_edge", v, round(v + 0.1, 2)
    m = re.search(r"([\d.]+)\s*%\s*or\s*" + _EDGE_WORD, q, flags=re.IGNORECASE)
    if m:
        v = float(m.group(1))
        if m.group(2).lower() in _LOW_WORDS:
            return f"<={v}", "low_edge", v, round(v - 0.1, 2)
        return f">={v}", "high_edge", v, round(v + 0.1, 2)
    m = re.search(r"([\d.]+)\s*%", q)
    if m:
        v = float(m.group(1))
        return f"{v}", "point", v, v
    raise ValueError(f"cannot parse CPI bucket: {q!r}")

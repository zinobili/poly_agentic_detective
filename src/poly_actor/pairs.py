"""Pure helpers for the milestone-1 market/ticker pairs (no network, no I/O).

Used by `scripts/build_pairs.py` (step 2) and reused in step 3.

Timezones: `et_to_utc` converts America/New_York wall-clock times to tz-aware UTC
using the IANA database (DST-correct, including the switch days).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    No extrapolation: returns None if 0.5 is not bracketed.

    Plateau tie-break: if the first bracketing pair is itself flat at exactly 0.5
    (p1 == p2 == 0.5, e.g. a fitted plateau at 0.5 that starts the ladder or follows
    a rung whose P is also exactly 0.5), the result is the geometric midpoint of that
    pair, i.e. of the plateau's first two rungs. A plateau at 0.5 entered from a rung
    strictly above 0.5 brackets on that earlier pair instead and returns the
    plateau's first rung (w = 1)."""
    for (k1, p1), (k2, p2) in zip(rungs, rungs[1:], strict=False):
        if p1 >= 0.5 >= p2:
            if p1 == p2:
                return math.exp((math.log(k1) + math.log(k2)) / 2)
            w = (p1 - 0.5) / (p1 - p2)
            return math.exp(math.log(k1) + w * (math.log(k2) - math.log(k1)))
    return None


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]  # fmt: skip


def parse_from_date(slug: str, year: int) -> tuple[int, int, int] | None:
    """Relisted BTC rung slugs end in '-from-<month>-<day>' (optionally followed by a
    numeric de-dup suffix), e.g. 'will-bitcoin-reach-65k-in-august-2026-from-august-6'.
    -> (year, month, day), or None for a whole-month rung. `year` is the event's year."""
    m = re.search(r"-from-([a-z]+)-(\d{1,2})(?:-\d+)?$", slug)
    if not m or m.group(1) not in _MONTHS:
        return None
    return (year, _MONTHS.index(m.group(1)) + 1, int(m.group(2)))


def isotonic_fit(values: list[float], increasing: bool) -> list[float]:
    """Least-squares monotone fit (pool-adjacent-violators, unit weights).

    `values` are in the given order; the fit is non-decreasing if `increasing`
    else non-increasing along that order."""
    sign = 1.0 if increasing else -1.0
    blocks: list[list[float]] = []  # each block: [sum, count]
    for v in values:
        blocks.append([sign * v, 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += n
    out: list[float] = []
    for s, n in blocks:
        out.extend([sign * s / n] * int(n))
    return out


def monotone_ladder_crossing(rungs: list[tuple[float, float]], ladder: str) -> float | None:
    """Well-defined P=0.5 crossing of a BTC touch ladder (amendments A15, A20).

    A20: `select_ladder` yields at most one rung per strike per hour, so the tie
    averaging below is a legacy safety net for direct callers and never fires on
    selected ladders. `monotone_ladder_crossing_diag` also reports whether PAV pooled.

    rungs = [(strike, P)] in any order; `ladder` is 'up' (reach K: P must be
    non-increasing in strike) or 'dip' (dip to K: P non-decreasing in strike).
    Steps: sort by strike (equal strikes are averaged), isotonic-regress P onto
    the required monotone direction, then take the FIRST crossing of 0.5 walking
    away from spot (up: ascending strike; dip: descending strike) with the same
    log-strike interpolation as `ladder_crossing`. None if 0.5 is not bracketed.
    """
    return monotone_ladder_crossing_diag(rungs, ladder)[0]


def monotone_ladder_crossing_diag(
    rungs: list[tuple[float, float]], ladder: str
) -> tuple[float | None, bool]:
    """-> (crossing, pooled). `pooled` is True when isotonic regression changed any
    value (the ladder was non-monotone); A20 logs how often this happens."""
    if ladder not in ("up", "dip"):
        raise ValueError(f"ladder must be 'up' or 'dip', got {ladder!r}")
    by_k: dict[float, list[float]] = {}
    for k, p in rungs:
        by_k.setdefault(k, []).append(p)
    ks = sorted(by_k)
    ps = [sum(by_k[k]) / len(by_k[k]) for k in ks]
    fit = isotonic_fit(ps, increasing=(ladder == "dip"))
    pooled = any(abs(a - b) > 1e-12 for a, b in zip(ps, fit, strict=True))
    pairs = list(zip(ks, fit, strict=True))
    if ladder == "dip":
        pairs.reverse()
    return ladder_crossing(pairs), pooled


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


# ---------------------------------------------------------------------------
# A20: time-t rung selection for the BTC touch ladders (pure, no I/O)
# ---------------------------------------------------------------------------
_CREATION_RE = re.compile(r"from the creation of this market", re.IGNORECASE)
_BETWEEN_RE = re.compile(r"between\s+([A-Za-z]+)\s+(\d{1,2})\b", re.IGNORECASE)


def detect_partial_window(
    slug: str, description: str | None, year: int, event_open_utc: datetime
) -> list[str]:
    """Why a BTC rung looks like a partial-window (re-listed / fresh) rung, else [].

    Reasons: 'slug' (`-from-<month>-<day>`, A15), 'description_creation' ("from the
    creation of this market"), 'description_between' ("between <Month> <day> ..."
    where that date is later than both the 1st of its month and the ET calendar day on
    which the event opened; whole-event windows, e.g. "between February 1 ..." for an
    event opened Jan 31, or "between January 2, 2025, 11:00 ..." for an event opened
    January 2, are not partial).
    The fourth reason, 'created_after_touch', needs the whole ladder: see
    `flag_created_after_touch`."""
    reasons: list[str] = []
    if parse_from_date(slug, year) is not None:
        reasons.append("slug")
    d = description or ""
    if _CREATION_RE.search(d):
        reasons.append("description_creation")
    open_day = event_open_utc.astimezone(ET).date()
    for m in _BETWEEN_RE.finditer(d):
        name = m.group(1).lower()
        if name not in _MONTHS:
            continue
        try:
            start_day = datetime(year, _MONTHS.index(name) + 1, int(m.group(2)), tzinfo=ET).date()
        except ValueError:
            continue
        if start_day > max(open_day, start_day.replace(day=1)):
            reasons.append("description_between")
            break
    return reasons


_DIRECTION_RE = re.compile(r"final\s+\W{0,2}(high|low)\W{0,2}\s+price", re.IGNORECASE)


def direction_from_description(description: str | None) -> str | None:
    """A21: the ladder a BTC rung really belongs to, from its resolution text: a final
    "High" price -> 'up', a final "Low" price -> 'dip'. None if the text names neither
    or both (e.g. the generic 2026 text "final \"High\" or \"Low\" price ...")."""
    found = {m.group(1).lower() for m in _DIRECTION_RE.finditer(description or "")}
    if found == {"high"}:
        return "up"
    if found == {"low"}:
        return "dip"
    return None


def rung_direction(question: str, description: str | None) -> tuple[str, bool]:
    """A21: (ladder, from_description). The question says 'dip' or not (-> 'up'); the
    description's High/Low text wins when it is clear and disagrees (some 2024-11 and
    2024-12 'Will Bitcoin reach $X' rungs resolve on a final Low price of X or lower,
    i.e. they are dip rungs); from_description is True exactly in that case."""
    from_q = "dip" if "dip" in question.lower() else "up"
    from_d = direction_from_description(description)
    if from_d is not None and from_d != from_q:
        return from_d, True
    return from_q, False


@dataclass(frozen=True)
class BtcRung:
    """One BTC touch rung. `ladder` is 'up' (reach K) or 'dip' (dip to K).
    `closed_time` is the Gamma market closedTime (UTC) or None; `resolved_yes` is
    True/False once resolved, else None. `inactive` marks rungs with active=false and
    no closedTime in the final snapshot (A21: structure only, a mild look-ahead):
    excluded from everything. `partial_reasons`
    is non-empty for partial-window rungs."""

    slug: str
    ladder: str
    strike: float
    created: datetime
    closed_time: datetime | None = None
    resolved_yes: bool | None = None
    inactive: bool = False
    partial_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LadderPoint:
    """One selected (strike, P) at hour t. `source` is 'touched' (P=1, no rung
    consulted), 'whole_month' or 'partial_window' (A20)."""

    strike: float
    p: float
    source: str
    slug: str | None = None
    partial_reasons: tuple[str, ...] = ()

    @property
    def partial_window(self) -> bool:
        return self.source == "partial_window"


def _touches(o: BtcRung, k: float, ladder: str) -> bool:
    """A resolved-Yes rung `o` implies strike k was touched. Dip: BTC fell to o.strike,
    so it also fell to every HIGHER strike (o.strike <= k). Up: BTC rose to o.strike,
    so it also rose to every LOWER strike (o.strike >= k). Time is checked by the caller."""
    return o.resolved_yes is True and (o.strike <= k if ladder == "dip" else o.strike >= k)


def is_touched(rungs: Sequence[BtcRung], ladder: str, k: float, t: datetime) -> bool:
    """A20: strike k is touched at t if any live same-ladder rung that touches it
    (`_touches`) has closed_time <= t. If BTC dipped to 60k it dipped to every higher
    dip strike; if it reached 100k it reached every lower up strike."""
    return any(
        o.ladder == ladder
        and not o.inactive
        and o.closed_time is not None
        and o.closed_time <= t
        and _touches(o, k, ladder)
        for o in rungs
    )


def flag_created_after_touch(rungs: Sequence[BtcRung]) -> set[str]:
    """Slugs of rungs created when their strike was already touched (A20): some other
    live rung of the same ladder that touches the strike had closed_time <= created.
    Such a rung re-asks an already-resolved question."""
    out: set[str] = set()
    for r in rungs:
        if r.inactive:
            continue
        for o in rungs:
            if (
                o is not r
                and o.ladder == r.ladder
                and not o.inactive
                and o.closed_time is not None
                and o.closed_time <= r.created
                and _touches(o, r.strike, r.ladder)
            ):
                out.add(r.slug)
                break
    return out


def select_ladder(
    rungs: Sequence[BtcRung],
    ladder: str,
    t: datetime,
    quotes: Mapping[str, float],
    min_age_h: float = 24,
) -> list[LadderPoint]:
    """A20 time-t ladder: at most one (strike, P) per strike, sorted by strike.

    Per strike K (over live rungs of this ladder):
      1. touched at t (`is_touched`) -> P=1; every rung at K, fresh or not, is ignored.
      2. else the whole-month rung at K if one EXISTS AT t (created <= t; quoted or
         not, so the question at a strike never switches), else a partial-window
         rung. A whole-month rung created after t does not suppress a partial rung
         (A21: no look-ahead). A rung needs a CLOB quote at t (`quotes[slug]` = P of
         Yes; missing -> skipped at t), must be open (closed_time None or > t) and
         at least `min_age_h` old (created + min_age_h <= t). Among several eligible
         rungs of one kind: earliest created, then slug (never averaged).
    Uses only information stamped <= t."""
    if ladder not in ("up", "dip"):
        raise ValueError(f"ladder must be 'up' or 'dip', got {ladder!r}")
    live = [r for r in rungs if r.ladder == ladder and not r.inactive]
    out: list[LadderPoint] = []
    for k in sorted({r.strike for r in live}):
        if is_touched(rungs, ladder, k, t):
            out.append(LadderPoint(k, 1.0, "touched"))
            continue
        at_k = [r for r in live if r.strike == k]
        want_partial = not any(not r.partial_reasons and r.created <= t for r in at_k)
        cands = [
            r
            for r in at_k
            if bool(r.partial_reasons) == want_partial
            and r.slug in quotes
            and (r.closed_time is None or r.closed_time > t)
            and r.created + timedelta(hours=min_age_h) <= t
        ]
        if not cands:
            continue
        r = min(cands, key=lambda x: (x.created, x.slug))
        out.append(
            LadderPoint(
                k,
                float(quotes[r.slug]),
                "partial_window" if want_partial else "whole_month",
                r.slug,
                r.partial_reasons,
            )
        )
    return out

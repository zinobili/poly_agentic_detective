"""CPI pair: monthly US CPI YoY bucket events (one per BLS release), companion events merged."""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

from collections.abc import Callable

from poly_actor.pairs import parse_cpi_bucket
from poly_actor.pairs_build.calendars import CPI_EXCLUDED, cpi_event_times_utc
from poly_actor.pairs_build.consts import (
    CPI_EDGE_MASS_MAX,
    SPLICE_RULE,
    STOCK_WINDOW_START,
    TODAY,
    TRADING_HOURS_NOTE_US,
)
from poly_actor.pairs_build.gamma import GammaClient
from poly_actor.pairs_build.slugs import CPI_MONTHS
from poly_actor.pairs_build.util import Flow, ceil_hour, iso, vol, yes_token


def _cpi_partition(e: dict) -> dict:
    buckets = []
    for m in e["markets"]:
        tok, price = yes_token(m)
        label, kind, bound, center = parse_cpi_bucket(m.get("question", ""))
        buckets.append(
            Flow(
                {
                    "label": label,
                    "kind": kind,
                    "center": center,
                    "slug": m["slug"],
                    "token_id_yes": tok,
                    "volume_usd": vol(m.get("volume")),
                    "final_yes_price": price,
                }
            )
        )
    return {
        "event_slug": e["slug"],
        "gamma_start": iso(e["startDate"]),
        "gamma_end_date_DO_NOT_ROLL_ON": iso(e["markets"][0].get("endDate") or e["endDate"]),
        "resolved": bool(e["closed"]),
        "volume_usd": vol(e.get("volume")),
        "n_buckets": len(buckets),
        "buckets": buckets,
    }


def _bk(part: dict, label: str) -> dict:
    for b in part["buckets"]:
        if b["label"] == label:
            return b
    raise KeyError(label)


def _merged(spec: list[tuple]) -> list[dict]:
    """spec items: (part, label) take the bucket as-is; or
    ('derived', label, center, kind, plus[(part,label)], minus[(part,label)], width)."""
    out = []
    for item in spec:
        if item[0] == "derived":
            _, label, center, kind, plus, minus, width = item
            out.append(
                Flow(
                    {
                        "label": label,
                        "kind": kind,
                        "center": center,
                        "width": width,
                        "validation_tolerance": round(width / 2, 4),
                        "derived": True,
                        "p_formula": "max(0, sum(plus) - sum(minus))",
                        "clip_binding_metric": "step 3 logs the share of hours where the max(0, ...) clip binds (sum(plus) < sum(minus))",
                        "plus_tokens": [_bk(p, lb)["token_id_yes"] for p, lb in plus],
                        "minus_tokens": [_bk(p, lb)["token_id_yes"] for p, lb in minus],
                    }
                )
            )
        else:
            part, label = item
            b = _bk(part, label)
            out.append(Flow({**b, "from_event": part["event_slug"]}))
    return out


def _merge_2026_01(parts: list[dict]) -> tuple[list[dict], str]:
    a = next(p for p in parts if p["event_slug"].endswith("lower-brackets-817"))
    b = next(p for p in parts if p["event_slug"] == "january-inflation-us-annual")
    merged = _merged(
        [
            (a, "<=2.1"),
            (a, "2.2"),
            (a, "2.3"),
            (a, "2.4"),
            (a, "2.5"),
            (a, "2.6"),
            (
                "derived",
                "2.7-2.8",
                2.75,
                "range",
                [(a, ">=2.7")],
                [(b, "2.9"), (b, "3.0"), (b, "3.1"), (b, ">=3.2")],
                0.2,
            ),
            (b, "2.9"),
            (b, "3.0"),
            (b, "3.1"),
            (b, ">=3.2"),
        ]
    )
    note = (
        "Two companion events with overlapping partitions (lower-brackets-817 is the primary by "
        "volume). Merged into one partition: A's <=2.1..2.6, derived '2.7-2.8' = A(>=2.7) - "
        "B(2.9..>=3.2), then B's 2.9, 3.0, 3.1, >=3.2. B's '<=2.8' is dropped as redundant."
    )
    return merged, note


def _merge_2026_03(parts: list[dict]) -> tuple[list[dict], str]:
    a = next(p for p in parts if p["event_slug"] == "march-inflation-us-annual")
    b = next(p for p in parts if p["event_slug"].endswith("higher-brackets"))
    merged = _merged(
        [
            (a, "<=2.0"),
            (a, "2.1"),
            (a, "2.2"),
            (a, "2.3"),
            (a, "2.4"),
            (a, "2.5"),
            (a, "2.6"),
            (a, "2.7"),
            (b, "2.8"),
            (b, "2.9"),
            (b, "3.0"),
            (b, "3.1"),
            (b, "3.2"),
            (b, "3.3"),
            (b, ">=3.4"),
        ]
    )
    note = (
        "Primary event march-inflation-us-annual has 9 buckets (<=2.0 ... >=2.8; it resolved in "
        "the >=2.8 edge bucket). The -higher-brackets companion (9 buckets, <=2.6 ... >=3.4, "
        "resolved 3.3) refines A's >=2.8 tail; merged partition uses A's <=2.0..2.7 and B's "
        "2.8..>=3.4 (A's >=2.8 and B's <=2.6 and 2.7 are dropped as redundant)."
    )
    return merged, note


def _merge_single(parts: list[dict]) -> tuple[list[dict], None]:
    """Months with one event: its own partition, as-is."""
    return [Flow({**b, "from_event": parts[0]["event_slug"]}) for b in parts[0]["buckets"]], None


# Months whose companion events must be merged into one partition (reference month -> merger).
_MERGERS: dict[str, Callable[[list[dict]], tuple[list[dict], str | None]]] = {
    "2026-01": _merge_2026_01,
    "2026-03": _merge_2026_03,
}


def _companion_drop(parts: list[dict], prev_roll: str, first_usable: str) -> dict | None:
    if len(parts) <= 1:
        return None
    earliest_open = min(p["gamma_start"] for p in parts)
    return {
        "from_utc": max(prev_roll, earliest_open),
        "to_utc": first_usable,
        "reason": "not every companion event is open yet; those hours are dropped (A18)",
    }


def _cpi_month_entry(key: str, parts: list[dict], t: dict | None, prev_roll: str) -> dict:
    """The yaml record of one release month (parts: its events, largest volume first)."""
    merged, merge_note = _MERGERS.get(key, _merge_single)(parts)
    # A18: first_usable_utc for ALL CPI months (avoids a mid-month partition switch; each earlier companion is a complete partition).
    first_usable = max(prev_roll, ceil_hour(max(p["gamma_start"] for p in parts)))
    winners = [b for b in merged if not b.get("derived") and b.get("final_yes_price", 0) >= 0.5]
    resolved = all(p["resolved"] for p in parts)
    return {
        "month": key,
        "release_time_utc": t["release_utc"] if t else None,
        "roll_utc": t["roll_utc"] if t else None,
        "use_from_utc": prev_roll,
        "first_usable_utc": first_usable,
        "companion_dropped_hours": _companion_drop(parts, prev_roll, first_usable),
        "resolved": resolved,
        "winning_bucket": winners[-1]["label"] if (resolved and winners) else None,
        "winning_bucket_center": winners[-1]["center"] if (resolved and winners) else None,
        "n_merged_buckets": len(merged),
        "merge_note": merge_note,
        "partitions": [{k: v for k, v in p.items() if k != "buckets"} for p in parts],
        "buckets": merged,
    }


def _cpi_gap(key: str, events: list[dict]) -> dict:
    reason = "no Gamma event" if not events else "event exists but has $0 volume"
    return {
        "month": key,
        "tried": CPI_MONTHS[key],
        "events_found": [e["slug"] for e in events],
        "reason": reason,
    }


CPI_STATIC: dict = {
    "id": "us_cpi_inflation",
    "priority": "primary",
    "analysis": "release_day_event_study",
    "description": (
        "Monthly US CPI YoY bucket events (one per BLS release) vs long-duration Treasuries and "
        "growth equities. CPI is released 08:30 ET, outside the stock session, and the market-implied "
        "level barely moves between releases, so hourly lead-lag is not attempted: the analysis is a "
        "release-day event study comparing the pre-release implied CPI (and its change over the prior "
        "days) with the open-gap/first-hour returns."
    ),
    "tickers": ["TLT", "QQQ"],
    "expected_sign": {"TLT": "negative", "QQQ": "negative"},
    "rationale": (
        "A higher market-implied CPI raises the odds of higher-for-longer policy, lifting yields: TLT "
        "falls, and long-duration growth stocks (QQQ) fall more than the broad market."
    ),
    "signal": {
        "name": "implied_cpi_yoy",
        "formula": "sum_i(p_i * c_i) / sum_i(p_i) over the merged buckets",
        "zero_mass": "if sum_i(p_i) == 0 for an hour, drop the hour (no signal; never fill with 0)",
        "edge_bucket_centres": "boundary -/+ 0.1 (e.g. '<=2.1' -> 2.0; '>=2.7' -> 2.8)",
        "edge_mass": "edge_mass = (p of low+high edge buckets) / sum_i(p_i); flag stored per hour",
        "drop_rule": f"drop the hour if edge_mass > {CPI_EDGE_MASS_MAX}",
        "validation": (
            "For each resolved month, the implied CPI at release_time_utc - 1h must lie within one "
            "bucket width (0.1pp; for an edge winner, within 0.1pp beyond the boundary) of the winning "
            "bucket's centre in a majority of months, else the method is revised BEFORE any stock "
            "returns are examined. A derived 'range' bucket (2026-01 '2.7-2.8', width 0.2, centre 2.75) "
            "uses tolerance = half its width (0.1pp) (A19)."
        ),
        "companion_events": "merged signal for a month is defined only from first_usable_utc = the hour when every companion event is open; earlier hours are dropped (companion_dropped_hours; A18)",
        "derived_bucket_clip": "p = max(0, sum(plus) - sum(minus)); step 3 logs how often the clip binds (A19)",
    },
    "roll_rule": {
        "rule": (
            "Event for release R is used from the previous release's roll time to R's release time + "
            "1 hour. Release 08:30 America/New_York -> UTC (DST-aware). Never roll on gamma endDate "
            "or closed flag. Between events there may be gaps (an event often opens after the previous "
            "release); those hours carry no signal."
        ),
        "roll_offset_hours": 1,
        "event_time": "BLS CPI release 08:30 America/New_York",
    },
    "splice_rule": SPLICE_RULE,
    "trading_hours_note": TRADING_HOURS_NOTE_US
    + " CPI releases at 08:30 ET: the reaction is measured as the 09:30 ET opening gap and first hourly bar.",
}


def _cpi_coverage(months: list[dict], gaps: list[dict]) -> dict:
    return {
        "stock_window_start_utc": STOCK_WINDOW_START,
        "signal_first_active_utc": min(m["partitions"][0]["gamma_start"] for m in months),
        "signal_last_active_through": TODAY,
        "gaps": gaps,
        "excluded_months": CPI_EXCLUDED,
        "note": "2026-02: event exists with $0 volume (unusable). 2025-10: no BLS release (excluded, see excluded_months).",
    }


def build_cpi(gamma: GammaClient) -> dict:
    times = cpi_event_times_utc()
    months: list[dict] = []
    gaps = [{"month": k, "reason": r} for k, r in sorted(CPI_EXCLUDED.items())]
    prev_roll = STOCK_WINDOW_START
    for key in sorted(CPI_MONTHS):
        events = [e for e in (gamma.get_event(s) for s in CPI_MONTHS[key]) if e is not None]
        if not events or all(float(e.get("volume") or 0) == 0 for e in events):
            gaps.append(_cpi_gap(key, events))
            continue
        by_volume = sorted(events, key=lambda e: -float(e.get("volume") or 0))
        t = times.get(key)
        months.append(_cpi_month_entry(key, [_cpi_partition(e) for e in by_volume], t, prev_roll))
        if t:
            prev_roll = t["roll_utc"]
    return {
        **CPI_STATIC,
        "coverage": _cpi_coverage(months, gaps),
        "event_times_utc": [
            {"month": k, **v, "event_slugs": CPI_MONTHS[k]} for k, v in sorted(times.items())
        ],
        "markets": months,
    }

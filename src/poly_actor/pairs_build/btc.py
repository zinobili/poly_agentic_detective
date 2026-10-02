"""Bitcoin pair: monthly 'what price will Bitcoin hit' touch-market ladders (reach / dip).

Months are discovered by direct per-month slug lookups (BTC_MONTHS), not tag pagination: the
bitcoin tag has 1000+ events. Rung selection and the time-t rules live in `poly_actor.pairs`.
"""

# ruff: noqa: E501  (long prose strings are emitted verbatim into pairs.yaml)
from __future__ import annotations

import math
import sys
from datetime import UTC, datetime
from typing import NamedTuple

from poly_actor.pairs import (
    BtcRung,
    detect_partial_window,
    et_to_utc,
    flag_created_after_touch,
    monotone_ladder_crossing_diag,
    parse_from_date,
    parse_strike,
    rung_direction,
    select_ladder,
)
from poly_actor.pairs_build.consts import (
    BTC_MIN_EVENT_AGE_H,
    SPLICE_RULE,
    STOCK_WINDOW_START,
    TODAY,
    TRADING_HOURS_NOTE_BTC,
)
from poly_actor.pairs_build.gamma import GammaClient
from poly_actor.pairs_build.slugs import BTC_MONTHS
from poly_actor.pairs_build.util import Flow, iso, plus_hours, vol, yes_token

SNAPSHOT_SLUG = "what-price-will-bitcoin-hit-in-october-2026"
REASON_NAMES = ("slug", "description_creation", "description_between", "created_after_touch")


def _utc(z: str) -> datetime:
    return datetime.fromisoformat(z.replace("Z", "+00:00"))


class _Ladders(NamedTuple):
    up: list[Flow]
    dip: list[Flow]
    partial: list[Flow]
    inactive: list[Flow]


def _find_event(gamma: GammaClient, key: str) -> dict | None:
    """First candidate slug of the month that resolves on Gamma (None = genuine gap)."""
    for slug in BTC_MONTHS[key]:
        e = gamma.get_event(slug)
        if e is not None:
            return e
    return None


def _rung(m: dict, y: int, g_start_dt: datetime) -> tuple[Flow, BtcRung]:
    """One market -> (yaml record, BtcRung for the time-t helpers)."""
    q = m.get("question", "")
    strike = parse_strike(q)
    tok, price = yes_token(m)
    ladder, dir_from_desc = rung_direction(q, m.get("description"))
    created = iso(m["createdAt"])
    closed = iso(m.get("closedTime"))
    from_d = parse_from_date(m["slug"], y)
    # A21: inactive = active=false and no closedTime in the final snapshot
    # (structure only; a mild look-ahead). Not necessarily a duplicate.
    inactive = (not m.get("active")) and not m.get("closedTime")
    reasons = detect_partial_window(m["slug"], m.get("description"), y, g_start_dt)
    resolved_yes = (price >= 0.5) if (m.get("closed") and price is not None) else None
    rec = Flow(
        {
            "slug": m["slug"],
            "token_id_yes": tok,
            "strike_usd": strike,
            "direction": "dip" if ladder == "dip" else "reach",
            "direction_from_description": dir_from_desc,
            "created_utc": created,
            "from_date_utc": et_to_utc(from_d, (0, 0)) if from_d else None,
            "relisted": from_d is not None,
            "rung_usable_from_utc": plus_hours(created, BTC_MIN_EVENT_AGE_H),
            "volume_usd_lifetime_at_pull_DO_NOT_FILTER_ON": vol(m.get("volume")),
            "closed_time": closed,
            "resolved_yes": resolved_yes,
            "inactive_excluded": inactive,
            "partial_window": False,
            "partial_window_detected_by": reasons,
        }
    )
    brung = BtcRung(
        slug=m["slug"],
        ladder=ladder,
        strike=strike,
        created=_utc(created),
        closed_time=_utc(closed) if closed else None,
        resolved_yes=resolved_yes,
        inactive=inactive,
    )
    return rec, brung


def _split_rungs(e: dict, y: int, g_start_dt: datetime) -> _Ladders:
    """Classify an event's rungs: whole-month up / dip, partial-window, inactive (A20/A21)."""
    pairs = [_rung(m, y, g_start_dt) for m in e["markets"]]
    recs = [r for r, _ in pairs]
    cat = flag_created_after_touch([b for _, b in pairs])
    up: list[Flow] = []
    dip: list[Flow] = []
    partial: list[Flow] = []
    inactive: list[Flow] = []
    for rec in recs:
        if rec["slug"] in cat:
            rec["partial_window_detected_by"].append("created_after_touch")
        if rec["inactive_excluded"]:
            rec["partial_window_detected_by"] = []
            inactive.append(rec)
        elif rec["partial_window_detected_by"]:
            rec["partial_window"] = True
            partial.append(rec)
        else:
            (dip if rec["direction"] == "dip" else up).append(rec)
    up.sort(key=lambda r: r["strike_usd"])
    dip.sort(key=lambda r: -r["strike_usd"])
    partial.sort(key=lambda r: (r["direction"], r["strike_usd"], r["created_utc"]))
    return _Ladders(up, dip, partial, inactive)


def _month_entry(key: str, e: dict) -> dict:
    """The yaml record of one calendar month's event (rolls at ET month end + 1h)."""
    y, mo = int(key[:4]), int(key[5:])
    ny, nm = (y + 1, 1) if mo == 12 else (y, mo + 1)
    month_end = et_to_utc((ny, nm, 1), (0, 0))
    g_start = iso(e["startDate"])
    lad = _split_rungs(e, y, _utc(g_start))
    month_start = et_to_utc((y, mo, 1), (0, 0))
    lag_h = round((_utc(g_start) - _utc(month_start)).total_seconds() / 3600, 1)
    both = bool(lad.up) and bool(lad.dip)
    return {
        "month": key,
        "event_slug": e["slug"],
        "gamma_start": g_start,
        "month_start_et_midnight_utc": month_start,
        "event_open_lag_hours_after_month_start": max(lag_h, 0.0),
        "first_usable_utc": max(month_start, plus_hours(g_start, BTC_MIN_EVENT_AGE_H)),
        "month_end_et_midnight_utc": month_end,
        "roll_utc": plus_hours(month_end, 1),
        "gamma_end_date_DO_NOT_ROLL_ON": iso(e["markets"][0].get("endDate") or e["endDate"]),
        "resolved": bool(e["closed"]),
        "volume_usd": vol(e.get("volume")),
        "usable": both,
        "exclusion_reason": None
        if both
        else "no whole-month "
        + ("dip" if lad.up else "reach")
        + " rungs (one-sided ladder; no signal)",
        "n_up_rungs": len(lad.up),
        "n_dip_rungs": len(lad.dip),
        "n_partial_window_rungs": len(lad.partial),
        "partial_window_rungs": lad.partial,
        "n_inactive_excluded": len(lad.inactive),
        "inactive_excluded": lad.inactive,
        "up_ladder": lad.up,
        "dip_ladder": lad.dip,
    }


def _partial_summary(months: list[dict]) -> dict:
    per_month: dict[str, dict] = {}
    for m in months:
        pw = m["partial_window_rungs"]
        if not pw and not m["n_inactive_excluded"]:
            continue
        per_month[m["month"]] = {
            "n_partial_window": len(pw),
            **{
                f"by_{r}": sum(1 for x in pw if r in x["partial_window_detected_by"])
                for r in REASON_NAMES
            },
            "n_inactive_excluded": m["n_inactive_excluded"],
        }
    return {
        "n_partial_window_rungs": sum(m["n_partial_window_rungs"] for m in months),
        "n_inactive_excluded": sum(m["n_inactive_excluded"] for m in months),
        "n_whole_month_rungs_kept": sum(m["n_up_rungs"] + m["n_dip_rungs"] for m in months),
        "n_months_affected": sum(1 for v in per_month.values() if v["n_partial_window"]),
        "per_month": per_month,
        "note": (
            "A rung is partial-window if any detector fires (slug -from-<date>, description 'from the "
            "creation of this market', description 'between <date>' later than the event's open day, "
            "created after its strike was already touched; A20). Detectors overlap, so by_* counts do "
            "not sum to n_partial_window. Partial rungs are used ONLY at a strike with no whole-month "
            "rung and not yet touched (select_ladder); inactive rungs never."
        ),
    }


def _snapshot_rung(m: dict, snap_open: datetime) -> BtcRung | None:
    """BtcRung of one market of the cached active-month snapshot (None: no parsable strike)."""
    q = m.get("question", "")
    _tok, price = yes_token(m)
    s = parse_strike(q)
    if s is None:
        return None
    closed = iso(m.get("closedTime"))
    return BtcRung(
        slug=m["slug"],
        ladder=rung_direction(q, m.get("description"))[0],
        strike=s,
        created=_utc(iso(m["createdAt"])),
        closed_time=_utc(closed) if closed else None,
        resolved_yes=(price >= 0.5) if (m.get("closed") and price is not None) else None,
        inactive=(not m.get("active")) and not m.get("closedTime"),
        partial_reasons=tuple(
            detect_partial_window(m["slug"], m.get("description"), 2026, snap_open)
        ),
    )


def _snapshot_inputs(snap: dict) -> tuple[list[BtcRung], dict[str, float]]:
    """Snapshot rungs (with created_after_touch folded in) and open-market quotes by slug."""
    snap_open = _utc(iso(snap["startDate"]))
    rungs: list[BtcRung] = []
    quotes: dict[str, float] = {}
    for m in snap["markets"]:
        r = _snapshot_rung(m, snap_open)
        if r is None:
            continue
        rungs.append(r)
        price = yes_token(m)[1]
        if price is not None and not m.get("closed"):
            quotes[m["slug"]] = price
    cat = flag_created_after_touch(rungs)
    rungs = [
        BtcRung(**{**r.__dict__, "partial_reasons": (*r.partial_reasons, "created_after_touch")})
        if r.slug in cat
        else r
        for r in rungs
    ]
    return rungs, quotes


def _snapshot_sample(gamma: GammaClient) -> dict | None:
    """Illustrative ladder-implied levels on the cached active-month snapshot."""
    snap = gamma.get_event(SNAPSHOT_SLUG)
    if not snap:
        return None
    rungs, quotes = _snapshot_inputs(snap)
    t_snap = datetime(2026, 10, 1, 23, 59, 59, tzinfo=UTC)
    upr = [(x.strike, x.p) for x in select_ladder(rungs, "up", t_snap, quotes, 0)]
    dpr = [(x.strike, x.p) for x in select_ladder(rungs, "dip", t_snap, quotes, 0)]
    (k_up, _), (k_dn, _) = (
        monotone_ladder_crossing_diag(upr, "up"),
        monotone_ladder_crossing_diag(dpr, "dip"),
    )
    return {
        "event_slug": snap["slug"],
        "note": (
            "Illustrative snapshot of the cached Gamma outcomePrices at pull time (NOT a price-history "
            "look): the A20 time-t rule is applied via select_ladder (touched strikes P=1, one rung per strike, "
            "whole-month before partial-window; no lifetime-volume filter); P(reach K)=0.5 log-interpolated on the up "
            "ladder and P(dip K)=0.5 on the dip ladder."
        ),
        "k_up_star_usd": round(k_up) if k_up else None,
        "k_dip_star_usd": round(k_dn) if k_dn else None,
        "ladder_level_usd": round(math.exp((math.log(k_up) + math.log(k_dn)) / 2))
        if k_up and k_dn
        else None,
        "correction": (
            "The earlier draft said spot was ~$85-87k by crossing 'reach 90k' (0.475) with 'dip 80k' "
            "(0.605). That mixed the two ladders and was wrong; the up-ladder crossing and dip-ladder "
            "crossing are separate quantities."
        ),
    }


BTC_STATIC: dict = {
    "id": "bitcoin_monthly_ladder",
    "priority": "primary",
    "analysis": "lead_lag_hourly_vs_spot_baseline",
    "description": (
        "Monthly 'what price will Bitcoin hit in <month>' touch-market ladders (reach $K above / "
        "dip to $K below) vs Bitcoin-linked equities. The question is whether Polymarket adds "
        "information beyond BTC-USD spot, not whether it correlates with BTC."
    ),
    "tickers": ["COIN", "MSTR", "IBIT", "BTC-USD", "XLU"],
    "ticker_roles": {
        "IBIT": "direct target (spot BTC ETF)",
        "COIN": "target",
        "MSTR": "target",
        "BTC-USD": "REQUIRED baseline: yfinance 24/7 spot; every result must be shown with and without controlling for spot returns",
        "XLU": "placebo (utilities; no BTC exposure)",
    },
    "expected_sign": {
        "COIN": "positive",
        "MSTR": "positive",
        "IBIT": "positive",
        "BTC-USD": "positive",
        "XLU": "zero (placebo)",
    },
    "rationale": (
        "A rising ladder-implied BTC level raises COIN (volume/fee revenue), MSTR (leveraged BTC "
        "treasury) and IBIT (spot ETF); IBIT is a direct target, not a control. Because BTC-USD "
        "trades 24/7 and Polymarket ladders are largely a function of spot, the informative test is "
        "incremental: do Polymarket changes predict stock returns after conditioning on BTC-USD "
        "spot returns? XLU is a placebo that should show no relationship."
    ),
    "signal": {
        "name": "btc_ladder_level_and_skew",
        "per_hour_procedure": [
            "A20/A21 RUNG SELECTION (poly_actor.pairs.select_ladder): at hour t a dip strike K is TOUCHED if any dip rung with strike <= K in that month has closed_time <= t and resolved Yes (BTC fell to the lower strike, so it fell to every higher one); an up strike K is TOUCHED if any up rung with strike >= K has closed_time <= t and resolved Yes. A touched strike has P=1 and every rung at that strike (fresh or not) is ignored. For an untouched strike use the whole-month rung if one exists at that strike AT t (created_utc <= t; a whole-month rung created after t does not suppress a partial rung); use a partial-window rung (partial_window=true, partial_window_detected_by lists slug / description_creation / description_between / created_after_touch) only if no whole-month rung exists at that strike. At most ONE rung per strike per hour (no tie-averaging of different questions; ties among eligible rungs of one kind: earliest created_utc, then slug). A rung with no CLOB quote at t is skipped at t. Rung direction comes from the resolution text (final High price = up, final Low price = dip), falling back to the question; rungs where the description overrides the question carry direction_from_description=true (A21). Rungs with active=false and no closedTime in the final snapshot (inactive_excluded; Gamma may still carry a stale outcomePrices) are excluded.",
            f"A rung counts at hour t only if its event has been open for at least {BTC_MIN_EVENT_AGE_H}h (t >= gamma_start + {BTC_MIN_EVENT_AGE_H}h; see first_usable_utc) AND the RUNG ITSELF is at least {BTC_MIN_EVENT_AGE_H}h old (t >= created_utc + {BTC_MIN_EVENT_AGE_H}h = rung_usable_from_utc; A15) AND the rung is open at t (t < closed_time or closed_time null); touched strikes follow the A20 rule above (P=1 from the touching rung's closed_time). NO lifetime-volume filter: lifetime volume is only known at pull time (look-ahead). Step 3 may add cumulative-volume-to-t (computed from trades, if available) as a time-t liquidity filter.",
            "Up-ladder: selected rungs 'reach $K' ordered by K ascending (P non-increasing). Before interpolating, apply isotonic regression (safety net only after A20) (pool-adjacent-violators, unit weights) to the hour's rung probabilities: non-increasing in strike on the up-ladder, non-decreasing in strike on the dip-ladder (A15; poly_actor.pairs.monotone_ladder_crossing). Then take the FIRST crossing of 0.5 walking away from spot and find the strike K_up* by linear interpolation of log(K) in P between the two bracketing rungs. No extrapolation; if 0.5 is not bracketed, drop the hour.",
            "Dip-ladder: rungs 'dip to $K' ordered by K descending; find K_dn* where P=0.5 the same way.",
            "ladder_level = exp((ln K_up* + ln K_dn*)/2); half_width = (ln K_up* - ln K_dn*)/2.",
            "skew = ln K_up* + ln K_dn* - 2*ln(S_t) with S_t = BTC-USD spot (positive = upside rungs further away than downside rungs relative to spot).",
        ],
        "min_event_age_hours": BTC_MIN_EVENT_AGE_H,
        "min_rung_age_hours": BTC_MIN_EVENT_AGE_H,
        "ladder_monotone_fit": "isotonic regression (PAVA) per ladder per hour before the 0.5 crossing (A15)",
        "partial_window_rungs": "recorded per month (partial_window_rungs, with detection methods) and summarised in coverage.partial_window_summary; used only per the A20 fallback rule",
        "pav_pooling_metric": "isotonic regression is only a safety net after A20 selection; step 3 logs the share of hours where PAV pools anything (poly_actor.pairs.monotone_ladder_crossing_diag)",
        "dropped_hours_metric": "step 3 reports the share of hours dropped (0.5 not bracketed, no usable rungs, month-start gap) per month and overall",
        "primary_signal": "hourly change in ln(ladder_level)",
        "why_not_nearest_0.5_reach_threshold": (
            "Touch markets pin to 1 and close within days once touched, and zombie rungs (e.g. $2 of "
            "volume) can sit near 0.5 on stale quotes; a single-rung signal is degenerate."
        ),
    },
    "roll_rule": {
        "rule": (
            "Event for calendar month M is used from the previous month's roll time to roll_utc of "
            "month M, where roll_utc = midnight America/New_York at the end of month M (-> UTC, "
            "DST-aware) + 1 hour. Never roll on gamma endDate or closed flag."
        ),
        "roll_offset_hours": 1,
        "event_time": "00:00 America/New_York on the 1st of the following month",
    },
    "splice_rule": SPLICE_RULE,
    "trading_hours_note": TRADING_HOURS_NOTE_BTC,
}


def _btc_coverage(first_active: str, gaps: list[dict], partial_summary: dict) -> dict:
    return {
        "stock_window_start_utc": STOCK_WINDOW_START,
        "signal_first_active_utc": first_active,
        "signal_last_active_through": TODAY,
        "gaps": gaps,
        "partial_window_summary": partial_summary,
        "note": (
            "Months with no Gamma event, or with only one whole-month ladder (none after A21: 2024-11 and 2024-12 have both ladders once rungs titled 'reach' but resolving on a final Low price are classed as dip rungs), have no ladder signal; hours in those months are dropped (no splice "
            "across the gap). MONTH-START GAP: the new month's event opens up to ~2 days after the month "
            "begins (see event_open_lag_hours_after_month_start) and the previous event rolls out at month "
            "end + 1h, so hours between roll_utc and first_usable_utc (event open + 24h) carry no signal "
            "and are dropped; step 3 reports their share."
        ),
    }


def build_btc(gamma: GammaClient) -> dict:
    months: list[dict] = []
    gaps: list[dict] = []
    for key in sorted(BTC_MONTHS):
        e = _find_event(gamma, key)
        if e is None:
            reason = "no Gamma event under any candidate slug"
            gaps.append({"month": key, "tried": BTC_MONTHS[key], "reason": reason})
        else:
            months.append(_month_entry(key, e))
    gaps.extend(
        {"month": m["month"], "event_slug": m["event_slug"], "reason": m["exclusion_reason"]}
        for m in months
        if not m["usable"]
    )
    gaps.sort(key=lambda g: g["month"])
    first_active = next(m for m in months if m["usable"])["first_usable_utc"]
    partial_summary = _partial_summary(months)
    print(f"  BTC partial-window / inactive: {partial_summary}", file=sys.stderr)
    return {
        **BTC_STATIC,
        "coverage": _btc_coverage(first_active, gaps, partial_summary),
        "event_times_utc": [
            {
                "month": m["month"],
                "event_time_utc": m["month_end_et_midnight_utc"],
                "roll_utc": m["roll_utc"],
                "event_slug": m["event_slug"],
            }
            for m in months
        ],
        "sample_ladder_snapshot": _snapshot_sample(gamma),
        "markets": months,
    }

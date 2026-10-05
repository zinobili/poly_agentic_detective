"""Evaluate one event's signal level at arbitrary instants from a `PriceBook`.

Every evaluator takes an `Event`, price books and epoch-second instants, and returns a frame
with one row per instant: `level` (NaN when dropped), `reason` ("ok" or why), `age_s` (largest
age of any quote used), `clipped` (a raw price above 1 was clipped) plus pair-specific
diagnostics. Quotes are as-of lookups (<= instant) so a level never uses later data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from poly_actor.align import signals
from poly_actor.align.consts import (
    BEFORE_USABLE,
    BTC_MIN_RUNG_AGE_H,
    CPI_EDGE_MASS_STRICT,
    MISSING_BUCKET,
    NO_RUNGS,
    NOT_BRACKETED,
    OK,
)
from poly_actor.align.events import BtcSpec, Event
from poly_actor.align.prices import PriceBook, Quotes
from poly_actor.pairs import monotone_ladder_crossing_diag, select_ladder

Evaluator = Callable[[Event, PriceBook, PriceBook, np.ndarray], pd.DataFrame]


def _max_age(quotes: list[Quotes], n: int) -> np.ndarray:
    """Largest quote age per instant (NaN when no quote is available at all)."""
    if not quotes:
        return np.full(n, np.nan)
    age = np.column_stack([q.age_s for q in quotes])
    out = np.nanmax(np.where(np.isnan(age), -np.inf, age), axis=1)
    return np.where(np.isfinite(out), out, np.nan)


def _any_clipped(quotes: list[Quotes], n: int) -> np.ndarray:
    if not quotes:
        return np.zeros(n, dtype=bool)
    return np.column_stack([q.clipped for q in quotes]).any(axis=1)


def _any_tolerance(quotes: list[Quotes], n: int) -> np.ndarray:
    if not quotes:
        return np.zeros(n, dtype=bool)
    return np.column_stack([q.used_tolerance for q in quotes]).any(axis=1)


def _gate_usable(frame: pd.DataFrame, event: Event, instants: np.ndarray) -> pd.DataFrame:
    """Hours before the event's first usable instant carry no signal."""
    early = instants < event.first_usable_s
    frame.loc[early, "level"] = np.nan
    frame.loc[early, "reason"] = BEFORE_USABLE
    return frame


def evaluate_fed(
    event: Event, book: PriceBook, spot: PriceBook, instants: np.ndarray
) -> pd.DataFrame:
    """fed_expected_change_bp = sum(p_i*delta_i)/sum(p_i); catch-all mass in `other_mass`."""
    n = len(instants)
    named = [book.asof(b.token, instants) for b in event.fed_buckets]
    other = [book.asof(t, instants) for t in event.fed_other_tokens]
    p = np.column_stack([q.p for q in named]) if named else np.empty((n, 0))
    deltas = np.array([b.delta_bp for b in event.fed_buckets], dtype="float64")
    other_p = np.column_stack([q.p for q in other]).sum(axis=1) if other else None
    level, other_mass, reason = signals.fed_expected_change(p, deltas, other_p)
    frame = pd.DataFrame(
        {
            "level": level,
            "reason": reason,
            "age_s": _max_age(named + other, n),
            "clipped": _any_clipped(named + other, n),
            "used_tol": _any_tolerance(named + other, n),
            "other_mass": other_mass,
        }
    )
    return _gate_usable(frame, event, instants)


def evaluate_cpi(
    event: Event, book: PriceBook, spot: PriceBook, instants: np.ndarray
) -> pd.DataFrame:
    """implied_cpi_yoy over merged buckets; derived buckets use max(0, sum(plus) - sum(minus))."""
    n = len(instants)
    quotes: list[Quotes] = []
    columns: list[np.ndarray] = []
    clip_binding = np.zeros(n, dtype=bool)
    has_derived = False
    for bucket in event.cpi_buckets:
        if bucket.token is not None:
            q = book.asof(bucket.token, instants)
            quotes.append(q)
            columns.append(q.p)
            continue
        has_derived = True
        plus = [book.asof(t, instants) for t in bucket.plus_tokens]
        minus = [book.asof(t, instants) for t in bucket.minus_tokens]
        quotes += plus + minus
        p_plus = np.column_stack([q.p for q in plus]) if plus else np.zeros((n, 0))
        p_minus = np.column_stack([q.p for q in minus]) if minus else np.zeros((n, 0))
        value, binding = signals.derived_bucket(p_plus, p_minus)
        incomplete = np.isnan(p_plus).any(axis=1) | np.isnan(p_minus).any(axis=1)
        columns.append(np.where(incomplete, np.nan, value))
        clip_binding |= binding & ~incomplete
    p = np.column_stack(columns)
    centers = np.array([b.center for b in event.cpi_buckets], dtype="float64")
    is_edge = np.array([b.is_edge for b in event.cpi_buckets], dtype=bool)
    level, edge_mass, reason = signals.cpi_implied(p, centers, is_edge)
    frame = pd.DataFrame(
        {
            "level": level,
            "reason": reason,
            "age_s": _max_age(quotes, n),
            "clipped": _any_clipped(quotes, n),
            "used_tol": _any_tolerance(quotes, n),
            "edge_mass_strict_ok": edge_mass <= CPI_EDGE_MASS_STRICT,
            "edge_mass": edge_mass,
            "cpi_has_derived": np.full(n, has_derived),
            "cpi_clip_binding": clip_binding,
        }
    )
    return _gate_usable(frame, event, instants)


def evaluate_recession(
    event: Event, book: PriceBook, spot: PriceBook, instants: np.ndarray
) -> pd.DataFrame:
    """recession_p_yes of the active market (level is the probability itself)."""
    q = book.asof(event.token, instants)
    frame = pd.DataFrame(
        {
            "level": q.p,
            "reason": np.where(np.isnan(q.p), MISSING_BUCKET, OK),
            "age_s": q.age_s,
            "clipped": q.clipped,
            "used_tol": q.used_tolerance,
        }
    )
    return _gate_usable(frame, event, instants)


@dataclass
class _BtcHour:
    """Ladder result of one instant (K_up*/K_dn* are NaN when the hour is dropped)."""

    reason: str = OK
    k_up: float = np.nan
    k_dn: float = np.nan
    pooled: bool = False
    n_up: int = 0
    n_dip: int = 0
    n_partial: int = 0


def _btc_hour(spec: BtcSpec, t: datetime, live: Mapping[str, float]) -> _BtcHour:
    """A20/A21 selection at time t from the fresh rung quotes `live` (slug -> P of Yes):
    `select_ladder`, isotonic safety net, then the first 0.5 crossing on each ladder."""
    ladders = {
        side: select_ladder(spec.rungs, side, t, live, BTC_MIN_RUNG_AGE_H) for side in ("up", "dip")
    }
    hour = _BtcHour(
        n_up=len(ladders["up"]),
        n_dip=len(ladders["dip"]),
        n_partial=sum(p.partial_window for pts in ladders.values() for p in pts),
    )
    if not ladders["up"] or not ladders["dip"]:
        hour.reason = NO_RUNGS
        return hour
    crossings = {}
    for side, pts in ladders.items():
        crossings[side], pooled = monotone_ladder_crossing_diag(
            [(p.strike, p.p) for p in pts], side
        )
        hour.pooled |= pooled
    if crossings["up"] is None or crossings["dip"] is None:
        hour.reason = NOT_BRACKETED
        return hour
    hour.k_up, hour.k_dn = crossings["up"], crossings["dip"]
    return hour


def evaluate_btc(
    event: Event, book: PriceBook, spot: PriceBook, instants: np.ndarray
) -> pd.DataFrame:
    """ln(ladder_level) of the month's rung ladders at each instant (see `_btc_hour`).

    `level` is ln(ladder_level) = (ln K_up* + ln K_dn*) / 2, so its hourly change is the
    pre-registered primary signal. Also K_up*, K_dn*, half_width, skew vs the BTC-USD spot
    (as-of), `pav_pooled` and how many strikes came from partial-window rungs."""
    n = len(instants)
    spec = event.btc
    quotes = {
        r.slug: book.asof(spec.token_by_slug[r.slug], instants)
        for r in spec.rungs
        if not r.inactive
    }
    spot_p = spot.asof("BTC-USD", instants).p
    hours: dict[int, _BtcHour] = {}
    age = np.full(n, np.nan)
    clipped = np.zeros(n, dtype=bool)
    used_tol = np.zeros(n, dtype=bool)
    reason = np.full(n, BEFORE_USABLE, dtype=object)
    for i in np.flatnonzero(instants >= event.first_usable_s):
        t = datetime.fromtimestamp(int(instants[i]), UTC)
        live = [s for s, q in quotes.items() if not np.isnan(q.p[i])]
        age[i] = max((quotes[s].age_s[i] for s in live), default=np.nan)
        clipped[i] = any(quotes[s].clipped[i] for s in live)
        used_tol[i] = any(quotes[s].used_tolerance[i] for s in live)
        hours[i] = _btc_hour(spec, t, {s: float(quotes[s].p[i]) for s in live})
        reason[i] = hours[i].reason
    frame = pd.DataFrame(
        {
            "k_up": _column(hours, n, "k_up", np.nan),
            "k_dn": _column(hours, n, "k_dn", np.nan),
            "pav_pooled": _column(hours, n, "pooled", False, dtype=bool),
            "n_up": _column(hours, n, "n_up", 0, dtype="int64"),
            "n_dip": _column(hours, n, "n_dip", 0, dtype="int64"),
            "n_partial": _column(hours, n, "n_partial", 0, dtype="int64"),
            "btc_spot": spot_p,
            "age_s": age,
            "clipped": clipped,
            "used_tol": used_tol,
            "reason": reason,
        }
    )
    frame["level"], frame["half_width"] = signals.log_ladder_level(frame["k_up"], frame["k_dn"])
    frame["skew"] = signals.skew(frame["k_up"], frame["k_dn"], frame["btc_spot"])
    return frame


def _column(hours: Mapping[int, _BtcHour], n: int, attr: str, fill, dtype=float) -> np.ndarray:
    out = np.full(n, fill, dtype=dtype)
    for i, hour in hours.items():
        out[i] = getattr(hour, attr)
    return out


EVALUATORS: dict[str, Evaluator] = {
    "fed_decision": evaluate_fed,
    "us_cpi_inflation": evaluate_cpi,
    "bitcoin_monthly_ladder": evaluate_btc,
    "us_recession": evaluate_recession,
}

"""Events (one market family per official event) and their active windows, from pairs.yaml.

Active event at the END instant x of a row window (start, end]: use_from < x <= use_until
(half-open on the left), where use_until is the roll time = official event time + 1h
(never Gamma endDate or the closed flag). A row ending exactly at the roll time therefore
still belongs to the OLD event, and the next row (starting at the roll) is the first row of
the new one (roll_hour). Event times come from config/pairs.yaml, which hardcodes
federalreserve.gov / bls.gov / exchange_calendars dates.
All instants are epoch seconds (UTC).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from poly_actor.ingest.common import to_epoch
from poly_actor.pairs import BtcRung, load_btc_rungs

HOUR_S = 3600
FAR_FUTURE_S = to_epoch("2100-01-01T00:00:00Z")


@dataclass(frozen=True)
class FedBucket:
    token: str
    delta_bp: float


@dataclass(frozen=True)
class CpiBucket:
    """A merged CPI bucket. Derived buckets have plus/minus tokens instead of one token."""

    label: str
    kind: str  # point | range | low_edge | high_edge
    center: float
    token: str | None = None
    plus_tokens: tuple[str, ...] = ()
    minus_tokens: tuple[str, ...] = ()

    @property
    def is_edge(self) -> bool:
        return self.kind in ("low_edge", "high_edge")


@dataclass(frozen=True)
class BtcSpec:
    rungs: tuple[BtcRung, ...]
    token_by_slug: Mapping[str, str]


@dataclass(frozen=True)
class Event:
    """One event's market family and the window during which it is the signal source."""

    id: str
    use_from_s: int
    use_until_s: int
    first_usable_s: int
    event_time_s: int | None
    fed_buckets: tuple[FedBucket, ...] = ()
    fed_other_tokens: tuple[str, ...] = ()
    cpi_buckets: tuple[CpiBucket, ...] = ()
    btc: BtcSpec | None = None
    token: str | None = None  # single-token markets (recession)


def fed_events(pair: Mapping) -> list[Event]:
    out = []
    for m in pair["markets"]:
        buckets = tuple(
            FedBucket(o["token_id_yes"], float(o["delta_bp"])) for o in m["outcomes"].values()
        )
        other = tuple(o["token_id_yes"] for o in m.get("other_outcomes") or [])
        use_from = to_epoch(m["use_from_utc"])
        out.append(
            Event(
                id=m["meeting"],
                use_from_s=use_from,
                use_until_s=to_epoch(m["use_until_utc"]),
                first_usable_s=to_epoch(m["gamma_start"]),  # open long before it becomes active
                event_time_s=to_epoch(m["decision_time_utc"]),
                fed_buckets=buckets,
                fed_other_tokens=other,
            )
        )
    return _sorted_checked(out)


def cpi_events(pair: Mapping) -> list[Event]:
    out = []
    for m in pair["markets"]:
        buckets = []
        for b in m["buckets"]:
            buckets.append(
                CpiBucket(
                    label=b["label"],
                    kind=b["kind"],
                    center=float(b["center"]),
                    token=b.get("token_id_yes"),
                    plus_tokens=tuple(b.get("plus_tokens") or ()),
                    minus_tokens=tuple(b.get("minus_tokens") or ()),
                )
            )
        out.append(
            Event(
                id=m["month"],
                use_from_s=to_epoch(m["use_from_utc"]),
                use_until_s=to_epoch(m["roll_utc"]),
                first_usable_s=to_epoch(m["first_usable_utc"]),
                event_time_s=to_epoch(m["release_time_utc"]),
                cpi_buckets=tuple(buckets),
            )
        )
    return _sorted_checked(out)


def btc_events(pair: Mapping) -> list[Event]:
    out = []
    for m in pair["markets"]:
        if not m.get("usable", True):
            continue
        token_by_slug = {
            r["slug"]: r["token_id_yes"]
            for key in ("up_ladder", "dip_ladder", "partial_window_rungs")
            for r in m.get(key) or []
        }
        out.append(
            Event(
                id=m["month"],
                use_from_s=to_epoch(m["month_start_et_midnight_utc"]) + HOUR_S,
                use_until_s=to_epoch(m["roll_utc"]),
                first_usable_s=to_epoch(m["first_usable_utc"]),
                event_time_s=to_epoch(m["month_end_et_midnight_utc"]),
                btc=BtcSpec(tuple(load_btc_rungs(m)), token_by_slug),
            )
        )
    return _sorted_checked(out)


def recession_events(pair: Mapping) -> list[Event]:
    roll = to_epoch(pair["roll_rule"]["roll_utc"])
    first, second = sorted(pair["markets"], key=lambda m: to_epoch(m["start"]))
    start_first, start_second = to_epoch(first["start"]), to_epoch(second["start"])
    return _sorted_checked(
        [
            Event(
                first["period"], start_first, roll, start_first, None, token=first["token_id_yes"]
            ),
            Event(
                second["period"],
                roll,
                to_epoch(second.get("closed_time") or second["end"]),
                start_second,
                None,
                token=second["token_id_yes"],
            ),
        ]
    )


def _sorted_checked(events: list[Event]) -> list[Event]:
    """Sort by use_from and refuse overlapping windows (two active events would be ambiguous)."""
    events = sorted(events, key=lambda e: e.use_from_s)
    for a, b in zip(events, events[1:], strict=False):
        if a.use_until_s > b.use_from_s:
            raise ValueError(f"events {a.id} and {b.id} overlap in their use windows")
    return events


def active_index(events: list[Event], instants: np.ndarray) -> np.ndarray:
    """Index of the event active at each row-END instant (-1 if none): use_from < x <= use_until."""
    if not events:
        return np.full(len(instants), -1, dtype="int64")
    starts = np.array([e.use_from_s for e in events], dtype="int64")
    ends = np.array([e.use_until_s for e in events], dtype="int64")
    idx = np.searchsorted(starts, instants, side="left") - 1
    inside = (idx >= 0) & (instants <= ends[np.maximum(idx, 0)])
    return np.where(inside, idx, -1)


def roll_times(events: list[Event]) -> np.ndarray:
    """Instants at which the active event changes (each event's start except the first)."""
    return np.array([e.use_from_s for e in events[1:]], dtype="int64")

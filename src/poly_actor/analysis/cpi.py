"""CPI release-day event study (A27 rule 4, prereg Pair 3).

Pre-release level: the PM as-of value at exactly release - 60 min, evaluated from the price book
(not the hourly grid row). The 5-day level: the as-of value at the same ET clock time 5 XNYS
sessions earlier, with the same `event_id`. Either invalid -> the release is dropped (no search
for a nearby valid hour). Validation (before any return is read): denominator = resolved months
with a valid release - 60 min level; pass = strictly more than half within 0.1 pp of the winning
bucket centre AND at least 8 valid months. The test runs if at least 10 releases are usable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from poly_actor.align.consts import OK
from poly_actor.align.evaluate import Evaluator
from poly_actor.align.events import Event, active_index
from poly_actor.align.prices import PriceBook
from poly_actor.analysis import models

ET = ZoneInfo("America/New_York")
PRE_RELEASE_S = 3600
SESSIONS_BACK = 5
VALIDATION_TOL_PP = 0.1
VALIDATION_MIN_VALID = 8
MIN_USABLE = 10  # A27 rule 4 (user decision: 10)
CLOSE_PROXY_P = 0.10
PLACEBO_SETS = 1000
PLACEBO_SEED = 20261006
PLACEBO_EXCLUDE_SESSIONS = 2  # +/- sessions around CPI releases and FOMC days
PLACEBO_PCTL = 0.10
EPS = 1e-9


@dataclass(frozen=True)
class Release:
    event_id: str
    release_s: int
    resolved: bool
    winning_center: float | None


def releases(pair: Mapping) -> list[Release]:
    from poly_actor.ingest.common import to_epoch

    return [
        Release(
            m["month"],
            to_epoch(m["release_time_utc"]),
            bool(m.get("resolved")),
            m.get("winning_bucket_center"),
        )
        for m in pair["markets"]
    ]


def et_date(epoch_s: int) -> date:
    return datetime.fromtimestamp(epoch_s, ET).date()


def same_clock(epoch_s: int, day: date) -> int:
    """The instant with the ET wall-clock time of `epoch_s` on `day` (DST-safe via zoneinfo)."""
    clock = datetime.fromtimestamp(epoch_s, ET).timetz().replace(tzinfo=None)
    return int(datetime.combine(day, time(clock.hour, clock.minute, clock.second), ET).timestamp())


def sessions_back(sessions: list[date], day: date, k: int) -> date | None:
    """The XNYS session k sessions before `day` (which must itself be a session)."""
    i = sessions.index(day)
    return sessions[i - k] if i - k >= 0 else None


def evaluate_at(
    events: list[Event],
    evaluator: Evaluator,
    book: PriceBook,
    spot: PriceBook,
    instants: np.ndarray,
    event_ids: list[str],
) -> pd.DataFrame:
    """Level of the named event at each instant. Invalid (NaN level, reason given) when the
    named event is not the active one at that instant."""
    by_id = {e.id: i for i, e in enumerate(events)}
    active = active_index(events, instants)
    out = []
    for inst, eid, act in zip(instants, event_ids, active, strict=True):
        i = by_id[eid]
        if act != i:
            out.append({"level": np.nan, "reason": "other_event_active", "age_s": np.nan})
            continue
        res = evaluator(events[i], book, spot, np.array([inst], dtype="int64")).iloc[0]
        out.append({"level": res["level"], "reason": res["reason"], "age_s": res["age_s"]})
    return pd.DataFrame(out)


def release_table(
    rels: list[Release],
    events: list[Event],
    evaluator: Evaluator,
    book: PriceBook,
    spot: PriceBook,
    sessions: list[date],
    closes: Mapping[date, int],
) -> pd.DataFrame:
    """One row per release: instants, levels and validity at release - 60 min, 5 sessions
    earlier, and at the prior session close (CPI sensitivity proxy)."""
    rows = []
    for r in rels:
        day = et_date(r.release_s)
        if day not in sessions:
            raise ValueError(f"release {r.event_id} is not on an XNYS session ({day})")
        t1 = r.release_s - PRE_RELEASE_S
        back = sessions_back(sessions, day, SESSIONS_BACK)
        prior = sessions_back(sessions, day, 1)
        rows.append(
            {
                "event_id": r.event_id,
                "session": day,
                "release_s": r.release_s,
                "t1": t1,
                "t0": same_clock(t1, back) if back else -1,
                "t_close": closes[prior] if prior else -1,
                "resolved": r.resolved,
                "winning_center": r.winning_center,
            }
        )
    tab = pd.DataFrame(rows)
    for col, tag in (("t1", "1"), ("t0", "0"), ("t_close", "c")):
        lv = evaluate_at(
            events, evaluator, book, spot, tab[col].to_numpy("int64"), tab["event_id"].tolist()
        )
        tab[f"level{tag}"] = lv["level"].to_numpy()
        tab[f"reason{tag}"] = lv["reason"].to_numpy()
        tab[f"age{tag}"] = lv["age_s"].to_numpy()
    tab["valid1"] = tab["reason1"] == OK
    tab["valid0"] = tab["reason0"] == OK
    tab["usable"] = tab["valid1"] & tab["valid0"]
    tab["proxy"] = np.where(tab["usable"], tab["level1"] - tab["level0"], np.nan)
    tab["close_proxy"] = np.where(
        tab["usable"] & (tab["reasonc"] == OK), tab["levelc"] - tab["level0"], np.nan
    )
    return tab


@dataclass(frozen=True)
class Validation:
    n_valid: int
    n_within: int
    passed: bool
    months: list[dict]


def validate(tab: pd.DataFrame) -> Validation:
    """Prereg Pair 3 method validation with the A27 denominator."""
    sel = tab[tab["resolved"] & tab["valid1"] & tab["winning_center"].notna()]
    err = (sel["level1"] - sel["winning_center"]).abs()
    within = err <= VALIDATION_TOL_PP + EPS
    n_valid, n_within = len(sel), int(within.sum())
    months = [
        {"event_id": e, "implied": float(lv), "winning_center": float(c), "within": bool(w)}
        for e, lv, c, w in zip(
            sel["event_id"], sel["level1"], sel["winning_center"], within, strict=True
        )
    ]
    passed = n_within > n_valid / 2 and n_valid >= VALIDATION_MIN_VALID
    return Validation(n_valid, n_within, passed, months)


@dataclass(frozen=True)
class SpearmanOut:
    n: int
    rho: float
    p_one: float  # H1: rho < 0
    p_two: float
    method: str
    ci_low: float
    ci_high: float
    boot_low: float
    boot_high: float
    sign_negative: int
    sign_n: int
    sign_p: float

    def as_dict(self) -> dict:
        return {k: (float(v) if isinstance(v, float) else v) for k, v in self.__dict__.items()}

    @property
    def upper_r(self) -> float:
        """One-sided 95% bound of the H1-direction effect (-rho), i.e. minus the lower end of
        the two-sided 90% Fisher interval."""
        return -self.ci_low

    @property
    def lower_r(self) -> float:
        return -self.ci_high


def spearman_test(proxy: np.ndarray, outcome: np.ndarray) -> SpearmanOut:
    """One-sided Spearman (rho < 0) with an exact permutation p, Fisher-z and bootstrap 90%
    intervals and the sign-test companion (A27 rule 4, m8)."""
    proxy, outcome = np.asarray(proxy, float), np.asarray(outcome, float)
    rho = models.spearman(proxy, outcome)
    p_one, method = models.spearman_perm_p(proxy, outcome, "less")
    p_two, _ = models.spearman_perm_p(proxy, outcome, "two-sided")
    lo, hi = models.fisher_ci(rho, len(proxy))
    blo, bhi = models.spearman_bootstrap_ci(proxy, outcome)
    k, n, sp = models.sign_test(proxy, outcome)
    return SpearmanOut(len(proxy), rho, p_one, p_two, method, lo, hi, blo, bhi, k, n, sp)


def drop_largest(proxy: np.ndarray, outcome: np.ndarray, share: float = 0.01):
    """R2 for CPI: drop the ceil(1%) releases with the largest |proxy|."""
    n_drop = math.ceil(share * len(proxy))
    keep = np.ones(len(proxy), dtype=bool)
    keep[np.argsort(-np.abs(proxy), kind="stable")[:n_drop]] = False
    return proxy[keep], outcome[keep]


def placebo_candidates(
    sessions: list[date], exclude_days: set[date], k: int = PLACEBO_EXCLUDE_SESSIONS
) -> list[date]:
    """Sessions at least k+1 sessions away from every CPI release and FOMC day."""
    idx = {d: i for i, d in enumerate(sessions)}
    bad = set()
    for d in exclude_days:
        if d in idx:
            bad.update(range(idx[d] - k, idx[d] + k + 1))
    return [d for i, d in enumerate(sessions) if i not in bad]


def placebo_rhos(
    proxy: np.ndarray,
    outcome: np.ndarray,
    n: int,
    sets: int = PLACEBO_SETS,
    seed: int = PLACEBO_SEED,
) -> np.ndarray:
    """Spearman rho on `sets` random sets of n placebo sessions (without replacement)."""
    rng = np.random.default_rng(seed)
    out = np.empty(sets)
    for i in range(sets):
        pick = rng.choice(len(proxy), n, replace=False)
        out[i] = models.spearman(proxy[pick], outcome[pick])
    return out


# Clock reference for placebo sessions: 07:30 ET (release 08:30 ET minus 60 min). Any instant
# with that ET wall-clock time works; this one is 2025-01-15 07:30 ET.
PLACEBO_CLOCK_REF = 1736944200

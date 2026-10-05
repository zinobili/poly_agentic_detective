"""Turn config/pairs.yaml into fetch targets (pure, no network).

Which tokens: every `token_id_yes` (Fed outcome submarkets, CPI buckets, BTC rungs,
recession markets) plus the `plus_tokens`/`minus_tokens` of derived CPI range buckets.
Inactive BTC rungs (A21) are excluded everywhere, so they are not fetched.

Each token is fetched over its market life [created/start, closed) + a 24h buffer,
clipped to [stock window start, asof). Whole-life pulls use fidelity 60. Additionally
fidelity 1 is fetched in [T - 24h, T + 24h) around every FOMC decision / CPI release T,
for that event's tokens and for the next event's tokens (the signal rolls into it).

Amendment A25 (2026-10-03, extended 2026-10-05 to CPI and recession): every token is also fetched at
fidelity 10 over the same whole life, so the as-of at the :30 session-bar ends is at most ~10
minutes stale (fidelity 60 alone leaves it ~30 minutes stale). Stored under fid=10, alongside
the gap-backfill windows; the manifest coverage makes the two passes idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from poly_actor.ingest.common import DAY, HOUR, Interval, ceil_to, floor_to, merge_intervals
from poly_actor.ingest.polymarket import TokenSpec

BUFFER = DAY
EVENT_HALF_WINDOW = DAY
FID_LIFE = 60
FID_EVENT = 1
FID_DENSE = 10  # A25: full-life pull for the fed and BTC-ladder tokens
PUBLISH_LAG = 600  # the server publishes some points late: stop at floor(asof - 10min, hour)


def _ep(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)  # PyYAML drops the Z; the file is UTC by convention
        return int(v.timestamp())
    return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())


def _clip(s: int, e: int, lo: int, asof: int) -> Interval | None:
    s, e = floor_to(max(s, lo), HOUR), ceil_to(min(e, asof), HOUR)
    e = min(e, floor_to(asof - PUBLISH_LAG, HOUR))
    return (s, e) if s < e else None


class _Plan:
    def __init__(self, lo: int, asof: int):
        self.lo, self.asof = lo, asof
        self.specs: dict[tuple[str, int], TokenSpec] = {}
        self.life: dict[str, Interval] = {}

    def add(
        self, pair: str, token: str, fid: int, s: int, e: int, life: Interval | None = None
    ) -> None:
        if life is not None:  # token's market life [created, closed), before the 24h buffer
            lo, hi = self.life.get(token, life)
            self.life[token] = (min(lo, life[0]), max(hi, life[1]))
        iv = _clip(s, e, self.lo, self.asof)
        if iv is None:
            return
        spec = self.specs.setdefault((token, fid), TokenSpec(token, fid))
        spec.intervals = merge_intervals([*spec.intervals, iv])
        spec.pairs.add(pair)

    def event(self, pair: str, tokens: list[str], t: int) -> None:
        for tok in tokens:
            self.add(pair, tok, FID_EVENT, t - EVENT_HALF_WINDOW, t + EVENT_HALF_WINDOW)


def _fed_tokens(m: dict) -> list[str]:
    toks = [o["token_id_yes"] for o in (m.get("outcomes") or {}).values()]
    toks += [o["token_id_yes"] for o in m.get("other_outcomes") or []]
    return [t for t in toks if t]


def _cpi_tokens(m: dict) -> list[str]:
    toks: list[str] = []
    for b in m.get("buckets") or []:
        if b.get("token_id_yes"):
            toks.append(b["token_id_yes"])
        toks += b.get("plus_tokens") or []
        toks += b.get("minus_tokens") or []
    return list(dict.fromkeys(toks))


def window_start(cfg: dict) -> int:
    """Earliest stock_window_start_utc across pairs (the analysis window floor)."""
    return min(_ep(p["coverage"]["stock_window_start_utc"]) for p in cfg["pairs"])


def pair_ids(cfg: dict) -> list[str]:
    return [p["id"] for p in cfg["pairs"]]


def stock_tickers(cfg: dict, pairs: list[str] | None = None) -> list[str]:
    """Real symbols named in the selected pairs. Spread entries such as 'IWM-SPY' (both
    legs are themselves listed) are derived in analysis, not fetched."""
    out: list[str] = []
    for p in cfg["pairs"]:
        if pairs is None or p["id"] in pairs:
            out += p["tickers"]
    names = set(out)
    real = [t for t in names if not ("-" in t and set(t.split("-")) <= names - {t})]
    return sorted(real)


def build_token_specs(cfg: dict, asof_ts: int, pairs: list[str] | None = None) -> list[TokenSpec]:
    plan = _Plan(window_start(cfg), asof_ts)
    for p in cfg["pairs"]:
        pid = p["id"]
        if pairs is not None and pid not in pairs:
            continue
        if pid == "fed_decision":
            _plan_fed(plan, pid, p)
        elif pid == "us_cpi_inflation":
            _plan_cpi(plan, pid, p)
        elif pid == "bitcoin_monthly_ladder":
            _plan_btc(plan, pid, p)
        elif pid == "us_recession":
            _plan_recession(plan, pid, p)
        else:
            raise ValueError(f"no ingestion plan for pair {pid!r}")
    for sp in plan.specs.values():
        sp.life = plan.life.get(sp.token_id)
    return sorted(plan.specs.values(), key=lambda s: (s.fidelity, s.token_id))


def _plan_fed(plan: _Plan, pid: str, p: dict) -> None:
    ms = sorted(p["markets"], key=lambda m: _ep(m["decision_time_utc"]))
    for i, m in enumerate(ms):
        toks = _fed_tokens(m)
        start, decision = _ep(m["gamma_start"]), _ep(m["decision_time_utc"])
        end = _ep(m["use_until_utc"]) + BUFFER
        for tok in toks:
            plan.add(pid, tok, FID_LIFE, start, end, (start, end - BUFFER))
            plan.add(pid, tok, FID_DENSE, start, end, (start, end - BUFFER))
        plan.event(pid, toks, decision)
        if i + 1 < len(ms):  # signal rolls into the next meeting's market
            plan.event(pid, _fed_tokens(ms[i + 1]), decision)


def _plan_cpi(plan: _Plan, pid: str, p: dict) -> None:
    ms = sorted(p["markets"], key=lambda m: _ep(m["release_time_utc"]))
    for i, m in enumerate(ms):
        toks = _cpi_tokens(m)
        starts = [_ep(x["gamma_start"]) for x in m.get("partitions") or [] if x.get("gamma_start")]
        start = min(starts) if starts else _ep(m["first_usable_utc"])
        release = _ep(m["release_time_utc"])
        for tok in toks:
            plan.add(pid, tok, FID_LIFE, start, release + BUFFER, (start, release))
            plan.add(pid, tok, FID_DENSE, start, release + BUFFER, (start, release))
        plan.event(pid, toks, release)
        if i + 1 < len(ms):
            plan.event(pid, _cpi_tokens(ms[i + 1]), release)


def _plan_btc(plan: _Plan, pid: str, p: dict) -> None:
    for m in p["markets"]:
        month_end = _ep(m["month_end_et_midnight_utc"])
        seen: set[str] = set()
        for key in ("up_ladder", "dip_ladder", "partial_window_rungs"):
            for r in m.get(key) or []:
                tok = r["token_id_yes"]
                if r.get("inactive_excluded") or tok in seen:
                    continue
                seen.add(tok)
                end = _ep(r.get("closed_time")) or month_end
                created = _ep(r["created_utc"])
                for fid in (FID_LIFE, FID_DENSE):
                    plan.add(pid, tok, fid, created, end + BUFFER, (created, end))


def _plan_recession(plan: _Plan, pid: str, p: dict) -> None:
    for m in p["markets"]:
        end = _ep(m.get("closed_time")) or _ep(m["end"])
        tok, start = m["token_id_yes"], _ep(m["start"])
        for fid in (FID_LIFE, FID_DENSE):
            plan.add(pid, tok, fid, start, end + BUFFER, (start, end))

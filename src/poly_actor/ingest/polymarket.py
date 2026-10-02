"""Polymarket CLOB `prices-history` ingestion.

Source: GET https://clob.polymarket.com/prices-history?market=<yes token>&startTs&endTs&fidelity
Native timezone: none; `t` is unix epoch seconds (UTC). `p` is the Yes price in [0, 1].
Resolution: `fidelity` minutes. 60 = hourly (whole-history pulls), 1 = minute (event windows).

Quirks handled here (docs/step1_data_check.md):
- Windows longer than 15 days are rejected (HTTP 400): we tile <= 15 days back to back.
- LOOK-AHEAD TRAP: for active markets the API appends the *current live* price after
  endTs. `parse_prices_history` clips every point to the half-open window [start, end).
- Server boundary semantics are inconsistent (start sometimes excluded). We request
  [start - 60s, end] and clip client-side to [start, end), then de-duplicate on `t`.

Empty 200s: a window that overlaps the token's life but returns no points is recorded as
status="empty" (not covered; retried). Once older than 48h it is probed once at fidelity 1;
if also empty it becomes "empty_confirmed" (covered).

Gap backfill: the server's fidelity-60 sampling is lossy (interior holes of tens of hours).
After the life pass, interior gaps > 3h of the fid=60 + fid=1 series are fetched at fidelity 10
(stored under fid=10). Step 4 must resample across fid=60, fid=10 and fid=1.

Raw layout (immutable, add-only):
  data/raw/polymarket/<token_id>/fid=<fidelity>/<start_ts>_<end_ts>.parquet   columns t, ts, p
  data/raw/polymarket/_manifest.jsonl  (one line per call: ok or failed)
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from poly_actor.config import RAW_DIR
from poly_actor.ingest.common import (
    DAY,
    EMPTY_RETRY_WINDOW,
    IngestError,
    Interval,
    Manifest,
    iso,
    merge_intervals,
    request_json_with_retry,
    sha256_hex,
    subtract_intervals,
    tile,
    utcnow,
    write_parquet_once,
)

CLOB_URL = "https://clob.polymarket.com/prices-history"
MAX_WINDOW = 15 * DAY  # server limit on endTs - startTs
BOUNDARY_PAD = 60  # request start - 60s so a start-exclusive server still returns t == start
TILE = MAX_WINDOW - BOUNDARY_PAD  # keeps the padded request within 15 days
RAW_SUBDIR = "polymarket"
FID_LIFE_FOR_GAPS = 60


def parse_prices_history(body: dict, start_ts: int, end_ts: int) -> pd.DataFrame:
    """Parse a prices-history body into columns t (int64 epoch s), ts (UTC), p (float).

    Keeps only start_ts <= t < end_ts (half-open: kills the appended live point and any
    out-of-window point), sorted, de-duplicated on t (first wins)."""
    if not isinstance(body, dict) or "history" not in body:
        raise ValueError("unexpected prices-history body: no 'history' key")
    hist = body["history"] or []
    df = pd.DataFrame({"t": [h["t"] for h in hist], "p": [h["p"] for h in hist]})
    df["t"] = df["t"].astype("int64")
    df["p"] = df["p"].astype("float64")
    df = df[(df["t"] >= start_ts) & (df["t"] < end_ts)]
    df = df.drop_duplicates(subset="t", keep="first").sort_values("t").reset_index(drop=True)
    df.insert(1, "ts", pd.to_datetime(df["t"], unit="s", utc=True))
    return df


@dataclass(frozen=True)
class FetchResult:
    body: dict
    sha256: str
    n_bytes: int


def fetch_prices_history(
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int,
    *,
    get: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 30.0,
) -> FetchResult:
    """One thin network call (window must be <= 15 days). Retries 429/5xx with backoff."""
    if end_ts - start_ts > MAX_WINDOW:
        raise ValueError("window longer than 15 days is rejected by the CLOB")
    params = {"market": token_id, "startTs": start_ts, "endTs": end_ts, "fidelity": fidelity}
    body, raw = request_json_with_retry(
        get or requests.get, CLOB_URL, params, timeout=timeout, sleep=sleep
    )
    return FetchResult(body, sha256_hex(raw), len(raw))


def plan_windows(target: list[Interval], covered: list[Interval]) -> list[Interval]:
    """Missing parts of `target`, tiled into back-to-back windows of <= TILE seconds."""
    out: list[Interval] = []
    for s, e in subtract_intervals(target, covered):
        out.extend(tile(s, e, TILE))
    return out


@dataclass
class TokenSpec:
    """What to fetch for one (token, fidelity): target intervals plus provenance labels.

    `life` is the token's market life [created, closed) in epoch seconds when known; an empty
    200 response overlapping it is suspicious (status "empty"), not a clean "nothing there"."""

    token_id: str
    fidelity: int
    intervals: list[Interval] = field(default_factory=list)
    pairs: set[str] = field(default_factory=set)
    label: str = ""
    life: Interval | None = None


@dataclass
class RunStats:
    calls: int = 0
    planned_calls: int = 0
    rows: int = 0
    failures: list[dict] = field(default_factory=list)
    per_token_calls: dict[str, int] = field(default_factory=dict)
    planned_by_key: dict[tuple[str, int], int] = field(default_factory=dict)
    empty_pending: int = 0  # empty 200s left uncovered (retried next run)
    empty_confirmed: int = 0
    probe_calls: int = 0
    probe_rows: int = 0


def raw_path(raw_dir: Path, token_id: str, fidelity: int, s: int, e: int) -> Path:
    return raw_dir / RAW_SUBDIR / token_id / f"fid={fidelity}" / f"{s}_{e}.parquet"


def manifest_for(raw_dir: Path = RAW_DIR) -> Manifest:
    return Manifest(raw_dir / RAW_SUBDIR / "_manifest.jsonl")


def overlaps_life(life: Interval | None, s: int, e: int) -> bool:
    """True if [s, e) overlaps the token's life. Unknown life -> False (no empty suspicion)."""
    return life is not None and s < life[1] and e > life[0]


def spec_coverage(records: list[dict], spec: TokenSpec) -> list[Interval]:
    """Covered intervals for a spec: 'ok' windows, except legacy zero-row 'ok' windows that
    overlap the token's life (those were empty 200s wrongly marked covered; re-fetched), plus
    'empty_confirmed'. 'empty' and 'failed' are never covered."""
    out: list[Interval] = []
    for r in records:
        if r.get("token_id") != spec.token_id or r.get("fidelity") != spec.fidelity:
            continue
        st = r.get("status")
        w = (r["start_ts"], r["end_ts"])
        if st == "empty_confirmed":
            out.append(w)
        elif st == "ok" and not (r.get("n_rows") == 0 and overlaps_life(spec.life, *w)):
            out.append(w)
    return out


def _call_window(
    token_id: str,
    fidelity: int,
    s: int,
    e: int,
    *,
    raw_dir: Path,
    fetch: Callable[..., FetchResult],
    now: Callable[[], Any],
) -> tuple[dict, pd.DataFrame, FetchResult]:
    """One fetch + parse + parquet write. Returns (base manifest record, df, result);
    raises IngestError/ValueError/KeyError/RequestException on failure (caller records it)."""
    rec = {
        "source": "polymarket",
        "token_id": token_id,
        "fidelity": fidelity,
        "start_ts": s,
        "end_ts": e,
        "fetched_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    res = fetch(token_id, s - BOUNDARY_PAD, e, fidelity)
    df = parse_prices_history(res.body, s, e)
    n_raw = len(res.body.get("history") or [])
    path = raw_path(raw_dir, token_id, fidelity, s, e)
    wrote = write_parquet_once(df, path) if len(df) else False
    rec.update(
        n_rows=len(df),
        n_rows_response=n_raw,
        n_dropped_outside_window=n_raw - len(df),
        sha256=res.sha256,
        file=str(path.relative_to(raw_dir)).replace("\\", "/") if len(df) else None,
        file_existed=bool(len(df)) and not wrote,
    )
    return rec, df, res


def run_polymarket(
    specs: list[TokenSpec],
    *,
    raw_dir: Path = RAW_DIR,
    fetch: Callable[..., FetchResult] = fetch_prices_history,
    dry_run: bool = False,
    pause: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], Any] = utcnow,
    log: Callable[[str], None] = lambda s: None,
    workers: int = 1,
) -> RunStats:
    """Fetch only the missing windows of each spec. A re-run with nothing missing makes
    zero calls. Failed windows are logged to the manifest (status=failed), not marked covered.

    Empty 200 responses overlapping the token's life are recorded as status="empty" (not
    covered, so retried). If the window ended more than 48h before now, the same window is
    probed once at fidelity 1; if that is empty too the original becomes "empty_confirmed"
    (covered). Probe data, if any, is stored under fid=1."""
    manifest = manifest_for(raw_dir)
    records = manifest.read()
    stats = RunStats()
    lock = threading.Lock()  # guards manifest appends and stats when workers > 1

    plans: list[tuple[TokenSpec, list[tuple[int, int]]]] = []
    for spec in specs:
        cov = spec_coverage(records, spec)
        wins = plan_windows(spec.intervals, cov)
        stats.planned_calls += len(wins)
        if wins:
            stats.planned_by_key[(spec.token_id, spec.fidelity)] = len(wins)
            plans.append((spec, wins))
    if dry_run:
        return stats

    def record(rec: dict, *, failed: bool = False) -> None:
        with lock:
            manifest.append(rec)
            if failed:
                stats.failures.append(rec)

    def count_call(token_id: str, *, probe: bool = False) -> None:
        with lock:
            stats.calls += 1
            if probe:
                stats.probe_calls += 1
            stats.per_token_calls[token_id] = stats.per_token_calls.get(token_id, 0) + 1

    def process(spec: TokenSpec, wins: list[tuple[int, int]]) -> None:
        # Windows of one token run in order in one worker; the pause is per worker.
        made = 0
        for s, e in wins:
            if made:
                sleep(pause)
            made += 1
            count_call(spec.token_id)
            try:
                rec, df, _res = _call_window(
                    spec.token_id, spec.fidelity, s, e, raw_dir=raw_dir, fetch=fetch, now=now
                )
            except (IngestError, ValueError, KeyError, requests.RequestException) as exc:
                record(_fail_rec(spec.token_id, spec.fidelity, s, e, now, exc), failed=True)
                log(f"FAIL {spec.token_id[:12]}.. fid={spec.fidelity} {iso(s)}: {exc}")
                return  # skip this token's remaining windows; others continue
            with lock:
                stats.rows += len(df)
            if len(df) == 0 and overlaps_life(spec.life, s, e):
                rec["status"] = "empty"
                record(rec)
                old = e <= int(now().timestamp()) - EMPTY_RETRY_WINDOW
                if not old:
                    with lock:
                        stats.empty_pending += 1  # recent: the server may still publish it
                    continue
                if spec.fidelity == 1:
                    rec2 = {**rec, "status": "empty_confirmed", "probe_rows": 0}
                else:
                    sleep(pause)
                    count_call(spec.token_id, probe=True)
                    try:
                        prec, pdf, _ = _call_window(
                            spec.token_id, 1, s, e, raw_dir=raw_dir, fetch=fetch, now=now
                        )
                    except (IngestError, ValueError, KeyError, requests.RequestException) as exc:
                        record(_fail_rec(spec.token_id, 1, s, e, now, exc), failed=True)
                        log(f"FAIL probe {spec.token_id[:12]}.. fid=1 {iso(s)}: {exc}")
                        return
                    prec["status"] = "ok"
                    prec["probe_for_fidelity"] = spec.fidelity
                    record(prec)
                    with lock:
                        stats.rows += len(pdf)
                        stats.probe_rows += len(pdf)
                    rec2 = {**rec, "status": "empty_confirmed", "probe_rows": len(pdf)}
                record(rec2)
                with lock:
                    stats.empty_confirmed += 1
                continue
            rec["status"] = "ok"
            record(rec)
            with lock:
                if stats.calls % 50 == 0:
                    log(f"  {stats.calls} calls, {stats.rows} rows")

    if workers <= 1:
        for spec, wins in plans:
            process(spec, wins)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in [pool.submit(process, spec, wins) for spec, wins in plans]:
                fut.result()  # re-raise unexpected errors
    return stats


def _fail_rec(token_id: str, fidelity: int, s: int, e: int, now, exc: Exception) -> dict:
    return {
        "source": "polymarket",
        "token_id": token_id,
        "fidelity": fidelity,
        "start_ts": s,
        "end_ts": e,
        "fetched_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "failed",
        "error": str(exc)[:300],
    }


# ---------------------------------------------------------------- gap backfill (fidelity 10)

BACKFILL_FID = 10
MIN_GAP = 3 * 3600  # an interior gap longer than this in the base (fid 60 + fid 1) series


def find_gaps(
    raw_dir: Path, token_ids: Iterable[str], min_gap: int = MIN_GAP
) -> dict[str, list[Interval]]:
    """Interior gaps (consecutive base points more than `min_gap` apart) per token.

    Base series = fid=60 and fid=1 points (fid=10 backfill is excluded so the gap list is
    stable across runs; coverage of the backfill is tracked by the manifest). A gap is the
    open span between two observed points, returned as [t_a + 1, t_b)."""
    import duckdb

    from poly_actor.store.raw_views import create_raw_views

    wanted = sorted(set(token_ids))
    if not wanted:
        return {}
    con = duckdb.connect()
    create_raw_views(con, raw_dir)
    rows = con.execute(
        """
        SELECT token_id, t_prev, t FROM (
            SELECT token_id, t, lag(t) OVER (PARTITION BY token_id ORDER BY t) AS t_prev
            FROM (SELECT DISTINCT token_id, t FROM raw_polymarket_prices
                  WHERE fidelity IN (60, 1) AND list_contains(?, token_id))
        ) WHERE t - t_prev > ? ORDER BY token_id, t
        """,
        [wanted, min_gap],
    ).fetchall()
    con.close()
    out: dict[str, list[Interval]] = {}
    for tok, a, b in rows:
        out.setdefault(tok, []).append((int(a) + 1, int(b)))
    return out


def backfill_specs(
    raw_dir: Path, specs: list[TokenSpec], min_gap: int = MIN_GAP
) -> list[TokenSpec]:
    """fid=10 specs covering each fid-60/fid-1 token's interior gaps."""
    base = {sp.token_id: sp for sp in specs if sp.fidelity == FID_LIFE_FOR_GAPS}
    gaps = find_gaps(raw_dir, base, min_gap)
    out = []
    for tok in sorted(gaps):
        b = base[tok]
        out.append(
            TokenSpec(
                tok, BACKFILL_FID, merge_intervals(gaps[tok]), set(b.pairs), "backfill", b.life
            )
        )
    return out


def gap_inventory(raw_dir: Path, token_ids: Iterable[str], min_gap: int = MIN_GAP) -> pd.DataFrame:
    """One row per base-series gap: how many fid=10 points landed inside it and what is left.

    Columns: token_id, gap_start_ts/gap_end_ts (+ ISO), gap_hours, filled_points (fid=10 points
    inside the gap), largest_remaining_gap_hours (largest spacing between consecutive points
    of ANY fidelity inside the gap, edges included), status in {filled, partial, unfilled}."""
    import duckdb

    from poly_actor.store.raw_views import create_raw_views

    gaps = find_gaps(raw_dir, token_ids, min_gap)
    cols = [
        "token_id", "gap_start_ts", "gap_end_ts", "gap_start", "gap_end",
        "gap_hours", "filled_points", "largest_remaining_gap_hours", "status",
    ]  # fmt: skip
    if not gaps:
        return pd.DataFrame(columns=cols)
    con = duckdb.connect()
    create_raw_views(con, raw_dir)
    pts = con.execute(
        "SELECT token_id, fidelity, t FROM raw_polymarket_prices WHERE list_contains(?, token_id)",
        [sorted(gaps)],
    ).df()
    con.close()
    by_tok = {k: g for k, g in pts.groupby("token_id")}
    rows = []
    for tok, ivs in gaps.items():
        g = by_tok[tok]
        ts_all = g["t"].to_numpy()
        ts10 = g.loc[g["fidelity"] == BACKFILL_FID, "t"].to_numpy()
        for a, b in ivs:
            inside = sorted(int(x) for x in ts_all if a <= x < b)
            n10 = int(((ts10 >= a) & (ts10 < b)).sum())
            edges = [a - 1, *inside, b]
            worst = max(y - x for x, y in zip(edges, edges[1:], strict=False))
            status = "filled" if worst <= min_gap else ("partial" if n10 else "unfilled")
            rows.append(
                [tok, a, b, iso(a), iso(b), round((b - a + 1) / 3600, 2), n10,
                 round(worst / 3600, 2), status]
            )  # fmt: skip
    return pd.DataFrame(rows, columns=cols)

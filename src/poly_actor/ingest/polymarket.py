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
    base_record,
    failed_record,
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


_FETCH_ERRORS = (IngestError, ValueError, KeyError, requests.RequestException)


def _base_record(token_id: str, fidelity: int, s: int, e: int, now: Callable[[], Any]) -> dict:
    return base_record(
        now, source="polymarket", token_id=token_id, fidelity=fidelity, start_ts=s, end_ts=e
    )


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
    rec = _base_record(token_id, fidelity, s, e, now)
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


class _Run:
    """State and per-window steps of one `run_polymarket` call. The lock guards manifest
    appends and stats when several workers share the run."""

    def __init__(
        self,
        *,
        raw_dir: Path,
        fetch: Callable[..., FetchResult],
        pause: float,
        sleep: Callable[[float], None],
        now: Callable[[], Any],
        log: Callable[[str], None],
        manifest: Manifest,
        stats: RunStats,
    ):
        self.raw_dir, self.fetch, self.pause = raw_dir, fetch, pause
        self.sleep, self.now, self.log = sleep, now, log
        self.manifest, self.stats = manifest, stats
        self.lock = threading.Lock()

    def record(self, rec: dict, *, failed: bool = False) -> None:
        with self.lock:
            self.manifest.append(rec)
            if failed:
                self.stats.failures.append(rec)

    def count_call(self, token_id: str, *, probe: bool = False) -> None:
        with self.lock:
            self.stats.calls += 1
            if probe:
                self.stats.probe_calls += 1
            per = self.stats.per_token_calls
            per[token_id] = per.get(token_id, 0) + 1

    def process(self, spec: TokenSpec, wins: list[tuple[int, int]]) -> None:
        """Windows of one token run in order in one worker; the pause is per worker. A failed
        window skips the token's remaining windows; other tokens continue."""
        for i, (s, e) in enumerate(wins):
            if i:
                self.sleep(self.pause)
            if not self._window(spec, s, e):
                return

    def _fetch_window(
        self, spec: TokenSpec, fidelity: int, s: int, e: int, label: str = ""
    ) -> tuple[dict, pd.DataFrame] | None:
        """Fetch one window; on failure record it (status=failed) and return None."""
        try:
            rec, df, _res = _call_window(
                spec.token_id, fidelity, s, e, raw_dir=self.raw_dir, fetch=self.fetch, now=self.now
            )
        except _FETCH_ERRORS as exc:
            base = _base_record(spec.token_id, fidelity, s, e, self.now)
            self.record(failed_record(base, exc), failed=True)
            self.log(f"FAIL {label}{spec.token_id[:12]}.. fid={fidelity} {iso(s)}: {exc}")
            return None
        return rec, df

    def _window(self, spec: TokenSpec, s: int, e: int) -> bool:
        """Fetch and record one window. False means: abandon this token."""
        self.count_call(spec.token_id)
        got = self._fetch_window(spec, spec.fidelity, s, e)
        if got is None:
            return False
        rec, df = got
        with self.lock:
            self.stats.rows += len(df)
        if len(df) == 0 and overlaps_life(spec.life, s, e):
            return self._handle_empty(spec, rec, s, e)
        rec["status"] = "ok"
        self.record(rec)
        with self.lock:
            if self.stats.calls % 50 == 0:
                self.log(f"  {self.stats.calls} calls, {self.stats.rows} rows")
        return True

    def _handle_empty(self, spec: TokenSpec, rec: dict, s: int, e: int) -> bool:
        """Empty 200 inside the token's life: record 'empty'; if old enough, confirm it with a
        fidelity-1 probe (skipped when already fidelity 1)."""
        rec["status"] = "empty"
        self.record(rec)
        if e > int(self.now().timestamp()) - EMPTY_RETRY_WINDOW:
            with self.lock:
                self.stats.empty_pending += 1  # recent: the server may still publish it
            return True
        probe_rows = 0
        if spec.fidelity != 1:
            n = self._probe_fid1(spec, s, e)
            if n is None:
                return False
            probe_rows = n
        self.record({**rec, "status": "empty_confirmed", "probe_rows": probe_rows})
        with self.lock:
            self.stats.empty_confirmed += 1
        return True

    def _probe_fid1(self, spec: TokenSpec, s: int, e: int) -> int | None:
        """Re-fetch the window at fidelity 1. Returns the probe's row count, or None on failure."""
        self.sleep(self.pause)
        self.count_call(spec.token_id, probe=True)
        got = self._fetch_window(spec, 1, s, e, label="probe ")
        if got is None:
            return None
        prec, pdf = got
        prec["status"] = "ok"
        prec["probe_for_fidelity"] = spec.fidelity
        self.record(prec)
        with self.lock:
            self.stats.rows += len(pdf)
            self.stats.probe_rows += len(pdf)
        return len(pdf)


def _plan_specs(
    specs: list[TokenSpec], records: list[dict], stats: RunStats
) -> list[tuple[TokenSpec, list[tuple[int, int]]]]:
    plans: list[tuple[TokenSpec, list[tuple[int, int]]]] = []
    for spec in specs:
        wins = plan_windows(spec.intervals, spec_coverage(records, spec))
        stats.planned_calls += len(wins)
        if wins:
            stats.planned_by_key[(spec.token_id, spec.fidelity)] = len(wins)
            plans.append((spec, wins))
    return plans


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
    stats = RunStats()
    plans = _plan_specs(specs, manifest.read(), stats)
    if dry_run:
        return stats
    run = _Run(
        raw_dir=raw_dir,
        fetch=fetch,
        pause=pause,
        sleep=sleep,
        now=now,
        log=log,
        manifest=manifest,
        stats=stats,
    )
    if workers <= 1:
        for spec, wins in plans:
            run.process(spec, wins)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in [pool.submit(run.process, spec, wins) for spec, wins in plans]:
                fut.result()  # re-raise unexpected errors
    return stats


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

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

Raw layout (immutable, add-only):
  data/raw/polymarket/<token_id>/fid=<fidelity>/<start_ts>_<end_ts>.parquet   columns t, ts, p
  data/raw/polymarket/_manifest.jsonl  (one line per call: ok or failed)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from poly_actor.config import RAW_DIR
from poly_actor.ingest.common import (
    DAY,
    IngestError,
    Interval,
    Manifest,
    iso,
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
    """What to fetch for one (token, fidelity): target intervals plus provenance labels."""

    token_id: str
    fidelity: int
    intervals: list[Interval] = field(default_factory=list)
    pairs: set[str] = field(default_factory=set)
    label: str = ""


@dataclass
class RunStats:
    calls: int = 0
    planned_calls: int = 0
    rows: int = 0
    failures: list[dict] = field(default_factory=list)
    per_token_calls: dict[str, int] = field(default_factory=dict)
    planned_by_key: dict[tuple[str, int], int] = field(default_factory=dict)


def raw_path(raw_dir: Path, token_id: str, fidelity: int, s: int, e: int) -> Path:
    return raw_dir / RAW_SUBDIR / token_id / f"fid={fidelity}" / f"{s}_{e}.parquet"


def manifest_for(raw_dir: Path = RAW_DIR) -> Manifest:
    return Manifest(raw_dir / RAW_SUBDIR / "_manifest.jsonl")


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
) -> RunStats:
    """Fetch only the missing windows of each spec. A re-run with nothing missing makes
    zero calls. Failed windows are logged to the manifest (status=failed), not marked covered."""
    manifest = manifest_for(raw_dir)
    cov: dict[tuple[str, int], list[Interval]] = {}
    for r in manifest.read():
        if r.get("status") == "ok":
            cov.setdefault((r["token_id"], r["fidelity"]), []).append((r["start_ts"], r["end_ts"]))
    stats = RunStats()
    for spec in specs:
        wins = plan_windows(spec.intervals, cov.get((spec.token_id, spec.fidelity), []))
        stats.planned_calls += len(wins)
        if wins:
            stats.planned_by_key[(spec.token_id, spec.fidelity)] = len(wins)
        if dry_run:
            continue
        for s, e in wins:
            if stats.calls:
                sleep(pause)
            stats.calls += 1
            stats.per_token_calls[spec.token_id] = stats.per_token_calls.get(spec.token_id, 0) + 1
            rec = {
                "source": "polymarket",
                "token_id": spec.token_id,
                "fidelity": spec.fidelity,
                "start_ts": s,
                "end_ts": e,
                "fetched_at": now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            try:
                res = fetch(spec.token_id, s - BOUNDARY_PAD, e, spec.fidelity)
                df = parse_prices_history(res.body, s, e)
            except (IngestError, ValueError, KeyError, requests.RequestException) as exc:
                rec.update(status="failed", error=str(exc)[:300])
                manifest.append(rec)
                stats.failures.append(rec)
                log(f"FAIL {spec.token_id[:12]}.. fid={spec.fidelity} {iso(s)}: {exc}")
                break  # skip this token's remaining windows; others continue
            n_raw = len(res.body.get("history") or [])
            path = raw_path(raw_dir, spec.token_id, spec.fidelity, s, e)
            wrote = write_parquet_once(df, path) if len(df) else False
            rec.update(
                status="ok",
                n_rows=len(df),
                n_rows_response=n_raw,
                n_dropped_outside_window=n_raw - len(df),
                sha256=res.sha256,
                file=str(path.relative_to(raw_dir)).replace("\\", "/") if len(df) else None,
                file_existed=bool(len(df)) and not wrote,
            )
            manifest.append(rec)
            cov.setdefault((spec.token_id, spec.fidelity), []).append((s, e))
            stats.rows += len(df)
            if stats.calls % 50 == 0:
                log(f"  {stats.calls} calls, {stats.rows} rows")
    return stats

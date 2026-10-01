"""Shared ingestion helpers: interval arithmetic, HTTP retry, append-only manifests.

All times here are integer unix epoch seconds (UTC by construction).
Nothing in this module deletes or overwrites files.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Interval = tuple[int, int]  # half-open [start, end) in epoch seconds

HOUR = 3600
DAY = 86400


class IngestError(RuntimeError):
    """A fetch failed in a way the caller should record (not a bug)."""


class HttpStatusError(IngestError):
    def __init__(self, status: int, url: str, text: str = ""):
        super().__init__(f"HTTP {status} for {url}: {text[:200]}")
        self.status = status


def to_epoch(x: str | datetime) -> int:
    """ISO string (trailing Z allowed) or aware datetime -> epoch seconds. Naive is rejected."""
    if isinstance(x, str):
        x = datetime.fromisoformat(x.replace("Z", "+00:00"))
    if x.tzinfo is None:
        raise ValueError("naive datetime not allowed (UTC everywhere)")
    return int(x.timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(UTC)


def floor_to(ts: int, step: int) -> int:
    return ts - ts % step


def ceil_to(ts: int, step: int) -> int:
    return ts + (-ts) % step


def merge_intervals(ivs: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(i for i in ivs if i[0] < i[1]):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract_intervals(target: Iterable[Interval], covered: Iterable[Interval]) -> list[Interval]:
    """Parts of `target` intervals not inside `covered` (all half-open)."""
    cov = merge_intervals(covered)
    out: list[Interval] = []
    for s, e in merge_intervals(target):
        cur = s
        for cs, ce in cov:
            if ce <= cur:
                continue
            if cs >= e:
                break
            if cs > cur:
                out.append((cur, cs))
            cur = max(cur, ce)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def tile(start: int, end: int, max_len: int) -> list[Interval]:
    """Back-to-back windows of length <= max_len covering [start, end) exactly."""
    out: list[Interval] = []
    cur = start
    while cur < end:
        nxt = min(cur + max_len, end)
        out.append((cur, nxt))
        cur = nxt
    return out


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_json_with_retry(
    get: Callable[..., Any],
    url: str,
    params: dict[str, Any],
    *,
    timeout: float = 30.0,
    max_retries: int = 6,
    backoff_base: float = 1.0,
    backoff_cap: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, bytes]:
    """GET -> (parsed json, raw bytes). Retries 429, 5xx, timeouts and connection errors
    with exponential backoff (honours Retry-After). Other 4xx raise HttpStatusError at once."""
    import requests

    last: Exception | None = None
    for attempt in range(max_retries + 1):
        wait = min(backoff_cap, backoff_base * 2**attempt)
        try:
            resp = get(url, params=params, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = exc
        else:
            status = resp.status_code
            if status == 200:
                try:
                    return resp.json(), resp.content
                except ValueError as exc:  # truncated/garbled body: retry
                    last = exc
            elif status == 429 or status >= 500:
                last = HttpStatusError(status, url, getattr(resp, "text", ""))
                ra = getattr(resp, "headers", {}).get("Retry-After")
                if ra:
                    try:
                        wait = min(backoff_cap, max(wait, float(ra)))
                    except ValueError:
                        pass
            else:
                raise HttpStatusError(status, url, getattr(resp, "text", ""))
        if attempt < max_retries:
            sleep(wait)
    raise IngestError(f"gave up after {max_retries + 1} attempts: {last!r}")


class Manifest:
    """Append-only JSONL log of every fetch (ok or failed). Never rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()

    def covered(self, **match: Any) -> list[Interval]:
        """Intervals of status=='ok' records whose fields equal `match`."""
        return merge_intervals(
            (r["start_ts"], r["end_ts"])
            for r in self.read()
            if r.get("status") == "ok" and all(r.get(k) == v for k, v in match.items())
        )


def write_parquet_once(df, path: Path) -> bool:
    """Write df to `path` atomically unless it already exists (raw is immutable).
    Returns True if written."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return True

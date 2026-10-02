"""Shared ingestion helpers: interval arithmetic, HTTP retry, append-only manifests.

All times here are integer unix epoch seconds (UTC by construction).
Nothing in this module deletes or overwrites files.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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


EMPTY_RETRY_WINDOW = 2 * DAY  # empty windows ending this close to asof may still be filled upstream


TORN_MARKER = "torn_line_sealed"


def _is_torn_marker(line: str) -> bool:
    try:
        return json.loads(line).get("status") == TORN_MARKER
    except (json.JSONDecodeError, AttributeError):
        return False


class Manifest:
    """Append-only JSONL log of every fetch (ok, empty, empty_confirmed or failed). Never rewritten.

    Statuses: ok (data stored, or nothing expected there), empty (HTTP 200 but no points although
    the window overlaps the token's life: NOT covered, retried), empty_confirmed (also empty at
    fidelity 1 and older than 48h: covered), failed (not covered)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> list[dict]:
        """All records. A torn line from a crashed write is skipped with a warning when it is
        the final line, or when `append` has since sealed it (it is followed by a
        TORN_MARKER record). Any other malformed line is real corruption and raises. Marker
        records are bookkeeping and are not returned."""
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        out: list[dict] = []
        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                sealed = i + 1 < len(lines) and _is_torn_marker(lines[i + 1])
                if i == len(lines) - 1 or sealed:
                    log.warning(
                        "skipping malformed (torn) manifest line %d in %s", i + 1, self.path
                    )
                    continue
                raise
            if rec.get("status") != TORN_MARKER:
                out.append(rec)
        return out

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as f:
            f.seek(0, 2)
            if f.tell():
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    # A crash left a torn final line: end it, then mark it as sealed so
                    # read() can tell it apart from real corruption.
                    marker = {"status": TORN_MARKER, "sealed_at": utcnow().isoformat()}
                    f.write(b"\n" + json.dumps(marker).encode() + b"\n")
            f.write((json.dumps(record, sort_keys=True) + "\n").encode())
            f.flush()

    def covered(self, **match: Any) -> list[Interval]:
        """Intervals of covered records whose fields equal `match`. Covered means status 'ok' or
        'empty_confirmed'. Status 'empty' is never covered (it is retried, and once older than
        48h it is probed at fidelity 1 and promoted to 'empty_confirmed')."""
        return merge_intervals(
            (r["start_ts"], r["end_ts"])
            for r in self.read()
            if r.get("status") in ("ok", "empty_confirmed")
            and all(r.get(k) == v for k, v in match.items())
        )


@contextlib.contextmanager
def ingest_lock(raw_dir: Path):
    """Exclusive lock file data/raw/.ingest.lock (O_EXCL). A second concurrent run fails fast.
    Removed on exit. A stale lock after a hard crash must be removed by hand."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / ".ingest.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise IngestError(f"another ingest run holds {path} (delete it if stale)") from exc
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode())
        os.close(fd)
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def write_parquet_once(df, path: Path) -> bool:
    """Write df to `path` atomically unless it already exists (raw is immutable).
    Returns True if written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return True

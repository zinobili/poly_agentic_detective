"""Results contract: the JSON files the analysis step writes and the dashboard reads.

One file per pair at ``data/clean/results/<pair_id>.json``. Every top-level slot is optional.
A missing file, a missing slot or a malformed slot becomes ``None`` and the dashboard shows
"Not run yet" for it. Nothing here ever fills in a default number.

Shape (all timestamps ISO-8601, tz-aware UTC; the dashboard never reads local time)::

    {
      "pair_id": "fed_decision",
      "n_events": 19,                                   # int, or null
      "xcorr": {"ticker": "TLT", "lags": [-12, ..., 12],  # whole hours; + = odds first
                "r": [...], "band": 0.05},               # one r per lag; band = +/- noise zone
      "event_study": {"ticker": "TLT", "hours": [-6, ..., 12],
                      "mean": [...], "ci_low": [...], "ci_high": [...],  # percent moves
                      "event_times": ["2025-03-19T18:00:00Z", ...]},
      "checklist": [{"name": "...", "status": "Passed|Failed|Weak|Not needed|Not run",
                     "plain": "...", "technical": "..."}],
      "verdict": "Polymarket moves first|Moves at the same time|No extra information
                  |Too early to tell",
      "confidence": {"level": "Not enough data|Low|Medium|High", "reason": "..."}
    }
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATUSES = ("Passed", "Failed", "Weak", "Not needed", "Not run")
VERDICTS = (
    "Polymarket moves first",
    "Moves at the same time",
    "No extra information",
    "Too early to tell",
)
CONFIDENCE_LEVELS = ("Not enough data", "Low", "Medium", "High")


@dataclass(frozen=True)
class XCorr:
    ticker: str
    lags: tuple[int, ...]
    r: tuple[float, ...]
    band: float


@dataclass(frozen=True)
class EventStudy:
    ticker: str
    hours: tuple[int, ...]
    mean: tuple[float, ...]
    ci_low: tuple[float, ...]
    ci_high: tuple[float, ...]
    event_times: tuple[datetime, ...]


@dataclass(frozen=True)
class CheckRow:
    name: str
    status: str
    plain: str
    technical: str


@dataclass(frozen=True)
class Confidence:
    level: str
    reason: str


@dataclass(frozen=True)
class PairResults:
    pair_id: str
    xcorr: XCorr | None = None
    event_study: EventStudy | None = None
    checklist: tuple[CheckRow, ...] | None = None
    verdict: str | None = None
    confidence: Confidence | None = None
    n_events: int | None = None


def results_path(clean_dir: Path, pair_id: str) -> Path:
    return clean_dir / "results" / f"{pair_id}.json"


def load_results(clean_dir: Path, pair_id: str) -> PairResults | None:
    """Read one pair's results file; ``None`` if it is missing, unreadable or for another pair."""
    path = results_path(clean_dir, pair_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable results file %s: %s", path, exc)
        return None
    if not isinstance(raw, dict) or raw.get("pair_id") != pair_id:
        log.warning("Ignoring results file %s: pair_id does not match", path)
        return None
    return parse_results(raw)


def parse_results(raw: dict[str, Any]) -> PairResults:
    """Pure parser: each slot is validated on its own, bad slots become ``None``."""
    return PairResults(
        pair_id=str(raw.get("pair_id")),
        xcorr=_xcorr(raw.get("xcorr")),
        event_study=_event_study(raw.get("event_study")),
        checklist=_checklist(raw.get("checklist")),
        verdict=raw.get("verdict") if raw.get("verdict") in VERDICTS else None,
        confidence=_confidence(raw.get("confidence")),
        n_events=_count(raw.get("n_events")),
    )


def _floats(values: Any) -> tuple[float, ...] | None:
    if not isinstance(values, list) or not values:
        return None
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int | float):
            return None
        out.append(float(v))
    return tuple(out)


def _ints(values: Any) -> tuple[int, ...] | None:
    floats = _floats(values)
    if floats is None or any(not f.is_integer() for f in floats):
        return None
    return tuple(int(f) for f in floats)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _xcorr(raw: Any) -> XCorr | None:
    if not isinstance(raw, dict):
        return None
    ticker, lags, r, band = _text(raw.get("ticker")), _ints(raw.get("lags")), None, None
    r = _floats(raw.get("r"))
    band = _floats([raw.get("band")])
    if not (ticker and lags and r and band) or len(lags) != len(r):
        return None
    if not math.isfinite(band[0]) or band[0] < 0 or len(set(lags)) != len(lags):
        return None
    order = sorted(range(len(lags)), key=lambda i: lags[i])
    return XCorr(ticker, tuple(lags[i] for i in order), tuple(r[i] for i in order), band[0])


def _event_times(values: Any) -> tuple[datetime, ...] | None:
    if not isinstance(values, list):
        return None
    out = []
    for v in values:
        try:
            t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
        if t.tzinfo is None:
            return None
        out.append(t)
    return tuple(out)


def _event_study(raw: Any) -> EventStudy | None:
    if not isinstance(raw, dict):
        return None
    ticker, hours = _text(raw.get("ticker")), _ints(raw.get("hours"))
    mean, low, high = (_floats(raw.get(k)) for k in ("mean", "ci_low", "ci_high"))
    times = _event_times(raw.get("event_times", []))
    if not (ticker and hours and mean and low and high) or times is None:
        return None
    if not len(hours) == len(mean) == len(low) == len(high):
        return None
    return EventStudy(ticker, hours, mean, low, high, times)


def _checklist(raw: Any) -> tuple[CheckRow, ...] | None:
    if not isinstance(raw, list) or not raw:
        return None
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        name = _text(item.get("name"))
        status = item.get("status")
        if not name or status not in STATUSES:
            return None
        rows.append(
            CheckRow(
                name, status, _text(item.get("plain")) or name, _text(item.get("technical")) or ""
            )
        )
    return tuple(rows)


def _confidence(raw: Any) -> Confidence | None:
    if not isinstance(raw, dict) or raw.get("level") not in CONFIDENCE_LEVELS:
        return None
    reason = _text(raw.get("reason"))
    return Confidence(raw["level"], reason) if reason else None

"""Results contract: the JSON files the analysis step writes and the dashboard reads.

One file per pair at ``data/clean/results/<pair_id>.json``. Every top-level slot is optional.
A missing file, a missing slot or a malformed slot becomes ``None`` and the dashboard shows
"Not run yet" for it. Nothing here ever fills in a default number.

Shape (schema 2; timestamps ISO-8601, tz-aware UTC)::

    {
      "pair_id": "fed_decision",
      "primary_ticker": "TLT",                       # the pre-registered test's stock
      "verdict": one of VERDICTS, "verdict_reason": "...",
      "confidence": {"level": one of CONFIDENCE_LEVELS, "reason": "..."},
      "stocks_first": true|false|null,               # exploratory label (A27 rule 8)
      "n_events": 16,
      "params": {"xcorr_lags": [-6, 6], "band_level": 0.95, "ci_level": 0.9, ...},
      "xcorr": "not_in_plan"                          # CPI, recession: no hourly lead-lag
             | {"TLT": {"lags": [-6..6], "r": [...], "band": 3.1,    # scalar band
                        "t": [...], "band_stat": "robust_t",          # A28: band on |t|
                        "residualised": {"lags", "r", "t", "band", "band_stat",
                                         "note"}}},  # BTC; note = caveat (A29)
      "event_study": {"TLT": {"unit": "bars|days", "steps": ["-3", ..., "gap", ...],
                              "mean", "ci_low", "ci_high",            # percent, per step
                              "band_low", "band_high",                # optional random dates
                              "paths": [[...], ...], "gap_marks": [[3], ...],  # optional
                              "label": "...", "compare": {"label", "mean", "ci_low",
                              "ci_high"},                             # optional
                              "n_unsigned": 0, "event_times": [...]}},
      "event_study_notes": {"TLT": "Too few events to draw this chart: ..."},  # optional
      "checklist": [{"name", "status": one of STATUSES, "plain", "technical"}]
    }
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATUSES = (
    "Passed",
    "Failed",
    "Failed (opposite sign)",
    "Weak",
    "Not needed",
    "Not run",
    "Not valid",  # the test ran but is biased by construction (prereg A29)
)
VERDICTS = (
    "Polymarket moves first",
    "Moves at the same time",
    "No head start",
    "No extra information",
    "Too early to tell",
    "Descriptive only",
)
CONFIDENCE_LEVELS = ("Not enough data", "Low", "Medium", "High")
NOT_IN_PLAN = "not_in_plan"
GAP_STEP = "gap"


@dataclass(frozen=True)
class XCorr:
    ticker: str
    lags: tuple[int, ...]
    r: tuple[float, ...]  # drawn in Chart 1
    band: float  # simultaneous noise band (scalar), in the units of `stat`
    residualised: XCorr | None = None  # BTC: returns net of Bitcoin's own price
    t: tuple[float, ...] | None = None  # robust t per lag; the band applies to it (A28 item 1)
    note: str | None = None  # caveat: the panel is shown but not read as evidence (A29)

    @property
    def stat(self) -> tuple[float, ...]:
        """The per-lag statistic the band applies to: robust t when given, else r."""
        return self.t if self.t is not None else self.r


@dataclass(frozen=True)
class Compare:
    label: str
    mean: tuple[float, ...]
    ci_low: tuple[float, ...]
    ci_high: tuple[float, ...]


@dataclass(frozen=True)
class EventStudy:
    ticker: str
    steps: tuple[str, ...]  # event-time labels; "gap" marks an opening-gap step
    mean: tuple[float, ...]
    ci_low: tuple[float, ...]
    ci_high: tuple[float, ...]
    event_times: tuple[datetime, ...]
    unit: str = "bars"
    band_low: tuple[float, ...] | None = None
    band_high: tuple[float, ...] | None = None
    paths: tuple[tuple[float, ...], ...] = ()
    gap_marks: tuple[tuple[int, ...], ...] = ()
    label: str | None = None
    compare: Compare | None = None
    n_unsigned: int | None = None


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
    xcorr: dict[str, XCorr] | None = None  # by ticker
    xcorr_not_in_plan: bool = False
    event_study: dict[str, EventStudy] | None = None  # by ticker
    checklist: tuple[CheckRow, ...] | None = None
    verdict: str | None = None
    verdict_reason: str | None = None
    confidence: Confidence | None = None
    n_events: int | None = None
    stocks_first: bool | None = None
    params: dict[str, Any] = field(default_factory=dict)
    primary_ticker: str | None = None  # the stock of the pre-registered test
    event_study_notes: dict[str, str] | None = None  # by ticker: why chart 2 is missing


def results_path(clean_dir: Path, pair_id: str) -> Path:
    """Where the analysis writes a pair's results JSON."""
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
    xraw = raw.get("xcorr")
    stocks_first = raw.get("stocks_first")
    return PairResults(
        pair_id=str(raw.get("pair_id")),
        xcorr=None if xraw == NOT_IN_PLAN else _by_ticker(xraw, _xcorr, "xcorr"),
        xcorr_not_in_plan=xraw == NOT_IN_PLAN,
        event_study=_by_ticker(raw.get("event_study"), _event_study, "event_study"),
        checklist=_checklist(raw.get("checklist")),
        verdict=raw.get("verdict") if raw.get("verdict") in VERDICTS else None,
        verdict_reason=_text(raw.get("verdict_reason")),
        confidence=_confidence(raw.get("confidence")),
        n_events=_count(raw.get("n_events")),
        stocks_first=stocks_first if isinstance(stocks_first, bool) else None,
        params=raw.get("params") if isinstance(raw.get("params"), dict) else {},
        primary_ticker=_text(raw.get("primary_ticker")),
        event_study_notes=_notes(raw.get("event_study_notes")),
    )


def _notes(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    out = {str(k): _text(v) for k, v in raw.items()}
    return {k: v for k, v in out.items() if v} or None


def _by_ticker(raw: Any, parse: Callable[[str, Any], Any], slot: str) -> dict[str, Any] | None:
    """Parse each ticker's entry on its own; bad entries are logged and left out."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for ticker, entry in raw.items():
        value = parse(str(ticker), entry)
        if value is None:
            log.warning("Ignoring invalid %s entry for %s", slot, ticker)
        else:
            out[str(ticker)] = value
    return out or None


def _floats(values: Any) -> tuple[float, ...] | None:
    if not isinstance(values, list) or not values:
        return None
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int | float):
            return None
        if not math.isfinite(v):
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


def _plain_xcorr(ticker: str, raw: Any) -> XCorr | None:
    if not isinstance(raw, dict):
        return None
    lags, r, band = _ints(raw.get("lags")), _floats(raw.get("r")), _floats([raw.get("band")])
    if not (lags and r and band) or len(lags) != len(r):
        return None
    if band[0] < 0 or len(set(lags)) != len(lags):
        return None
    t = None
    if raw.get("band_stat") == "robust_t":  # A28 item 1: the band is read against |t|
        t = _floats(raw.get("t"))
        if t is None or len(t) != len(lags):
            return None
    elif raw.get("band_stat") not in (None, "r"):
        return None
    order = sorted(range(len(lags)), key=lambda i: lags[i])
    return XCorr(
        ticker,
        tuple(lags[i] for i in order),
        tuple(r[i] for i in order),
        band[0],
        t=None if t is None else tuple(t[i] for i in order),
        note=_text(raw.get("note")),
    )


def _xcorr(ticker: str, raw: Any) -> XCorr | None:
    base = _plain_xcorr(ticker, raw)
    if base is None:
        return None
    resid = raw.get("residualised")
    if resid is None:
        return base
    parsed = _plain_xcorr(ticker, resid)
    if parsed is None:
        return None
    return XCorr(base.ticker, base.lags, base.r, base.band, parsed, base.t, base.note)


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


def _steps(values: Any) -> tuple[str, ...] | None:
    if not isinstance(values, list) or not values:
        return None
    if not all(isinstance(v, str) and v for v in values):
        return None
    return tuple(values)


def _paths(raw: Any, n: int) -> tuple[tuple[float, ...], ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return None
    out = []
    for p in raw:
        vals = _floats(p)
        if vals is None or len(vals) != n:
            return None
        out.append(vals)
    return tuple(out)


def _gap_marks(raw: Any, n_paths: int) -> tuple[tuple[int, ...], ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) != n_paths:
        return None
    out = []
    for m in raw:
        if m == []:
            out.append(())
            continue
        ints = _ints(m)
        if ints is None:
            return None
        out.append(ints)
    return tuple(out)


def _compare(raw: Any, n: int) -> Compare | None:
    if not isinstance(raw, dict):
        return None
    mean, low, high = (_floats(raw.get(k)) for k in ("mean", "ci_low", "ci_high"))
    label = _text(raw.get("label"))
    if not (label and mean and low and high) or not len(mean) == len(low) == len(high) == n:
        return None
    return Compare(label, mean, low, high)


def _event_study(ticker: str, raw: Any) -> EventStudy | None:
    if not isinstance(raw, dict):
        return None
    steps = _steps(raw.get("steps"))
    mean, low, high = (_floats(raw.get(k)) for k in ("mean", "ci_low", "ci_high"))
    times = _event_times(raw.get("event_times", []))
    if not (steps and mean and low and high) or times is None:
        return None
    n = len(steps)
    if not n == len(mean) == len(low) == len(high):
        return None
    band_low, band_high = _floats(raw.get("band_low")), _floats(raw.get("band_high"))
    if (band_low is None) != (band_high is None):
        return None
    if band_low is not None and not len(band_low) == len(band_high) == n:
        return None
    paths = _paths(raw.get("paths"), n)
    marks = _gap_marks(raw.get("gap_marks"), len(paths or ()))
    unit = raw.get("unit", "bars")
    if paths is None or marks is None or unit not in ("bars", "days"):
        return None
    compare = _compare(raw.get("compare"), n) if raw.get("compare") is not None else None
    return EventStudy(
        ticker,
        steps,
        mean,
        low,
        high,
        times,
        unit=unit,
        band_low=band_low,
        band_high=band_high,
        paths=paths,
        gap_marks=marks,
        label=_text(raw.get("label")),
        compare=compare,
        n_unsigned=_count(raw.get("n_unsigned")),
    )


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

"""Read-only loading of the published election bundle (`reports/election/`). No network, no
writes, no statistics: `results.json` as a dict and each `series/*.csv` as a DataFrame.

Dates and timestamps are read as strings; `h3_night.bar_end_ts` is tz-aware UTC text.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from poly_actor.config import ROOT

log = logging.getLogger(__name__)

BUNDLE_DIR = ROOT / "reports" / "election"
BUNDLE_DIR_ENV = "POLY_ACTOR_ELECTION_BUNDLE"
RESULTS_FILE = "results.json"
BUILD_COMMAND = (  # shown to the reader as-is
    "python -m poly_actor.studies.election analyse && python -m poly_actor.studies.election publish"
)


@dataclass(frozen=True)
class Bundle:
    """The step-9 results tree and its chart series (name -> frame; a missing file is absent)."""

    results: dict[str, Any]
    series: dict[str, pd.DataFrame] = field(default_factory=dict)


def bundle_dir() -> Path:
    """The bundle folder: the environment override if set, else `reports/election/`."""
    return Path(os.environ.get(BUNDLE_DIR_ENV, BUNDLE_DIR))


def load_bundle(folder: Path) -> Bundle | None:
    """The bundle in ``folder``, or ``None`` when `results.json` is missing or unreadable."""
    path = folder / RESULTS_FILE
    if not path.is_file():
        return None
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable bundle %s: %s", path, exc)
        return None
    if not isinstance(results, dict):
        log.warning("Ignoring bundle %s: top level is not a JSON object", path)
        return None
    series: dict[str, pd.DataFrame] = {}
    for name, rel in sorted((results.get("series") or {}).items()):
        csv = folder / str(rel)
        if not csv.is_file():
            log.warning("Series %r listed in %s is missing: %s", name, RESULTS_FILE, csv)
            continue
        try:
            series[name] = pd.read_csv(csv)
        except (OSError, ValueError) as exc:  # pandas parser errors are ValueErrors
            log.warning("Ignoring unreadable series %s: %s", csv, exc)
    return Bundle(results, series)


def bundle_signature(folder: Path) -> tuple[tuple[str, int], ...]:
    """(relative path, mtime in ns) of every bundle file: a cache key that changes on rewrite."""
    if not folder.is_dir():
        return ()
    files = [p for p in folder.rglob("*") if p.is_file()]
    return tuple(sorted((str(p.relative_to(folder)), p.stat().st_mtime_ns) for p in files))

"""Read-only loading for the dashboard: panels, results and the pair list. No network, no writes.

Timezone: every panel timestamp is tz-aware UTC (hourly grid, session bars are 30-90 min).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from poly_actor.config import CONFIG_DIR

from .contract import PairResults, load_results, results_path

log = logging.getLogger(__name__)

try:  # the C loader is ~10x faster on the 4k-line pairs file
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _Loader

PAIRS_FILE = CONFIG_DIR / "pairs.yaml"


@dataclass(frozen=True)
class PairSpec:
    """A pair id and its tickers, in pairs-file order."""

    pair_id: str
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class Coverage:
    """Observed facts about a panel. Times are tz-aware UTC; ages are in seconds."""

    first: datetime  # first row end (UTC)
    last: datetime  # last row end (UTC)
    rows: int  # panel rows (hourly windows)
    both_trading_rows: int  # session bars where both markets trade
    median_quote_age_s: float | None  # seconds, on both-trading rows


def load_pair_specs(path: Path = PAIRS_FILE) -> tuple[PairSpec, ...]:
    """Pair ids and tickers, in the order written in the pairs file."""
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 (safe loader)
    return tuple(PairSpec(p["id"], tuple(p["tickers"])) for p in doc["pairs"])


def load_panel(clean_dir: Path, pair_id: str) -> pd.DataFrame | None:
    """The aligned hourly panel for a pair, or ``None`` if it is missing or unreadable."""
    path = clean_dir / f"panel_{pair_id}.parquet"
    if not path.is_file():
        return None
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as exc:  # pyarrow's ArrowInvalid is a ValueError
        log.warning("Ignoring unreadable panel %s: %s", path, exc)
        return None


def load_all_results(clean_dir: Path, specs: tuple[PairSpec, ...]) -> dict[str, PairResults | None]:
    """Every pair's results (``None`` where missing or malformed), keyed by pair id."""
    return {s.pair_id: load_results(clean_dir, s.pair_id) for s in specs}


def results_signature(clean_dir: Path) -> tuple[tuple[str, int], ...]:
    """(file name, mtime in ns) of every results file: a cache key that changes on rewrite."""
    folder = results_path(clean_dir, "any").parent
    if not folder.is_dir():
        return ()
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in folder.glob("*.json")))


def panel_coverage(panel: pd.DataFrame) -> Coverage | None:
    """Real, observed facts about a panel: span, usable rows, how old Polymarket quotes are."""
    if panel.empty:
        return None
    ages = panel.loc[panel["both_trading"], "pm_obs_age_s"].dropna()
    return Coverage(
        first=panel["ts_end"].min().to_pydatetime(),
        last=panel["ts_end"].max().to_pydatetime(),
        rows=len(panel),
        both_trading_rows=int(panel["both_trading"].sum()),
        median_quote_age_s=float(ages.median()) if len(ages) else None,
    )


def available_tickers(panel: pd.DataFrame, tickers: tuple[str, ...]) -> tuple[str, ...]:
    """Tickers that have a plain return series in the panel (not derived spreads)."""
    return tuple(t for t in tickers if f"ret_{t}" in panel.columns)

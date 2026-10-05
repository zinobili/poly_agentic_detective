"""Read-only loading for the dashboard: panels, results and the pair list. No network, no writes.

Timezone: every panel timestamp is tz-aware UTC (hourly grid, session bars are 30-90 min).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from poly_actor.config import CONFIG_DIR

from .contract import PairResults, load_results

try:  # the C loader is ~10x faster on the 4k-line pairs file
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _Loader

PAIRS_FILE = CONFIG_DIR / "pairs.yaml"


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class Coverage:
    first: datetime
    last: datetime
    rows: int
    both_trading_rows: int
    median_quote_age_s: float | None


def load_pair_specs(path: Path = PAIRS_FILE) -> tuple[PairSpec, ...]:
    """Pair ids and tickers, in the order written in the pairs file."""
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506 (safe loader)
    return tuple(PairSpec(p["id"], tuple(p["tickers"])) for p in doc["pairs"])


def load_panel(clean_dir: Path, pair_id: str) -> pd.DataFrame | None:
    """The aligned hourly panel for a pair, or ``None`` if it has not been built."""
    path = clean_dir / f"panel_{pair_id}.parquet"
    return pd.read_parquet(path) if path.is_file() else None


def load_all_results(clean_dir: Path, specs: tuple[PairSpec, ...]) -> dict[str, PairResults | None]:
    return {s.pair_id: load_results(clean_dir, s.pair_id) for s in specs}


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

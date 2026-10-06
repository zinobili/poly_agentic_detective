"""I/O for step 6: panels from data/clean, price books and calendars from data/raw (read-only).

Everything returned here is a level, a flag or a calendar; returns are only read by the
callers that run the tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.align import pipeline
from poly_actor.align.pipeline import PairInputs
from poly_actor.analysis import cpi as cpi_mod
from poly_actor.ingest.common import to_epoch


@dataclass(frozen=True)
class Calendar:
    sessions: list[date]
    opens: dict[date, int]
    closes: dict[date, int]


def calendar(inputs: PairInputs) -> Calendar:
    s = inputs.sessions
    days = list(s["session"])
    return Calendar(
        days,
        dict(zip(days, s["open_s"].astype(int), strict=True)),
        dict(zip(days, s["close_s"].astype(int), strict=True)),
    )


def pair_inputs(cfg: Mapping, pair_id: str) -> PairInputs:
    """Events, evaluator, price books and sessions of a pair (raw data, read-only)."""
    con = pipeline.connect_raw()
    try:
        return pipeline.build_pair_inputs(cfg, pair_id, con)[0]
    finally:
        con.close()


def load_panel(clean_dir: Path, pair_id: str) -> pd.DataFrame:
    path = pipeline.panel_path(pair_id, clean_dir)
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run `python -m poly_actor.align run` first")
    return pd.read_parquet(path)


def event_days(cfg: Mapping) -> dict[str, set[date]]:
    """ET session dates of FOMC decisions and CPI releases (from pairs.yaml)."""
    fed = pipeline.find_pair(cfg, "fed_decision")
    cpi = pipeline.find_pair(cfg, "us_cpi_inflation")
    return {
        "fomc": {cpi_mod.et_date(to_epoch(m["decision_time_utc"])) for m in fed["markets"]},
        "cpi": {cpi_mod.et_date(to_epoch(m["release_time_utc"])) for m in cpi["markets"]},
    }


def cpi_release_table(cfg: Mapping, inputs: PairInputs) -> pd.DataFrame:
    """Validity-only release table (levels at exact instants; no returns)."""
    cal = calendar(inputs)
    rels = cpi_mod.releases(pipeline.find_pair(cfg, "us_cpi_inflation"))
    last = max(cal.closes.values())
    rels = [r for r in rels if r.release_s <= last]  # releases after the data end
    return cpi_mod.release_table(
        rels,
        inputs.events,
        inputs.evaluator,
        inputs.pm_book,
        inputs.spot_book,
        cal.sessions,
        cal.closes,
    )


def spot_lookup(inputs: PairInputs, key: str = "BTC-USD"):
    """Epoch seconds -> as-of BTC-USD close (NaN beyond the 3 h staleness cap)."""

    def at(instants: np.ndarray) -> np.ndarray:
        return inputs.spot_book.asof(key, np.asarray(instants, dtype="int64")).p

    return at


def cpi_placebo_table(inputs: PairInputs, candidates: list[date]) -> pd.DataFrame:
    """Levels at 07:30 ET on each candidate session and 5 sessions earlier, same event."""
    from poly_actor.align.consts import OK
    from poly_actor.align.events import active_index

    cal = calendar(inputs)
    rows = []
    for day in candidates:
        back = cpi_mod.sessions_back(cal.sessions, day, cpi_mod.SESSIONS_BACK)
        if back is None:
            continue
        t1 = cpi_mod.same_clock(cpi_mod.PLACEBO_CLOCK_REF, day)
        rows.append({"session": day, "t1": t1, "t0": cpi_mod.same_clock(t1, back)})
    tab = pd.DataFrame(rows)
    act = active_index(inputs.events, tab["t1"].to_numpy("int64"))
    tab = tab[act >= 0].reset_index(drop=True)
    ids = [inputs.events[i].id for i in active_index(inputs.events, tab["t1"].to_numpy("int64"))]
    for col, tag in (("t1", "1"), ("t0", "0")):
        lv = cpi_mod.evaluate_at(
            inputs.events,
            inputs.evaluator,
            inputs.pm_book,
            inputs.spot_book,
            tab[col].to_numpy("int64"),
            ids,
        )
        tab[f"level{tag}"] = lv["level"].to_numpy()
        tab[f"reason{tag}"] = lv["reason"].to_numpy()
    tab["usable"] = (tab["reason1"] == OK) & (tab["reason0"] == OK)
    tab["proxy"] = np.where(tab["usable"], tab["level1"] - tab["level0"], np.nan)
    return tab

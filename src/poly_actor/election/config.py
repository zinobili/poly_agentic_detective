"""Typed view of config/election.yaml (the single source of truth for the election study).

Dates in the file are quoted strings: `...Z` instants are UTC, bare `YYYY-MM-DD` are ET calendar
dates (converted to America/New_York midnight epochs here, with zoneinfo, never fixed offsets).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from poly_actor.config import CLEAN_DIR, CONFIG_DIR, RAW_DIR
from poly_actor.ingest.common import to_epoch
from poly_actor.pairs import ET

ELECTION_YAML = CONFIG_DIR / "election.yaml"
RAW_ELECTION = RAW_DIR / "election"
CLEAN_ELECTION = CLEAN_DIR / "election"

SIGNALS = ("p_sen", "p_house", "p_sweep", "p_rr")
AI_SUBS = ("semis", "hyperscalers", "power_infra", "software")


@dataclass(frozen=True)
class Market:
    name: str
    event_id: int
    market_id: str
    question: str
    token_id: str
    created_s: int
    closed_s: int | None  # None = still open


@dataclass(frozen=True)
class Stock:
    ticker: str
    basket: str  # "ai" or "placebo"
    sub: str
    why: str


def et_midnight(day: str | date) -> int:
    """Epoch seconds of 00:00 America/New_York on an ISO date."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return int(datetime(d.year, d.month, d.day, tzinfo=ET).timestamp())


def et_wall(stamp: str) -> int:
    """Epoch seconds of an ET wall-clock string like 2026-11-03T18:00:00."""
    return int(datetime.fromisoformat(stamp).replace(tzinfo=ET).timestamp())


def _market(name: str, d: dict) -> Market:
    closed = d.get("closed")
    return Market(
        name=name,
        event_id=int(d["event_id"]),
        market_id=str(d["market_id"]),
        question=d["question"],
        token_id=str(d["yes_token_id"]),
        created_s=to_epoch(d["created"]),
        closed_s=to_epoch(closed) if closed else None,
    )


class ElectionConfig:
    def __init__(self, raw: dict):
        self.raw = raw
        st = raw["study"]
        self.data_start_s = et_midnight(st["data_start"])
        self.data_end_s = et_midnight(st["data_end"])
        self.vol_start_s = et_midnight(st["vol_start"])
        self.pm_start_s = to_epoch(st["pm_start"])
        self.pre_sample = (st["pre_sample_start"], st["pre_sample_end"])
        self.max_age = {
            "daily": int(raw["asof"]["daily_max_age_s"]),
            "hourly": int(raw["asof"]["hourly_max_age_s"]),
            "night": int(raw["asof"]["night_max_age_s"]),
        }
        w = raw["windows"]
        self.fid1_window = (to_epoch(w["fid1_start"]), to_epoch(w["fid1_end"]))
        self.fut5m_window = (et_midnight(w["futures_5m_start"]), et_midnight(w["futures_5m_end"]))
        self.h3_window = (et_wall(w["h3_start_et"]), et_wall(w["h3_end_et"]))
        self.h3_margin_s = int(w["h3_margin_min"]) * 60
        self.signals = {k: _market(k, v) for k, v in raw["signals"].items()}
        self.moratorium = {k: _market(k, v) for k, v in raw["moratorium"].items()}
        self.universe = [
            Stock(u["ticker"], u["basket"], u["sub"], u["why"]) for u in raw["universe"]
        ]
        self.controls = list(raw["controls"])
        self.futures = list(raw["futures"])
        self.vol_indices = list(raw["vol_indices"])

    def basket(self, name: str) -> list[str]:
        return [s.ticker for s in self.universe if s.basket == name]

    @property
    def equity_tickers(self) -> list[str]:
        return [s.ticker for s in self.universe] + self.controls

    def validate(self) -> None:
        """Hard structural checks (also run by the tests)."""
        ai, pl = self.basket("ai"), self.basket("placebo")
        if len(ai) != 29 or len(pl) != 29:
            raise ValueError(f"expected 29 + 29 names, got {len(ai)} + {len(pl)}")
        if set(ai) & set(pl) or len(set(ai + pl)) != 58:
            raise ValueError("ticker duplicated or present in both baskets")
        if {s.sub for s in self.universe if s.basket == "ai"} != set(AI_SUBS):
            raise ValueError("AI universe must have exactly the 4 pre-registered sub-baskets")
        if any(not s.why.strip() for s in self.universe):
            raise ValueError("every universe name needs a rationale")
        if set(self.signals) != set(SIGNALS):
            raise ValueError(f"signals must be {SIGNALS}")


def load_config(path: Path | None = None) -> ElectionConfig:
    with open(path or ELECTION_YAML, encoding="utf-8") as f:
        cfg = ElectionConfig(yaml.safe_load(f))
    cfg.validate()
    return cfg

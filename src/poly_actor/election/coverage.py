"""coverage.json: row counts, ranges, missing-odds shares, odds age, per-ticker session gaps.

Odds shares are reported twice: over every row ("all") and over rows inside the market's life
("in_life": instant between creation and close, or the study end for open markets), because rows
before creation and after the resolution are missing by construction.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from poly_actor.align.grid import bar_table, epoch_seconds
from poly_actor.election.config import SIGNALS, ElectionConfig

MINUTE_S = 60


def age_stats(age: pd.Series) -> dict[str, Any]:
    a = age.dropna()
    if not len(a):
        return {"n_valid": 0, "median_s": None, "p95_s": None}
    return {
        "n_valid": int(len(a)),
        "median_s": float(a.median()),
        "p95_s": float(np.percentile(a, 95)),
    }


def odds_stats(df: pd.DataFrame, ts_col: str, life: dict[str, tuple[int, int]]) -> dict[str, Any]:
    """Missing share and age stats per signal and overall, all rows and in-life rows."""
    inst = pd.Series(epoch_seconds(df[ts_col]), index=df.index)
    lo = df["signal"].map(lambda k: life[k][0])
    hi = df["signal"].map(lambda k: life[k][1])
    in_life = (inst >= lo) & (inst <= hi)

    def block(mask: pd.Series) -> dict[str, Any]:
        d = df[mask]
        return {
            "rows": int(len(d)),
            "missing_share": float(d["p"].isna().mean()) if len(d) else None,
            **age_stats(d["age_s"]),
        }

    out = {"all": block(pd.Series(True, index=df.index)), "in_life": block(in_life)}
    out["by_signal"] = {
        k: {"all": block(df["signal"] == k), "in_life": block((df["signal"] == k) & in_life)}
        for k in sorted(df["signal"].unique())
    }
    return out


def ticker_sessions(daily: pd.DataFrame, sessions: pd.DataFrame) -> dict[str, Any]:
    out = {}
    for tk, g in daily.groupby("ticker"):
        miss = g.loc[g["missing"], "session"]
        out[tk] = {
            "sessions": int((~g["missing"]).sum()),
            "expected": int(len(sessions)),
            "missing_sessions": [str(d) for d in miss],
        }
    return out


def ticker_bars(
    hourly: pd.DataFrame, sessions: pd.DataFrame, unmatched: pd.DataFrame
) -> dict[str, Any]:
    exp = bar_table(sessions).groupby("session").size()
    out = {}
    for tk, g in hourly.groupby("ticker"):
        have = g[~g["nan_bar"]].groupby("session").size().reindex(exp.index, fill_value=0)
        short = have[have < exp]
        out[tk] = {
            "bars": int((~g["nan_bar"]).sum()),
            "expected": int(exp.sum()),
            "nan_bars": int(g["nan_bar"].sum()),
            "unmatched_bars": int((unmatched["ticker"] == tk).sum()) if len(unmatched) else 0,
            "short_sessions": len(short),
            "first_short_sessions": [str(d) for d in short.index[:10]],
        }
    return out


def stamp_offsets(points: dict[str, pd.DataFrame], signals: list[str]) -> dict[str, Any]:
    """Seconds after the grid line at which fid-60 / fid-10 points are stamped (lesson 10)."""
    out = {}
    for fid in (60, 10):
        step = fid * MINUTE_S
        offs = np.concatenate(
            [
                (d.loc[d["fidelity"] == fid, "t"] % step).to_numpy()
                for k, d in points.items()
                if k in signals
            ]
        )
        out[f"fid{fid}"] = (
            {
                "n": int(len(offs)),
                "median_s": float(np.median(offs)),
                "p95_s": float(np.percentile(offs, 95)),
                "max_s": int(offs.max()),
            }
            if len(offs)
            else {"n": 0}
        )
    return out


def _span(df: pd.DataFrame, col: str) -> list:
    return [str(df[col].min()), str(df[col].max())] if len(df) else [None, None]


def coverage_report(
    cfg: ElectionConfig,
    tables: dict[str, pd.DataFrame],
    sessions: pd.DataFrame,
    unmatched: pd.DataFrame,
    points: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    life = {
        k: (m.created_s, m.closed_s or cfg.data_end_s)
        for k, m in {**cfg.signals, **cfg.moratorium}.items()
    }
    ts_col = {"daily": "session", "odds_daily": "close_ts", "hourly": "bar_end_ts"}
    ts_col |= {"odds_hourly": "bar_end_ts", "night_5m": "bar_end_ts", "vol_daily": "date"}
    ts_col["moratorium_daily"] = "close_ts"
    rep: dict[str, Any] = {"tables": {}}
    for name, df in tables.items():
        rep["tables"][name] = {"rows": int(len(df)), "range": _span(df, ts_col[name])}
    rep["odds_daily"] = odds_stats(tables["odds_daily"], "close_ts", life)
    rep["odds_hourly"] = odds_stats(tables["odds_hourly"], "bar_end_ts", life)
    night = tables["night_5m"]
    nights = {}
    for k in SIGNALS:
        w = night[night["in_window"] & (night["ticker"] == "NQ=F")]
        nights[k] = {
            "rows_in_window": int(len(w)),
            "missing_share": float(w[k].isna().mean()),
            **age_stats(w[f"age_{k}"]),
        }
    rep["night_5m_odds_NQ_in_window"] = nights
    mor = tables["moratorium_daily"]
    rep["moratorium_daily"] = {
        "rows": int(len(mor)),
        "n_states_median": float(mor["n_states"].median()) if len(mor) else None,
        "n_states_min": int(mor["n_states"].min()) if len(mor) else None,
        "missing_share_by_state": {s: float(mor[f"p_{s}"].isna().mean()) for s in cfg.moratorium},
    }
    rep["daily_by_ticker"] = ticker_sessions(tables["daily"], sessions)
    rep["hourly_by_ticker"] = ticker_bars(tables["hourly"], sessions, unmatched)
    rep["clob_stamp_offsets"] = stamp_offsets(points, list(cfg.signals))
    rep["sessions_expected"] = int(len(sessions))
    return rep

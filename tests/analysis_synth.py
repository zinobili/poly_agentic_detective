"""Panel-shaped synthetic data with a known answer for the step 6 method tests.

Sessions have 7 bars, every `early_every`-th session is an early close with 3 bars. Some
return cells are Yahoo holes (NaN), some rows are excluded (FOMC-like decision and roll bars,
stale PM quotes). The PM change x drives the first ticker's return at the planted lags
(`betas`: lag -> coefficient in SD units), within the session only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from poly_actor.analysis.sample import MAX_BARS, SIGNAL_SIGN, SessionGrid, lag

P = MAX_BARS


@dataclass
class Synth:
    sessions: np.ndarray
    exists: np.ndarray
    x: np.ndarray
    returns: dict[str, np.ndarray]
    event_hour: np.ndarray
    roll_hour: np.ndarray
    age: np.ndarray
    pair_id: str


def _sessions(n: int) -> np.ndarray:
    days, d = [], date(2025, 1, 6)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return np.array(days)


def _garch(rng: np.random.Generator, n_cells: int) -> np.ndarray:
    """GARCH(1,1) volatility path, unit long-run variance."""
    omega, alpha, beta = 0.05, 0.10, 0.85
    sig2 = np.empty(n_cells)
    s2, e_prev = 1.0, 0.0
    shocks = rng.standard_t(4, n_cells) / np.sqrt(2.0)
    for i in range(n_cells):
        s2 = omega + alpha * e_prev**2 + beta * s2
        sig2[i] = s2
        e_prev = np.sqrt(s2) * shocks[i]
    return np.sqrt(sig2)


def make(
    seed: int,
    n_sessions: int = 500,
    betas: dict[int, float] | None = None,
    tickers: tuple[str, ...] = ("TLT", "SPY", "XLF"),
    pair_id: str = "fed_decision",
    realistic: bool = False,
    early_every: int = 60,
    hole_rate: float = 0.005,
    fomc_every: int = 31,
    stale_rate: float = 0.005,
) -> Synth:
    rng = np.random.default_rng(seed)
    S = n_sessions
    exists = np.ones((S, P), dtype=bool)
    early = np.arange(S) % early_every == early_every - 1
    exists[early, 3:] = False
    vol = _garch(rng, S * P).reshape(S, P) if realistic else np.ones((S, P))
    if realistic:  # sparse PM changes: 70% zeros, t(3) jumps; shared volatility
        jump = rng.standard_t(3, (S, P)) / np.sqrt(3.0)
        x = np.where(rng.random((S, P)) < 0.7, 0.0, jump) * vol
    else:
        x = rng.standard_normal((S, P))
    x = np.where(exists, x, np.nan)
    sd_x = np.nanstd(x)
    betas = betas or {}
    returns = {}
    for i, t in enumerate(tickers):
        noise = (
            rng.standard_t(4, (S, P)) / np.sqrt(2.0) if realistic else rng.standard_normal((S, P))
        ) * vol
        y = noise * np.sqrt(max(1.0 - sum(b * b for b in betas.values()), 0.0)) if i == 0 else noise
        if i == 0:
            for k, b in betas.items():
                y = y + b * np.nan_to_num(lag(x, k, np.nan)) / sd_x
        y = np.where(exists, y, np.nan)
        holes = rng.random((S, P)) < hole_rate
        returns[t] = np.where(holes, np.nan, y)
    event_hour = np.zeros((S, P), dtype=bool)
    roll_hour = np.zeros((S, P), dtype=bool)
    fomc = (np.arange(S) % fomc_every == 7) & ~early
    event_hour[fomc, 4] = True
    roll_hour[fomc, 5] = True
    age = np.where(rng.random((S, P)) < stale_rate, 2400.0, 594.0)
    return Synth(_sessions(S), exists, x, returns, event_hour, roll_hour, age, pair_id)


def to_grid(sy: Synth) -> SessionGrid:
    """The SessionGrid `sample.build_grid` would produce from `to_panel(sy)` (fast path)."""
    stock_ok = sy.exists & np.all([~np.isnan(r) for r in sy.returns.values()], axis=0)
    pm_ok = sy.exists & ~np.isnan(sy.x) & ~sy.event_hour & ~sy.roll_hour & (sy.age <= 1800)
    ts = _ts_end(sy)
    return SessionGrid(
        sessions=sy.sessions,
        ts_end=ts,
        exists=sy.exists.copy(),
        stock_ok=stock_ok,
        pm_ok=pm_ok,
        x=sy.x.copy(),
        returns={k: v.copy() for k, v in sy.returns.items()},
        event_id=np.where(sy.exists, "E", None).astype(object),
    )


def _ts_end(sy: Synth) -> np.ndarray:
    base = np.array(
        [int(pd.Timestamp(d, tz="UTC").timestamp()) + 14 * 3600 + 1800 for d in sy.sessions]
    )
    ts = base[:, None] + 3600 * (np.arange(P)[None, :] + 1)
    ts[:, P - 1] -= 1800  # the 15:30 ET bar ends at the close
    return np.where(sy.exists, ts, -1)


def to_panel(sy: Synth) -> pd.DataFrame:
    """Session-bar rows in the step 4 panel schema (only the columns step 6 reads)."""
    s_idx, p_idx = np.nonzero(sy.exists)
    ts = _ts_end(sy)[s_idx, p_idx]
    sign = SIGNAL_SIGN[sy.pair_id]
    frame = pd.DataFrame(
        {
            "ts_end": pd.to_datetime(ts, unit="s", utc=True),
            "ts_start": pd.to_datetime(ts - 3600, unit="s", utc=True),
            "is_session_bar": True,
            "is_session_open": p_idx == 0,
            "session": sy.sessions[s_idx],
            "event_id": "E",
            "signal_level": 1.0,
            "signal_change": sy.x[s_idx, p_idx] / sign,
            "roll_hour": sy.roll_hour[s_idx, p_idx],
            "event_hour": sy.event_hour[s_idx, p_idx],
            "pm_obs_age_s": sy.age[s_idx, p_idx],
            "clipped_p_gt1": False,
            "outage_mask": False,
        }
    )
    rng = np.random.default_rng(len(sy.sessions))
    is_open = (p_idx == 0).astype(bool)
    for t, r in sy.returns.items():
        frame[f"ret_{t}"] = r[s_idx, p_idx]
        frame[f"overnight_gap_{t}"] = np.where(
            is_open, 0.003 * rng.standard_normal(len(s_idx)), np.nan
        )
    frame["pm_overnight_change"] = np.where(is_open, rng.standard_normal(len(s_idx)), np.nan)
    frame["pm_overnight_n_missing"] = 0
    rets = [f"ret_{t}" for t in sy.returns]
    frame["both_trading"] = frame[rets].notna().all(axis=1) & frame["signal_change"].notna()
    return frame


# ---------------------------------------------------------------- whole-pair inputs


def fed_panel(seed: int = 0, n_sessions: int = 300, betas=None) -> pd.DataFrame:
    return to_panel(make(seed, n_sessions=n_sessions, betas=betas or {2: 0.1}))


def btc_panel(seed: int = 0, n_sessions: int = 300):
    """BTC-shaped panel and a spot as-of function (hourly random walk)."""
    sy = make(
        seed,
        n_sessions=n_sessions,
        tickers=("IBIT", "COIN", "MSTR", "XLU"),
        pair_id="bitcoin_monthly_ladder",
        fomc_every=1000,
    )
    panel = to_panel(sy)
    t0 = int(panel["ts_end"].min().timestamp()) - 10 * 86400
    n_hours = (int(panel["ts_end"].max().timestamp()) - t0) // 3600 + 48
    price = 50000.0 * np.exp(
        np.cumsum(0.005 * np.random.default_rng(seed).standard_normal(n_hours))
    )

    def spot_at(instants: np.ndarray) -> np.ndarray:
        idx = (np.asarray(instants, dtype="int64") - t0) // 3600
        return price[np.clip(idx, 0, n_hours - 1)]

    return panel, spot_at


def cpi_inputs(seed: int = 0, n_usable: int = 12, validation_ok: bool = True):
    """CPI-shaped panel, release table and placebo table (levels only)."""
    rng = np.random.default_rng(seed)
    sy = make(seed, n_sessions=420, tickers=("TLT", "QQQ"), pair_id="us_cpi_inflation")
    panel = to_panel(sy)
    days = list(sy.sessions)
    rel = days[20::20][:20]
    usable = np.arange(len(rel)) < n_usable
    level1 = 2.5 + 0.3 * rng.standard_normal(len(rel))
    center = np.round(level1, 1) if validation_ok else np.round(level1, 1) + 0.5
    tab = pd.DataFrame(
        {
            "event_id": [f"E{i}" for i in range(len(rel))],
            "session": rel,
            "resolved": True,
            "winning_center": center,
            "valid1": usable,
            "level1": level1,
            "usable": usable,
            "proxy": np.where(usable, 0.05 * rng.standard_normal(len(rel)), np.nan),
            "close_proxy": np.where(usable, 0.05 * rng.standard_normal(len(rel)), np.nan),
        }
    )
    others = [d for d in days[5:] if d not in set(rel)][::3]
    placebo = pd.DataFrame(
        {"session": others, "usable": True, "proxy": 0.05 * rng.standard_normal(len(others))}
    )
    return panel, tab, placebo


def recession_panel(seed: int = 0) -> pd.DataFrame:
    sy = make(seed, n_sessions=300, tickers=("SPY", "IWM", "TLT"), pair_id="us_recession")
    panel = to_panel(sy)
    change = 0.01 * np.random.default_rng(seed).standard_normal(len(panel))
    panel["signal_change"] = change
    panel["signal_level"] = np.clip(0.3 + np.cumsum(change), 0.02, 0.98)
    return panel


def all_jobs() -> dict:
    """Phase-1 jobs for the four pairs on synthetic panels (seed 0)."""
    from poly_actor.analysis import run

    panel, spot = btc_panel(0)
    cpi_panel, tab, placebo_tab = cpi_inputs(0)
    return {
        "fed_decision": run.fed_job(fed_panel(0), {"fomc": set(), "cpi": set()}),
        "bitcoin_monthly_ladder": run.btc_job(panel, spot),
        "us_cpi_inflation": run.cpi_job(cpi_panel, tab, placebo_tab),
        "us_recession": run.recession_job(recession_panel(0)),
    }

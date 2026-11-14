"""Exploratory blocks E1, E2, E3, E5 (labelled "exploratory" in every output). Pure functions."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from poly_actor.analysis import models
from poly_actor.election import stats as st
from poly_actor.election.config import E5_START, ELECTION_DAY, PAST_ELECTIONS

LABEL = "exploratory"
ROLL = 60  # rows (complete-case sessions) per rolling window
LAST = 30  # rows in the "last 30 sessions" interaction
Z90 = 1.645  # two-sided 90% normal z of the E1 band (as specified; not recomputed from CI_LEVEL)
TRADING_DAYS_PER_YEAR = 252.0  # annualised VXN -> one-day implied move
MIN_E3_ROWS = 5  # E3 reports a correlation only with at least this many days
ELECTIONS = (*PAST_ELECTIONS, ELECTION_DAY)
REL_DAYS = (-20, 7)


def e1_rolling(dates: list[str], y: np.ndarray, x: np.ndarray, Z: np.ndarray) -> dict:
    """Rolling 60-row b with a +-1.645 se band (HAC 5), and b in the last 30 rows vs before
    (interaction dP x 1[last 30], HAC 5)."""
    rows = []
    for end in range(ROLL, len(y) + 1):
        sl = slice(end - ROLL, end)
        try:
            f = st.beta_fit(y[sl], x[sl], Z[sl])
        except np.linalg.LinAlgError:  # e.g. dP constant over the window
            rows.append({"date": dates[end - 1], "b10_pct": np.nan, "lo": np.nan, "hi": np.nan})
            continue
        b, se = f.b * st.PER_10PTS_PCT, f.se * st.PER_10PTS_PCT
        rows.append({"date": dates[end - 1], "b10_pct": b, "lo": b - Z90 * se, "hi": b + Z90 * se})
    last = np.zeros(len(y))
    last[-LAST:] = 1.0
    f = st.beta_fit(y, x, np.column_stack([x * last, last, Z]))
    X = st.design(x, np.column_stack([x * last, last, Z]))
    fit = models.ols(X, y, cov="hac", hac_lag=st.HAC_LAG_DAILY)
    w = np.zeros(X.shape[1])
    w[2] = 1.0
    lt = models.lin_test(fit, w, level=st.CI_LEVEL)
    k = st.PER_10PTS_PCT
    return {
        "label": LABEL,
        "window": ROLL,
        "series": "e1_rolling",
        "rolling": rows,
        "before_b10_pct": f.b * k,
        "last30_minus_before_b10_pct": lt.estimate * k,
        "last30_minus_before_ci10_pct": [lt.ci_low * k, lt.ci_high * k],
        "p_hac": lt.p_two,
        "last30_start": dates[-LAST],
    }


def e2_vol(vol: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Vol-ratio paths, trading days -20..+7 around each election, plus the VXN-implied one-day
    move on election day vs the realised Nasdaq-100 move the next session."""
    w = vol.pivot_table(index="date", columns="ticker", values="close", aggfunc="first")
    w.index = [str(d) for d in w.index]
    w = w.sort_index()
    m = pd.DataFrame(index=w.index)
    m["vix9d_over_vix"] = w["^VIX9D"] / w["^VIX"]
    m["vix_over_vix3m"] = w["^VIX"] / w["^VIX3M"]
    m["vxn_minus_vix"] = w["^VXN"] - w["^VIX"]
    parts, moves = [], {}
    days = list(w.index)
    for e in ELECTIONS:
        if e not in days:
            moves[e] = None
            continue
        i0 = days.index(e)
        lo, hi = max(0, i0 + REL_DAYS[0]), min(len(days) - 1, i0 + REL_DAYS[1])
        seg = m.iloc[lo : hi + 1].copy()
        seg["rel_day"] = np.arange(lo, hi + 1) - i0
        seg["election"] = e
        seg["date"] = seg.index
        parts.append(seg.reset_index(drop=True))
        nxt = days[i0 + 1] if i0 + 1 < len(days) else None
        implied = w.loc[e, "^VXN"] / math.sqrt(TRADING_DAYS_PER_YEAR)
        real = (
            100.0 * math.log(w.loc[nxt, "^NDX"] / w.loc[e, "^NDX"])
            if nxt and pd.notna(w.loc[nxt, "^NDX"])
            else None
        )
        moves[e] = {
            "implied_1d_pct": float(implied),
            "realised_next_day_pct": real,
            "next_day": nxt,
            "ratio_abs_realised_to_implied": abs(real) / implied if real is not None else None,
        }
    series = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return {
        "label": LABEL,
        "series": "e2_vol",
        "moves": moves,
        "elections": list(ELECTIONS),
    }, series


def e3_moratorium(
    mor: pd.DataFrame, power_minus_xlu: pd.Series, gen: np.random.Generator
) -> tuple[dict, pd.DataFrame]:
    """Daily mean moratorium dP vs (power/DC sub-basket - XLU) log return, same session."""
    m = mor.assign(session=mor["session"].astype(str)).set_index("session")["mean_dp"]
    df = pd.DataFrame({"mean_dp": m, "excess_ret": power_minus_xlu.reindex(m.index)}).dropna()
    out = {"label": LABEL, "series": "e3_scatter", "n": int(len(df))}
    if len(df) >= MIN_E3_ROWS:
        rho = models.spearman(df["mean_dp"].to_numpy(), df["excess_ret"].to_numpy())
        p = st.label_perm(df["mean_dp"].to_numpy(), df["excess_ret"].to_numpy(), gen)
        out |= {"rho": rho, "p_two": p["p_two"], "ci90": p["ci90"]}
    df = df.reset_index().rename(columns={"index": "session"})
    return out, df


def e5_drift(
    names: list[str], b: np.ndarray, ar_daily: pd.DataFrame, start: str = E5_START
) -> tuple[dict, pd.DataFrame]:
    """Top vs bottom tercile (by pre-election b_i) cumulative abnormal return from `start`."""
    rank = pd.Series(b, index=names).rank(method="first")
    terc = pd.qcut(rank, 3, labels=["bottom", "middle", "top"])
    top = [n for n in names if terc[n] == "top"]
    bot = [n for n in names if terc[n] == "bottom"]
    a = ar_daily[ar_daily.index >= start]
    car = pd.DataFrame(
        {"top": a[top].mean(axis=1).cumsum(), "bottom": a[bot].mean(axis=1).cumsum()}
    )
    car["top_minus_bottom"] = car["top"] - car["bottom"]
    car.index.name = "session"
    last = car.iloc[-1] if len(car) else None
    out = {
        "label": LABEL,
        "series": "e5_car",
        "top": top,
        "bottom": bot,
        "start": start,
        "end": car.index[-1] if len(car) else None,
        "car_top_minus_bottom_pct": float(100 * last["top_minus_bottom"])
        if last is not None
        else None,
        "car_top_minus_bottom_ex_event_day_pct": float(
            100 * (last["top_minus_bottom"] - car["top_minus_bottom"].iloc[0])
        )
        if last is not None
        else None,
    }
    return out, car.reset_index()

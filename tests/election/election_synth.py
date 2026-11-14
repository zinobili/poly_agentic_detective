"""Synthetic step 8 panels with planted effects (same schemas, real XNYS sessions and bar ends).

Daily: r_i = b_i dP_sen + 1.0 r_RSP + 0.2 r_TLT + noise, close-to-close; dP is the change of the
as-of P over the same close-to-close window (P is built per session close, so timing matches the
pipeline). Hourly: same per bar (dP of the same bar end, or of `h_lag` bars earlier within the
session). Night: 5-minute futures returns = g dP_{t - n_lag} + noise. Odds before 2025-07-18 are
missing (the real thin start). After 2026-11-04 10:54 UTC P_sen is resolved at 0.9995.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.core.timegrid.grid import bar_table
from poly_actor.studies.election.config import SIGNALS, ElectionConfig
from poly_actor.studies.election.panel import sessions_in

ODDS_START = "2025-07-18"
RESOLVE = pd.Timestamp("2026-11-04T10:54:00Z")


def _p_path(rng, n, start=0.4, sd=0.02):
    """Logit random walk (never sticks at a bound), rounded to the 0.005 tick."""
    lg = np.log(start / (1 - start)) + np.cumsum(rng.standard_t(4, n) * sd * 4 / 1.4)
    return np.round(1 / (1 + np.exp(-lg)) / 0.005) * 0.005


def make_panels(
    cfg: ElectionConfig,
    out: Path,
    seed: int = 0,
    b_ai: float | np.ndarray = 0.0,
    b_pl: float | np.ndarray = 0.0,
    noise: float = 0.012,
    h_gain: float = 0.0,
    h_lag: int = 0,
    n_gain: float = 0.0,
    n_lag: int = 0,
    event_xs: float = 0.0,
) -> dict:
    """Write the 7 panels + coverage.json to `out`; returns the planted parameters."""
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    sess = sessions_in(cfg)
    S = len(sess)
    days = [str(d) for d in sess["session"]]
    close_ts = pd.to_datetime(sess["close_s"], unit="s", utc=True)
    has_odds = np.array([d >= ODDS_START for d in days])
    ev = days.index("2026-11-04")
    # odds daily
    odds, P = [], {}
    for k, sig in enumerate(SIGNALS):
        p = _p_path(rng, S, 0.3 + 0.1 * k)
        p[ev:] = 0.9995 if sig != "p_rr" else 0.0005
        p[ev - 1] = 0.745 if sig == "p_sen" else p[ev - 1]
        p = np.where(has_odds, p, np.nan)
        P[sig] = p
        dp = pd.Series(p).diff().to_numpy()
        odds.append(
            pd.DataFrame(
                {
                    "session": sess["session"],
                    "close_ts": close_ts,
                    "signal": sig,
                    "p": p,
                    "age_s": 590.0,
                    "resolved": np.arange(S) >= ev,
                    "dp": dp,
                }
            )
        )
    odds_daily = pd.concat(odds, ignore_index=True)
    dps = np.nan_to_num(pd.Series(P["p_sen"]).diff().to_numpy())
    # daily returns
    ai, pl = cfg.basket("ai"), cfg.basket("placebo")
    rsp = rng.normal(0, 0.008, S)
    tlt = rng.normal(0, 0.006, S)
    bai = np.broadcast_to(np.asarray(b_ai, dtype=float), (len(ai),))
    bpl = np.broadcast_to(np.asarray(b_pl, dtype=float), (len(pl),))
    rets = {"RSP": rsp, "TLT": tlt}
    for tk in ("SPY", "QQQ", "SMH", "XLU"):
        rets[tk] = rsp + rng.normal(0, 0.004, S)
    for tk, b in [*zip(ai, bai, strict=True), *zip(pl, bpl, strict=True)]:
        r = b * dps + rsp + 0.2 * tlt + rng.normal(0, noise, S)
        r[ev] += event_xs * b
        rets[tk] = r
    rows = []
    for tk, r in rets.items():
        r = r.copy()
        r[0] = np.nan
        px = 100 * np.exp(np.nancumsum(np.nan_to_num(r)))
        op = np.r_[np.nan, px[:-1]] * np.exp(rng.normal(0, 0.002, S))
        rows.append(
            pd.DataFrame(
                {
                    "session": sess["session"],
                    "close_ts": close_ts,
                    "ticker": tk,
                    "adj_close": px,
                    "adj_open": op,
                    "ret": r,
                    "missing": False,
                }
            )
        )
    daily = pd.concat(rows, ignore_index=True)
    # hourly
    bars = bar_table(sess)
    end = pd.to_datetime(bars["end_s"], unit="s", utc=True)
    hp = pd.DataFrame({"session": bars["session"], "bar_end_ts": end})
    ph = np.clip(0.5 + np.cumsum(rng.normal(0, 0.004, len(bars))), 0.02, 0.98)
    hp["p"] = ph
    hp["dp"] = hp.groupby("session")["p"].diff()
    xl = hp.groupby("session")["dp"].shift(h_lag).fillna(0.0).to_numpy()
    h_rsp = rng.normal(0, 0.002, len(bars))
    h_tlt = rng.normal(0, 0.0015, len(bars))
    hrows = []
    for tk in ai + pl + ["RSP", "TLT", "SPY", "QQQ", "SMH", "XLU"]:
        if tk == "RSP":
            r = h_rsp
        elif tk == "TLT":
            r = h_tlt
        else:
            g = h_gain if tk in ai else 0.0
            r = g * xl + h_rsp + 0.1 * h_tlt + rng.normal(0, 0.003, len(bars))
        hrows.append(
            pd.DataFrame(
                {
                    "ticker": tk,
                    "session": bars["session"],
                    "bar_start_ts": pd.to_datetime(bars["start_s"], unit="s", utc=True),
                    "bar_end_ts": end,
                    "open": 100.0,
                    "close": 100 * np.exp(r),
                    "ret": r,
                    "nan_bar": False,
                }
            )
        )
    hourly = pd.concat(hrows, ignore_index=True)
    odds_hourly = pd.concat(
        [
            hp.assign(signal=s, age_s=590.0, resolved=False)[
                ["session", "bar_end_ts", "signal", "p", "age_s", "resolved", "dp"]
            ]
            for s in SIGNALS
        ],
        ignore_index=True,
    )
    # night 5m (window 18:00 ET 3 Nov = 23:00Z -> 09:30 ET 4 Nov = 14:30Z, margin 30 min)
    ends = pd.date_range("2026-11-03T22:35:00Z", "2026-11-04T15:00:00Z", freq="5min")
    n = len(ends)
    pn = np.clip(0.745 + np.cumsum(rng.normal(0, 0.004, n)), 0.02, 0.98)
    res = ends >= RESOLVE
    pn[res] = pn[~res][-1]
    dpn = np.r_[np.nan, np.diff(pn)]
    xn = pd.Series(np.nan_to_num(dpn)).shift(n_lag).fillna(0.0).to_numpy()
    nrows = []
    for tk, g in (("NQ=F", n_gain), ("ES=F", 0.0), ("RTY=F", 0.0)):
        r = g * xn + rng.normal(0, 0.0008, n)
        d = pd.DataFrame(
            {
                "ticker": tk,
                "bar_start_ts": ends - pd.Timedelta(minutes=5),
                "bar_end_ts": ends,
                "in_window": (ends > pd.Timestamp("2026-11-03T23:00:00Z"))
                & (ends <= pd.Timestamp("2026-11-04T14:30:00Z")),
                "open": 100.0,
                "close": 100 * np.exp(r),
                "ret": r,
            }
        )
        for sig in SIGNALS:
            d[sig] = pn
            d[f"age_{sig}"] = 41.0
            d[f"d{sig}"] = dpn
            d[f"res_{sig}"] = res
        nrows.append(d)
    night = pd.concat(nrows, ignore_index=True)
    # vol
    vdays = pd.bdate_range("2018-01-02", "2026-11-12")
    vrows = []
    for tk, lvl in (
        ("^VIX", 18),
        ("^VIX9D", 17),
        ("^VIX3M", 20),
        ("^VXN", 22),
        ("^VVIX", 90),
        ("^NDX", 15000),
    ):
        v = lvl * np.exp(np.cumsum(rng.normal(0, 0.01, len(vdays))))
        vrows.append(pd.DataFrame({"date": vdays.date, "ticker": tk, "close": v}))
    vol = pd.concat(vrows, ignore_index=True)
    # moratorium
    m0 = days.index("2026-09-29")
    mor = pd.DataFrame({"session": sess["session"][m0:].to_numpy()})
    mor["close_ts"] = close_ts[m0:].to_numpy()
    mor["mean_p"] = np.clip(0.4 + np.cumsum(rng.normal(0, 0.02, len(mor))), 0, 1)
    mor["n_states"] = 7
    mor["mean_dp"] = mor["mean_p"].diff()
    tables = {
        "daily": daily,
        "odds_daily": odds_daily,
        "hourly": hourly,
        "odds_hourly": odds_hourly,
        "night_5m": night,
        "vol_daily": vol,
        "moratorium_daily": mor,
    }
    for k, df in tables.items():
        df.to_parquet(out / f"{k}.parquet", index=False)
    (out / "coverage.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    return {"b_ai": bai, "b_pl": bpl, "event_index": ev, "days": days}

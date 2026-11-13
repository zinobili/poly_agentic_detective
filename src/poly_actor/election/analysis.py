"""Step 9: the pre-registered election-study analysis (docs/election/preregistration.md).

`analyse(clean_dir, out_dir)` reads the step 8 panels, runs H1, H2, H2b, H3, H4, H5 and the
exploratory blocks, applies the verdict table mechanically and writes `results.json` plus chart
series (`series/*.csv`). `publish` copies that bundle to `reports/election/`.

Data rules: daily returns are adjusted close-to-close log returns; dP is the as-of change over
the same close-to-close window (A1: after a market's close its price is the last traded price).
A day with any missing input is dropped, never filled. Baskets are equal-weight means of log
returns and require every member (no member is missing in the real data). Seeds are fixed
(`stats.SEED`) and each test has its own stream.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.election import explore as ex
from poly_actor.election import intraday as itd
from poly_actor.election import stats as st
from poly_actor.election.bundle import (
    INSTRUMENTS,
    basket,
    checklist,
    clean,
    context_series,
    headline,
    night_series,
    publish,
    write,
)
from poly_actor.election.config import AI_SUBS, SIGNALS, ElectionConfig

H2_EST_END = "2026-10-30"
EVENT_DAY = "2026-11-04"
ELECTION_DAY = "2026-11-03"
W3_END = "2026-11-06"
E5_START = "2026-11-04"


# ---------------------------------------------------------------- inputs


def load_panels(clean_dir: Path) -> dict[str, pd.DataFrame | dict]:
    names = ["daily", "odds_daily", "odds_hourly", "hourly", "night_5m", "vol_daily"]
    p: dict = {n: pd.read_parquet(clean_dir / f"{n}.parquet") for n in names}
    p["moratorium_daily"] = pd.read_parquet(clean_dir / "moratorium_daily.parquet")
    cov = clean_dir / "coverage.json"
    p["coverage"] = json.loads(cov.read_text(encoding="utf-8")) if cov.exists() else {}
    return p


def daily_frame(daily: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """Index = ISO session; ret columns per ticker, then p_/dp_/dlogit_ per signal."""
    d = daily.assign(session=daily["session"].astype(str))
    D = d.pivot(index="session", columns="ticker", values="ret")
    o = odds.assign(session=odds["session"].astype(str)).sort_values(["signal", "session"])
    o["lg"] = st.logit(o["p"].to_numpy())
    o["dlogit"] = o.groupby("signal")["lg"].diff()
    for sig in SIGNALS:
        g = o[o["signal"] == sig].set_index("session")
        D[f"p_{sig}"] = g["p"].reindex(D.index)
        D[f"dp_{sig}"] = g["dp"].reindex(D.index)
        D[f"dlogit_{sig}"] = g["dlogit"].reindex(D.index)
    return D.sort_index()


def complete(cols: dict[str, pd.Series]) -> pd.DataFrame:
    """Rows where every column is present (missing dP days are dropped, never filled)."""
    return pd.DataFrame(cols).dropna()


def window(D: pd.DataFrame, lo: str, hi: str) -> pd.DataFrame:
    return D[(D.index >= lo) & (D.index <= hi)]


# ---------------------------------------------------------------- H1 / H5 / robustness


def _Z(df: pd.DataFrame, cols: list[str]) -> np.ndarray | None:
    return df[cols].to_numpy() if cols else None


def h1_row(df: pd.DataFrame, y: str, x: str, ctrls: list[str], gen_off: int) -> dict:
    row = st.h1_block(df[y].to_numpy(), df[x].to_numpy(), _Z(df, ctrls), st.rng(gen_off))
    row["first"], row["last"] = df.index[0], df.index[-1]
    return row


def run_h1(S: pd.DataFrame, cfg: ElectionConfig) -> tuple[dict, list[dict], dict, pd.DataFrame]:
    ai, pl = cfg.basket("ai"), cfg.basket("placebo")
    cols = {
        "ai": basket(S, ai),
        "placebo": basket(S, pl),
        "dp": S["dp_p_sen"],
        "RSP": S["RSP"],
        "TLT": S["TLT"],
    }
    base = complete(cols)
    base["diff"] = base["ai"] - base["placebo"]
    c = ["RSP", "TLT"]
    h1 = {
        "ai": h1_row(base, "ai", "dp", c, 1),
        "placebo": h1_row(base, "placebo", "dp", c, 2),
        "diff": h1_row(base, "diff", "dp", c, 3),
        "signal": "p_sen",
        "controls": c,
        "hac_lag": st.HAC_LAG_DAILY,
        "dropped_sessions_missing_dp": [s for s in S.index if pd.isna(S.loc[s, "dp_p_sen"])],
    }
    # robustness (composite)
    rob = [{"name": "baseline (RSP, TLT, dP_sen)", **_rob(h1["ai"])}]
    spec = [
        ("SPY instead of RSP", {"x": S["dp_p_sen"], "c1": S["SPY"], "c2": S["TLT"]}, 11),
        ("no controls", {"x": S["dp_p_sen"]}, 12),
        (
            "logit change of p_sen (per +1 logit, not per 10 pts)",
            {"x": S["dlogit_p_sen"], "c1": S["RSP"], "c2": S["TLT"]},
            13,
        ),
        ("E4 p_house", {"x": S["dp_p_house"], "c1": S["RSP"], "c2": S["TLT"]}, 14),
        ("E4 p_sweep", {"x": S["dp_p_sweep"], "c1": S["RSP"], "c2": S["TLT"]}, 15),
        ("E4 p_rr (R Senate, R House)", {"x": S["dp_p_rr"], "c1": S["RSP"], "c2": S["TLT"]}, 16),
    ]
    for name, cols_r, off in spec:
        df = complete({"y": basket(S, ai), **cols_r})
        ctr = [k for k in ("c1", "c2") if k in cols_r]
        r = h1_row(df, "y", "x", ctr, off)
        if name.startswith("logit"):
            r["unit"] = "per +1 logit (b10 fields are b x 10)"
        rob.append({"name": name, **_rob(r)})
    top5 = base["dp"].abs().sort_values(ascending=False, kind="stable").index[:5]
    df = base.drop(index=top5)
    rob.append(
        {
            "name": "drop 5 largest |dP| days",
            **_rob(h1_row(df, "ai", "dp", c, 17)),
            "dropped": list(top5),
        }
    )
    # H5 sub-baskets
    subs = {s: [x.ticker for x in cfg.universe if x.sub == s] for s in AI_SUBS}
    sub_cols = {s: basket(S, n) for s, n in subs.items()}
    sdf = complete({**sub_cols, "dp": S["dp_p_sen"], "RSP": S["RSP"], "TLT": S["TLT"]})
    h5_rows = {s: h1_row(sdf, s, "dp", c, 20 + i) for i, s in enumerate(AI_SUBS)}
    rej, adj = st.models.bh([h5_rows[s]["p_perm"] for s in AI_SUBS], 0.05)
    for i, s in enumerate(AI_SUBS):
        h5_rows[s] |= {"bh_reject": bool(rej[i]), "p_bh": float(adj[i]), "names": subs[s]}
    wald = st.wald_equal_b(
        sdf[list(AI_SUBS)].to_numpy(), sdf["dp"].to_numpy(), sdf[c].to_numpy(), st.HAC_LAG_DAILY
    )
    wald["b10_pct"] = [v * st.PER_10PTS_PCT for v in wald.pop("b")]
    h5 = {
        "label": "secondary",
        "family": "BH over 4 sub-baskets (q = 0.05) on permutation p",
        "subs": h5_rows,
        "wald_equal": wald,
    }
    return h1, rob, h5, base


def _rob(r: dict) -> dict:
    keys = ["b10_pct", "ci10_pct", "se10_pct", "p_hac", "p_perm", "n", "mde10_pct", "unit"]
    return {k: r[k] for k in keys if k in r}


# ---------------------------------------------------------------- H2 / H2b / E5


def event_returns(daily: pd.DataFrame, tickers: list[str]) -> dict[str, pd.Series]:
    """Per ticker, log return over the three pre-registered event windows."""
    d = daily.assign(session=daily["session"].astype(str)).set_index(["session", "ticker"])
    c3 = d.loc[ELECTION_DAY, "adj_close"].reindex(tickers)
    o4 = d.loc[EVENT_DAY, "adj_open"].reindex(tickers)
    w1 = d.loc[EVENT_DAY, "ret"].reindex(tickers)
    sess = sorted(s for s in d.index.get_level_values(0).unique() if EVENT_DAY <= s <= W3_END)
    w3 = sum(d.loc[s, "ret"].reindex(tickers) for s in sess)
    return {
        "close3_close4": w1,
        "close3_open4": np.log(o4 / c3),
        "close3_close6": w3,
    }


def h2_estimation(D: pd.DataFrame, cfg: ElectionConfig, names: list[str]) -> pd.DataFrame:
    """Complete-case estimation rows for per-stock b_i: sessions in [pre start, 2026-10-30]."""
    E = window(D, cfg.pre_sample[0], H2_EST_END)
    return complete(
        {**{n: E[n] for n in names}, "dp": E["dp_p_sen"], "RSP": E["RSP"], "TLT": E["TLT"]}
    )


def run_h2(D: pd.DataFrame, daily: pd.DataFrame, cfg: ElectionConfig) -> tuple[dict, dict]:
    groups = {"ai": cfg.basket("ai"), "placebo": cfg.basket("placebo")}
    groups["pooled58"] = groups["ai"] + groups["placebo"]
    ev = event_returns(daily, groups["pooled58"] + ["RSP", "TLT"])
    out: dict = {"est_end": H2_EST_END, "windows": list(ev), "primary_window": "close3_close4"}
    out["event_dp_sen"] = float(D.loc[EVENT_DAY, "dp_p_sen"])
    out["groups"] = {}
    betas = {}
    for gi, (g, names) in enumerate(groups.items()):
        E = h2_estimation(D, cfg, names)
        B = st.per_stock_betas(
            E[names].to_numpy(), E["dp"].to_numpy(), E[["RSP", "TLT"]].to_numpy()
        )
        betas[g] = (names, B)
        blk = {
            "n_est": int(len(E)),
            "est_first": E.index[0],
            "est_last": E.index[-1],
            "per_stock": [],
            "windows": {},
        }
        for wi, (w, r) in enumerate(ev.items()):
            z = np.array([r["RSP"], r["TLT"]])
            ar = st.abnormal(r[names].to_numpy(), B, z)
            res = st.label_perm(B[1], ar, st.rng(100 + 10 * gi + wi))
            res["mean_ar_pct"] = float(100 * ar.mean())
            blk["windows"][w] = res
            if w == "close3_close4":
                blk["per_stock"] = [
                    {
                        "ticker": n,
                        "b10_pct": float(B[1, i] * st.PER_10PTS_PCT),
                        "c_rsp": float(B[2, i]),
                        "d_tlt": float(B[3, i]),
                        "ar_pct": float(100 * ar[i]),
                    }
                    for i, n in enumerate(names)
                ]
        out["groups"][g] = blk
    return out, betas


def run_h2b(S: pd.DataFrame, cfg: ElectionConfig) -> dict:
    out = {"warmup": st.WARMUP, "top_quantile": st.TOP_Q}
    for g in ("ai", "placebo"):
        names = cfg.basket(g)
        E = complete(
            {**{n: S[n] for n in names}, "dp": S["dp_p_sen"], "RSP": S["RSP"], "TLT": S["TLT"]}
        )
        days = st.walk_forward(
            E["dp"].to_numpy(), E[names].to_numpy(), E[["RSP", "TLT"]].to_numpy()
        )
        for d in days:
            d["date"] = E.index[d["row"]]
            d["first_est"], d["last_est"] = E.index[0], E.index[d["row"] - 1]
        out[g] = {"days": days, **st.one_sided_t([d["signed_rho"] for d in days])}
    return out


def ar_daily(D: pd.DataFrame, names: list[str], B: np.ndarray, lo: str, hi: str) -> pd.DataFrame:
    W = window(D, lo, hi)
    z = W[["RSP", "TLT"]].to_numpy()
    return pd.DataFrame(W[names].to_numpy() - z @ B[2:, :], index=W.index, columns=names)


# ---------------------------------------------------------------- H4


def run_h4(p: dict, cfg: ElectionConfig) -> dict:
    lo, hi = cfg.pre_sample
    h = p["hourly"].assign(session=p["hourly"]["session"].astype(str))
    h = h[(h["session"] >= lo) & (h["session"] <= hi)]
    w = h.pivot_table(index="bar_end_ts", columns="ticker", values="ret", aggfunc="first")
    comp = w[cfg.basket("ai")].mean(axis=1, skipna=False)
    resid, coef = itd.residualise(comp.to_numpy(), w[["RSP", "TLT"]].to_numpy())
    o = p["odds_hourly"]
    o = o[(o["signal"] == "p_sen")].assign(session=o["session"].astype(str))
    o = o[(o["session"] >= lo) & (o["session"] <= hi)].copy()
    o["resid"] = pd.Series(resid, index=comp.index).reindex(o["bar_end_ts"]).to_numpy()
    X, sess = itd.session_matrix(o, "dp")
    Y, _ = itd.session_matrix(o, "resid")
    out = itd.h4(Y, X)
    out |= {
        "label": "secondary",
        "residual_on": ["RSP", "TLT"],
        "resid_coef": coef,
        "n_sessions": len(sess),
        "n_bars_with_return": int(np.isfinite(Y).sum()),
        "sessions_without_bars": [
            s for s, row in zip(sess, Y, strict=True) if not np.isfinite(row).any()
        ],
    }
    return out


def analyse(cfg: ElectionConfig, clean_dir: Path, out_dir: Path) -> dict:
    p = load_panels(clean_dir)
    D = daily_frame(p["daily"], p["odds_daily"])
    S = window(D, *cfg.pre_sample)
    h1, rob, h5, base = run_h1(S, cfg)
    h2, betas = run_h2(D, p["daily"], cfg)
    h2b = run_h2b(S, cfg)
    h3 = itd.h3(itd.night_frame(p["night_5m"], INSTRUMENTS), cfg.max_age["night"])
    h4 = run_h4(p, cfg)
    # exploratory
    ctrl = base[["RSP", "TLT"]].to_numpy()
    e1 = ex.e1_rolling(list(base.index), base["ai"].to_numpy(), base["dp"].to_numpy(), ctrl)
    e2, e2s = ex.e2_vol(p["vol_daily"])
    power = [s.ticker for s in cfg.universe if s.sub == "power_infra"]
    e3, e3s = ex.e3_moratorium(p["moratorium_daily"], basket(D, power) - D["XLU"], st.rng(300))
    names, B = betas["ai"]
    last = D.index.max()
    e5, e5s = ex.e5_drift(names, B[1], ar_daily(D, names, B, E5_START, last), E5_START)
    hd = headline(h1, h2, h2b)
    res = {
        "meta": {
            "preregistration": "docs/election/preregistration.md (frozen 2026-11-13, amendment A1)",
            "pre_sample": list(cfg.pre_sample),
            "h1_n_sessions": h1["ai"]["n"],
            "h2_est_end": H2_EST_END,
            "event_window": "close 2026-11-03 -> close 2026-11-04",
            "data_last_session": last,
            "signals": list(SIGNALS),
            "primary_signal": "p_sen",
            "seed": st.SEED,
            "units": "b10_pct = % log return per +10 probability points",
        },
        "headline": hd,
        "h1": h1,
        "h2": h2,
        "h2b": h2b,
        "h3": h3,
        "h4": h4,
        "h5": h5,
        "exploratory": {
            "e1": e1,
            "e2": e2,
            "e3": e3,
            "e4": {"label": "exploratory", "see": "robustness rows 'E4 ...'"},
            "e5": e5,
        },
        "robustness": rob,
        "coverage": p["coverage"],
    }
    res["checklist"] = checklist(res)
    series = context_series(D, cfg, p["odds_daily"])
    series |= {
        "e1_rolling": pd.DataFrame(e1.pop("rolling")),
        "e2_vol": e2s,
        "e3_scatter": e3s,
        "e5_car": e5s,
        "h3_night": night_series(p["night_5m"]),
    }
    series["h2_cross_section"] = pd.DataFrame(
        [{"group": g, **r} for g in ("ai", "placebo") for r in h2["groups"][g]["per_stock"]]
    )
    series["h2b_days"] = pd.DataFrame(
        [
            {"group": g, **{k: d[k] for k in ("date", "dp", "signed_rho", "n_est")}}
            for g in ("ai", "placebo")
            for d in h2b[g]["days"]
        ]
    )
    res["series"] = {k: f"series/{k}.csv" for k in sorted(series)}
    write(out_dir, clean(res), series)
    return res


__all__ = ["analyse", "publish", "basket"]

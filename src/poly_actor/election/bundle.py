"""Results bundle of the election study: verdict headline (pre-registered table, applied
mechanically), checklist, JSON cleaning, chart series, writing and `publish`."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.election import stats as st
from poly_actor.election.config import AI_SUBS, ElectionConfig

INSTRUMENTS = {"NQ": "NQ=F", "ES": "ES=F", "RTY": "RTY=F"}
CTX_START = "2025-07-14"
WALD_ALPHA = 0.05  # H5 Wald equality test, single secondary test (no correction)


def tick(ok: bool) -> str:
    return "✓" if ok else "✗"


def basket(D: pd.DataFrame, names: list[str]) -> pd.Series:
    """Equal-weight mean log return; NaN if any member is missing that day."""
    return D[names].mean(axis=1, skipna=False)


def checklist(res: dict) -> dict:
    h1, h2 = res["h1"], res["h2"]["groups"]["ai"]["windows"]["close3_close4"]
    hd = res["headline"]
    b2, wd = res["h2b"]["ai"], res["h5"]["wald_equal"]
    return {
        "H1": [
            {
                "name": "permutation p below Holm threshold",
                "status": tick(hd["holm"]["reject"][0]),
                "plain": "AI basket moved with Senate odds beyond chance",
                "technical": f"p_perm={h1['ai']['p_perm']:.4f}, thr={hd['holm']['threshold'][0]}",
            },
            {
                "name": "AI minus placebo significant at 0.10",
                "status": tick(h1["diff"]["p_perm"] < 0.10),
                "plain": "the link is stronger for AI than for non-AI large caps",
                "technical": f"diff b10={h1['diff']['b10_pct']:.3f}%, "
                f"p_perm={h1['diff']['p_perm']:.4f}",
            },
            {
                "name": "MDE <= 0.5% per 10 pts",
                "status": tick(h1["ai"]["mde10_pct"] <= st.MDE_BOUND_PCT),
                "plain": "the test could see a modest beta",
                "technical": f"MDE80={h1['ai']['mde10_pct']:.3f}%",
            },
        ],
        "H2": [
            {
                "name": "rho > 0 and permutation p below Holm threshold",
                "status": tick(hd["holm"]["reject"][1] and h2["rho"] > 0),
                "plain": "stocks with higher pre-election betas did better on election night",
                "technical": f"rho={h2['rho']:.3f}, p_one={h2['p_one']:.4f}, "
                f"p_two={h2['p_two']:.4f}",
            },
            {
                "name": "H2b walk-forward p < 0.10",
                "status": tick((res["h2b"]["ai"]["p"] or 1.0) < st.H2B_ALPHA),
                "plain": "betas also ranked stocks on other big-odds days",
                "technical": f"mean={b2['mean']}, n={b2['n']}, p={b2['p']}",
            },
        ],
        "H3": [
            {
                "name": "descriptive only",
                "status": "n.a.",
                "plain": "one night, path seen before freeze",
                "technical": f"fresh share={res['h3']['share_fresh_odds']:.3f}",
            }
        ],
        "H4": [
            {
                "name": "ordering verdict",
                "status": "n.a.",
                "plain": res["h4"]["verdict"],
                "technical": f"band max|t|={res['h4']['band_max_abs_t_95']:.2f}",
            }
        ],
        "H5": [
            {
                "name": "Wald equal b",
                "status": tick(res["h5"]["wald_equal"]["p"] < WALD_ALPHA),
                "plain": "sub-baskets differ in beta (secondary, single uncorrected test; it "
                "does not make any sub-basket significant, and the composite b is null)",
                "technical": f"W={wd['wald']:.2f}, p={wd['p']:.4f}",
            }
        ],
    }


def headline(h1: dict, h2: dict, h2b: dict) -> dict:
    p_h2 = h2["groups"]["ai"]["windows"]["close3_close4"]
    rho = p_h2["rho"]
    hm = st.holm([h1["ai"]["p_perm"], p_h2["p_one"]])
    h2_ok = st.h2_passes(hm["reject"][1], rho)
    v1, c1 = st.h1_verdict(
        hm["reject"][0], h1["diff"]["p_perm"], h1["ai"]["mde10_pct"], h2_ok, h2b["ai"]["p"]
    )
    v2, c2 = st.h2_verdict(h2_ok, h2b["ai"]["p"])
    a = h1["ai"]
    sent = (
        f"H1: {v1} (confidence {c1}); b = {a['b10_pct']:+.3f}% per +10 pts of P(D Senate), "
        f"90% CI [{a['ci10_pct'][0]:+.3f}, {a['ci10_pct'][1]:+.3f}], "
        f"permutation p = {a['p_perm']:.3f}, "
        f"MDE80 = {a['mde10_pct']:.3f}%. H2: {v2} (confidence {c2}); rho = {rho:+.3f}, "
        f"one-sided p = {p_h2['p_one']:.3f}."
    )
    return {
        "h1_verdict": v1,
        "h1_confidence": c1,
        "h2_verdict": v2,
        "h2_confidence": c2,
        "sentence": sent,
        "holm": hm,
        "holm_inputs": {"h1_p_perm": a["p_perm"], "h2_p_one": p_h2["p_one"]},
    }


def clean(o):
    """JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [clean(v) for v in o]
    if isinstance(o, np.bool_ | bool):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, float | np.floating):
        return None if not math.isfinite(float(o)) else float(o)
    return o


def context_series(D: pd.DataFrame, cfg: ElectionConfig, odds: pd.DataFrame) -> dict:
    o = odds.assign(session=odds["session"].astype(str))
    o = o[o["p"].notna()][["session", "signal", "p", "resolved"]]
    C = D[D.index >= CTX_START]
    subs = {s: [x.ticker for x in cfg.universe if x.sub == s] for s in AI_SUBS}
    cum = pd.DataFrame(index=C.index)
    cum["ai_composite"] = basket(C, cfg.basket("ai"))
    for s, n in subs.items():
        cum[s] = basket(C, n)
    cum["placebo"] = basket(C, cfg.basket("placebo"))
    cum["RSP"] = C["RSP"]
    cum = cum.cumsum()
    cum.index.name = "session"
    return {"odds_daily": o.reset_index(drop=True), "cum_log_returns": cum.reset_index()}


def night_series(night: pd.DataFrame) -> pd.DataFrame:
    """Odds and each future as % change from the 18:00 ET window start (open of the first bar)."""
    w = night[night["in_window"]]
    parts = []
    for name, tk in INSTRUMENTS.items():
        g = w[w["ticker"] == tk].sort_values("bar_end_ts")
        if len(g):
            ref = g["open"].iloc[0]
            parts.append(
                pd.DataFrame(
                    {
                        "bar_end_ts": g["bar_end_ts"].astype(str),
                        "series": name,
                        "value": 100 * (g["close"] / ref - 1),
                    }
                )
            )
    g = w[w["ticker"] == INSTRUMENTS["NQ"]]
    for k in ("p_sen", "p_house"):
        parts.append(
            pd.DataFrame({"bar_end_ts": g["bar_end_ts"].astype(str), "series": k, "value": g[k]})
        )
    return pd.concat(parts, ignore_index=True)


def write(out_dir: Path, res: dict, series: dict[str, pd.DataFrame]) -> None:
    (out_dir / "series").mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for k, df in series.items():
        df.to_csv(
            out_dir / "series" / f"{k}.csv", index=False, float_format="%.10g", lineterminator="\n"
        )


def publish(results_dir: Path, report_dir: Path) -> list[str]:
    """Copy results.json + series/ to the tracked report directory (replacing it)."""
    if not (results_dir / "results.json").exists():
        raise FileNotFoundError(f"run `analyse` first: no {results_dir / 'results.json'}")
    # Copy to a sibling staging dir first, so a failed copy never touches the tracked directory;
    # then swap it in with renames on the same filesystem (the previous bundle is restored if the
    # swap fails).
    report_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{report_dir.name}.new-", dir=report_dir.parent))
    backup = report_dir.with_name(f".{report_dir.name}.old")
    try:
        staging.chmod(0o755)
        shutil.copytree(results_dir, staging, dirs_exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup)
        if report_dir.exists():
            report_dir.rename(backup)
        try:
            staging.rename(report_dir)
        except OSError:
            if backup.exists() and not report_dir.exists():
                backup.rename(report_dir)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if backup.exists():
        shutil.rmtree(backup)
    return sorted(str(f.relative_to(report_dir)) for f in report_dir.rglob("*") if f.is_file())

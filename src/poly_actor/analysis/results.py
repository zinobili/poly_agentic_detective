"""Results JSON in the dashboard contract (`dashboard/contract.py`), built from the analysis
cores and the verdict facts. Every label and status here is computed; nothing is typed in
per pair.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

from poly_actor.analysis import events as ev
from poly_actor.analysis import placebo, verdict
from poly_actor.analysis.runners import BtcCore, CpiCore, FedCore
from poly_actor.analysis.verdict import Facts

SCHEMA_VERSION = 2
NOT_IN_PLAN = "not_in_plan"

PARAMS = {
    "xcorr_lags": [min(placebo.XCORR_LAGS), max(placebo.XCORR_LAGS)],
    "lag_unit": "session bars (about 1 hour)",
    "band_level": placebo.BAND_QUANTILE,
    "band_kind": "simultaneous: 95th percentile of the largest |r| over every session shift of "
    f"at least {placebo.MIN_SHIFT} sessions",
    "ci_level": 0.90,
    "bh_q": verdict.BH_Q,
    "event_window_bars": [-3, 6],
    "event_band_draws": ev.BAND_DRAWS,
    "max_quote_age_s": 1800,
}


# ---------------------------------------------------------------- small helpers


def _fmt(v: float | None, digits: int = 3) -> str:
    return "n/a" if v is None or not math.isfinite(v) else f"{v:.{digits}g}"


def _row(name: str, status: str, plain: str, technical: str) -> dict:
    return {"name": name, "status": status, "plain": plain, "technical": technical}


def xcorr_json(res: placebo.XcorrResult) -> dict:
    return {
        "lags": list(res.lags),
        "r": [0.0 if math.isnan(v) else v for v in res.r],
        "band": res.band,
        "peak_lag": res.peak_lag,
        "clear_link": res.clear_link,
        "adjacent_outside": res.adjacent_outside,
        "n_shifts": res.n_shifts,
    }


def event_json(out: ev.EventStudyOut | None) -> dict | None:
    if out is None:
        return None
    doc = out.as_contract("bars")
    doc["event_times"] = [_iso(t) for t in out.event_ts]
    return doc


def _iso(epoch_s: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(int(epoch_s), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _common(facts: Facts, bh: dict) -> tuple[list[dict], dict]:
    label, reason = verdict.verdict(facts)
    literal, _ = verdict.verdict(facts, literal_placebo=True)
    level, why = verdict.confidence(facts)
    rows = [
        _row(
            "Many-pairs correction",
            "Passed" if facts.bh_reject else "Failed",
            "Holds after the many-pairs correction",
            f"Benjamini-Hochberg q = {verdict.BH_Q} over {bh['family']}: adjusted p = "
            f"{_fmt(facts.bh_q)}",
        ),
        _row(
            "Enough data",
            "Passed" if facts.sufficient else "Failed",
            "Enough cases to be sure",
            facts.sufficiency_note,
        ),
    ]
    head = {
        "verdict": label,
        "verdict_reason": reason,
        "confidence": {"level": level, "reason": why},
        "verdict_if_placebo_read_literally": literal,
    }
    return rows, head


def _robust_row(rob: dict | None, facts: Facts) -> dict:
    if rob is None:
        return _row("Robustness", "Not run", "Holds in robustness checks", "")
    parts = [
        f"{k.split('_')[0]} {'holds' if v.get('holds') else 'fails'}"
        for k, v in rob.items()
        if k.startswith("R")
    ]
    status = "Passed" if rob["all_hold"] else ("Failed" if facts.bh_reject else "Weak")
    return _row(
        "Robustness",
        status,
        "Holds in robustness checks (clustered errors, without the biggest moves, without event "
        "days)",
        "; ".join(parts) + " (sign unchanged and one-sided p < 0.10)",
    )


# ---------------------------------------------------------------- Fed


def fed_result(core: FedCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> dict:
    t = core.reg.tests["sum"]
    lead = core.reg.tests["lead"]
    rows, head = _common(facts, bh)
    plc = core.placebo
    rows = [
        _row(
            "Primary test",
            verdict.primary_status(facts),
            "The odds and long-term bonds move together in the expected direction",
            f"TLT on Δdovishness lags 0-2: b0+b1+b2 = {_fmt(t.estimate)} bp per bp "
            f"(90% CI {_fmt(t.ci_low)} to {_fmt(t.ci_high)}), one-sided HAC p = {_fmt(t.p_one)}, "
            f"n = {core.reg.n}, Newey-West lag {core.reg.hac_lag}",
        ),
        _row(
            "Odds move first",
            ("Passed" if lead.p_one < verdict.LEAD_ALPHA else "Failed")
            if facts.bh_reject
            else "Not needed",
            "Odds move first (the earlier odds changes carry the link)",
            f"b1+b2 = {_fmt(lead.estimate)} bp per bp (90% CI {_fmt(lead.ci_low)} to "
            f"{_fmt(lead.ci_high)}), one-sided p = {_fmt(lead.p_one)}; tested only when the "
            "primary passes",
        ),
        _row(
            "Placebo",
            "Passed" if facts.placebo_pass else "Failed",
            "Link vanishes when timing is scrambled",
            f"session-shift permutation p = {_fmt(plc['permutation_p'])} over "
            f"{plc['n_shifts']} shifts (passes if < 0.10)",
        ),
        *rows,
        _robust_row(core.robustness, facts),
    ]
    xc = {tk: xcorr_json(r) for tk, r in core.xcorr.items()}
    stocks_first = core.xcorr["TLT"].stocks_first if "TLT" in core.xcorr else None
    return {
        "pair_id": "fed_decision",
        **head,
        "stocks_first": stocks_first,
        "n_events": extra.get("n_events"),
        "params": PARAMS,
        "xcorr": xc,
        "event_study": {k: v for k, v in studies.items() if v is not None},
        "checklist": rows,
        "details": {
            "primary": core.reg.as_dict(),
            "placebo_shift": plc,
            "robustness": core.robustness,
            "secondary": {k: v.as_dict() for k, v in core.secondary.items()},
            **extra,
        },
    }


# ---------------------------------------------------------------- BTC


def btc_result(core: BtcCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> dict:
    t = core.reg.tests["lag1"]
    nc = core.reg_nocontrol.tests["lag1"]
    rows, head = _common(facts, bh)
    xlu = core.xlu.tests["lag1"] if core.xlu else None
    beyond = (
        verdict.primary_status(facts)
        if not (not facts.bh_reject and nc.p_one < verdict.NO_EXTRA_P)
        else "Failed"
    )
    rows = [
        _row(
            "Primary test",
            verdict.primary_status(facts),
            "Odds an hour earlier help predict the Bitcoin ETF beyond Bitcoin's own price",
            f"IBIT on Δln(ladder) at t-1 with BTC-USD lags 0-3: {_fmt(t.estimate)} bp per 1% "
            f"(90% CI {_fmt(t.ci_low)} to {_fmt(t.ci_high)}), one-sided HAC p = {_fmt(t.p_one)}, "
            f"n = {core.reg.n}",
        ),
        _row(
            "Beyond Bitcoin's own price",
            beyond,
            "The odds add something beyond Bitcoin's own price",
            f"without the spot control: {_fmt(nc.estimate)} bp per 1% (one-sided p = "
            f"{_fmt(nc.p_one)}); with it: one-sided p = {_fmt(t.p_one)}",
        ),
        _row(
            "Placebo",
            "Not run" if xlu is None else ("Passed" if facts.placebo_pass else "Failed"),
            "No link to an unrelated control stock (utilities); a pass is weak evidence at "
            "this sample size",
            ""
            if xlu is None
            else f"XLU: {_fmt(xlu.estimate)} bp per 1% (90% CI "
            f"{_fmt(xlu.ci_low)} to {_fmt(xlu.ci_high)}), two-sided p = {_fmt(xlu.p_two)} "
            "(passes if > 0.10)",
        ),
        *rows,
        _robust_row(core.robustness, facts),
    ]
    xc = {}
    for tk, raw in core.xcorr_raw.items():
        xc[tk] = {**xcorr_json(raw), "residualised": xcorr_json(core.xcorr_resid[tk])}
    stocks_first = core.xcorr_resid["IBIT"].stocks_first if "IBIT" in core.xcorr_resid else None
    return {
        "pair_id": "bitcoin_monthly_ladder",
        **head,
        "stocks_first": stocks_first,
        "n_events": extra.get("n_events"),
        "params": PARAMS,
        "xcorr": xc,
        "event_study": {k: v for k, v in studies.items() if v is not None},
        "checklist": rows,
        "details": {
            "primary": core.reg.as_dict(),
            "no_control": core.reg_nocontrol.as_dict(),
            "xlu_placebo": core.xlu.as_dict() if core.xlu else None,
            "placebo_shift_reported_only": core.placebo_shift,
            "robustness": core.robustness,
            "exploratory": {k: v.as_dict() for k, v in core.exploratory.items()},
            **extra,
        },
    }


# ---------------------------------------------------------------- CPI


def cpi_result(core: CpiCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> dict:
    rows, head = _common(facts, bh)
    t = core.test
    v = core.validation
    plc = core.placebo
    tech = (
        "not run"
        if t is None
        else f"Spearman rho = {_fmt(t.rho)} (90% CI {_fmt(t.ci_low)} to {_fmt(t.ci_high)}), "
        f"exact one-sided p = {_fmt(t.p_one)}, n = {t.n}; sign test {t.sign_negative} of "
        f"{t.sign_n} (p = {_fmt(t.sign_p)})"
    )
    rows = [
        _row(
            "Method check",
            "Passed" if v.passed else "Failed",
            "The odds read resolved months correctly before the release",
            f"{v.n_within} of {v.n_valid} valid months within 0.1 pp of the winning bucket "
            "(needs more than half and at least 8)",
        ),
        _row(
            "Primary test",
            verdict.primary_status(facts),
            "Higher inflation odds before the release go with a weaker bond opening",
            tech,
        ),
        _row(
            "Odds move first",
            (("Passed" if facts.close_proxy_ok else "Failed") if facts.bh_reject else "Not needed"),
            "The odds move had happened by the previous close",
            "proxy ending at the prior 16:00 ET close: "
            + (
                "not run"
                if core.close_proxy is None
                else f"rho = {_fmt(core.close_proxy.rho)}, one-sided p = "
                f"{_fmt(core.close_proxy.p_one)}"
            ),
        ),
        _row(
            "Placebo",
            "Not run" if plc is None else ("Passed" if plc["passes"] else "Failed"),
            "Link vanishes on random non-release days",
            ""
            if plc is None
            else f"release rho {_fmt(plc['release_rho'])} vs 10th percentile "
            f"{_fmt(plc['p10_of_placebo_rho'])} of {plc['n_sets']} random sets",
        ),
        *rows,
    ]
    return {
        "pair_id": "us_cpi_inflation",
        **head,
        "stocks_first": None,
        "n_events": core.n_usable,
        "params": PARAMS,
        "xcorr": NOT_IN_PLAN,
        "event_study": {k: v for k, v in studies.items() if v is not None},
        "checklist": rows,
        "details": {
            "usable_releases": core.n_usable,
            "validation": v.__dict__,
            "primary": t.as_dict() if t else None,
            "close_proxy": core.close_proxy.as_dict() if core.close_proxy else None,
            "robust_R2_drop_largest": core.robust_r2.as_dict() if core.robust_r2 else None,
            "placebo_random_dates": plc,
            **extra,
        },
    }


# ---------------------------------------------------------------- recession


def recession_result(main: dict, sensitivity: dict) -> dict:
    """Pair 4: "Descriptive only", confidence Low, and no p-value anywhere (A27 rule 5)."""
    facts = Facts(pair="recession")
    label, reason = verdict.verdict(facts)
    level, why = verdict.confidence(facts)
    rises = main["groups"]["rises"]["tickers"]
    studies = {}
    for t, entry in rises.items():
        if "mean" not in entry:
            continue
        falls = main["groups"]["falls"]["tickers"][t]
        doc = {
            "unit": "days",
            "steps": ["0", "+1"],
            "mean": entry["mean"],
            "ci_low": entry["ci_low"],
            "ci_high": entry["ci_high"],
            "paths": [v for v in entry["values"] if all(map(math.isfinite, v))],
            "label": "Days with the largest rises in recession odds",
            "event_times": [_iso(ts) for ts in main["groups"]["rises"]["close_ts"]],
        }
        if "mean" in falls:
            doc["compare"] = {
                "label": "Days with the largest falls",
                "mean": falls["mean"],
                "ci_low": falls["ci_low"],
                "ci_high": falls["ci_high"],
            }
        studies[t] = doc
    rows = [
        _row(
            "Descriptive only",
            "Not needed",
            "Descriptive only: one episode, so no significance test (decided in advance)",
            "10 largest rises and falls of the recession odds, at least 2 trading days apart; "
            "day 0 and day +1 moves with 90% BCa intervals",
        ),
    ]
    return {
        "pair_id": "us_recession",
        "verdict": label,
        "verdict_reason": reason,
        "confidence": {"level": level, "reason": why},
        "stocks_first": None,
        "n_events": len(main["groups"]["rises"]["dates"]),
        "params": {k: v for k, v in PARAMS.items() if k != "bh_q"},
        "xcorr": NOT_IN_PLAN,
        "event_study": studies,
        "checklist": rows,
        "details": {
            "main_change_in_probability": main,
            "sensitivity_change_in_log_odds": sensitivity,
        },
    }


# ---------------------------------------------------------------- writing


def jsonable(obj):
    """Replace NaN/inf by None and numpy scalars/arrays by Python values (strict JSON)."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        return float(obj) if math.isfinite(obj) else None
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def write_json(doc: dict, path: Path) -> None:
    """Strict JSON, written to a temp file and renamed (atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jsonable(doc), indent=1, allow_nan=False), "utf-8")
    os.replace(tmp, path)

"""Results JSON in the dashboard contract (`dashboard/contract.py`), built from the analysis
cores and the verdict facts. Every label and status here is computed; nothing is typed in
per pair.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, TypedDict

import numpy as np

from poly_actor.analysis import events as ev
from poly_actor.analysis import placebo, verdict
from poly_actor.analysis.runners import BtcCore, CpiCore, FedCore
from poly_actor.analysis.verdict import Facts
from poly_actor.dashboard.contract import (
    CheckRowDoc,
    ConfidenceDoc,
    Params,
    ResultsDoc,
    XCorrDoc,
)

SCHEMA_VERSION = 2
NOT_IN_PLAN = "not_in_plan"

PARAMS: Params = {
    "xcorr_lags": [min(placebo.XCORR_LAGS), max(placebo.XCORR_LAGS)],
    "lag_unit": "session bars (about 1 hour)",
    "band_level": placebo.BAND_QUANTILE,
    "band_stat": placebo.BAND_STAT,
    "band_kind": "simultaneous: 95th percentile of the largest |robust t| over every session "
    f"shift of at least {placebo.MIN_SHIFT} sessions (A28 item 1)",
    "ci_level": 0.90,
    "bh_q": verdict.BH_Q,
    "event_window_bars": [-3, 6],
    "event_band_draws": ev.BAND_DRAWS,
    "max_quote_age_s": 1800,
}


# ---------------------------------------------------------------- small helpers


def _fmt(v: float | None, digits: int = 3) -> str:
    return "n/a" if v is None or not math.isfinite(v) else f"{v:.{digits}g}"


def _row(name: str, status: str, plain: str, technical: str) -> CheckRowDoc:
    return {"name": name, "status": status, "plain": plain, "technical": technical}


def xcorr_json(res: placebo.XcorrResult) -> XCorrDoc:
    return {
        "lags": list(res.lags),
        "r": [0.0 if math.isnan(v) else v for v in res.r],
        "t": [0.0 if math.isnan(v) else v for v in res.t],
        "band": res.band,
        "band_stat": placebo.BAND_STAT,
        "peak_lag": res.peak_lag,
        "clear_link": res.clear_link,
        "adjacent_outside": res.adjacent_outside,
        "n_shifts": res.n_shifts,
    }


def event_json(out: ev.EventStudyOut | ev.TooFewEvents | None) -> dict[str, Any] | None:
    if not isinstance(out, ev.EventStudyOut):
        return None
    doc = out.as_contract("bars")
    doc["event_times"] = [_iso(t) for t in out.event_ts]
    return doc


def too_few_note(c: ev.TooFewEvents) -> str:
    """Reader-facing reason for a missing chart 2, with the A27 rule 13 counts."""
    return (
        f"Too few events to draw this chart: {c.n_used} of {c.n_candidates} could be used "
        f"({c.n_unsigned} had no clear odds move, or no odds reading, just before; "
        f"{c.n_dropped} had missing prices); at least {c.min_events} are needed."
    )


def study_slots(studies: dict) -> dict:
    """Contract slots from raw chart-2 outputs: the drawn studies, the reasons for the missing
    ones, and every count (drawn or not) for the details."""
    drawn = {t: event_json(o) for t, o in studies.items() if isinstance(o, ev.EventStudyOut)}
    few = {t: o for t, o in studies.items() if isinstance(o, ev.TooFewEvents)}
    counts = {
        t: {"n_used": len(o.paths), "n_unsigned": o.n_unsigned, "n_dropped": o.n_dropped}
        if isinstance(o, ev.EventStudyOut)
        else o.as_dict()
        for t, o in studies.items()
        if o is not None
    }
    return {
        "event_study": drawn,
        "event_study_notes": {t: too_few_note(c) for t, c in few.items()},
        "event_study_counts": counts,
    }


def _iso(epoch_s: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(int(epoch_s), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _HeadBase(TypedDict):
    verdict: str
    verdict_reason: str
    confidence: ConfidenceDoc
    verdict_if_placebo_read_literally: str


class _Head(_HeadBase, total=False):  # the A29 keys, BTC only
    verdict_if_a27_rule3_read_literally: str
    a29_note: str


def _common(facts: Facts, bh: dict) -> tuple[list[CheckRowDoc], _Head]:
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
            "Enough data for the test",
            facts.sufficiency_note,
        ),
    ]
    head: _Head = {
        "verdict": label,
        "verdict_reason": reason,
        "confidence": {"level": level, "reason": why},
        "verdict_if_placebo_read_literally": literal,
    }
    if facts.control_misaligned:
        head["verdict_if_a27_rule3_read_literally"] = verdict.verdict(facts, literal_a29=True)[0]
        head["a29_note"] = verdict.A29_NOTE
    return rows, head


ROBUST_PLAIN = {
    "fed": "Holds in robustness checks (clustered errors, without the biggest moves, without "
    "event days)",
    "btc": "Holds in robustness checks (clustered errors, without the biggest moves)",
}


def _robust_row(rob: dict | None, facts: Facts) -> CheckRowDoc:
    plain = ROBUST_PLAIN.get(facts.pair, "Holds in robustness checks")
    if rob is None:
        return _row("Robustness", "Not run", plain, "")
    parts = []
    for k, v in rob.items():
        if not k.startswith("R"):
            continue
        state = {True: "holds", False: "fails", None: "not applicable"}[v.get("holds")]
        parts.append(f"{k.split('_')[0]} {state}")
    status = "Passed" if rob["all_hold"] else ("Failed" if facts.bh_reject else "Weak")
    technical = "; ".join(parts) + " (sign unchanged and one-sided p < 0.10)"
    if facts.control_misaligned:  # A29: these runs use the same biased control
        status, technical = verdict.NOT_VALID, f"{technical}. Prereg A29: {verdict.A29_NOTE}"
    return _row("Robustness", status, plain, technical)


def _relative_placebo_status(passes: bool | None, facts: Facts) -> str:
    """Fed and CPI placebos gate only a significant primary (prereg A28 item 2); for a null one
    they are reported, not used, so the row reads "Not needed" rather than "Failed"."""
    if passes is None:
        return "Not run"
    if not facts.bh_reject:
        return "Not needed"
    return "Passed" if passes else "Failed"


# ---------------------------------------------------------------- shared skeleton


def _base_doc(
    pair: tuple[str, str],
    facts: Facts,
    bh: dict,
    studies: dict,
    *,
    rows: list[CheckRowDoc],
    tail: list[CheckRowDoc],
    xcorr: dict[str, XCorrDoc] | str,
    stocks_first: bool | None,
    n_events: int | None,
    details: dict[str, Any],
    extra: dict,
) -> ResultsDoc:
    """The document every tested pair shares. ``pair`` is (pair_id, primary ticker); the
    checklist is the pair's own ``rows``, then the common rows, then ``tail``; ``details``
    follows the chart-2 counts and is followed by ``extra``."""
    common, head = _common(facts, bh)
    slots = study_slots(studies)
    return {
        "pair_id": pair[0],
        "primary_ticker": pair[1],
        **head,
        "stocks_first": stocks_first,
        "n_events": n_events,
        "params": PARAMS,
        "xcorr": xcorr,
        "event_study": slots["event_study"],
        "event_study_notes": slots["event_study_notes"],
        "checklist": [*rows, *common, *tail],
        "details": {"event_study_counts": slots["event_study_counts"], **details, **extra},
    }


# ---------------------------------------------------------------- Fed


def _fed_rows(core: FedCore, facts: Facts) -> list[CheckRowDoc]:
    t = core.reg.tests["sum"]
    lead = core.reg.tests["lead"]
    plc = core.placebo
    return [
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
            _relative_placebo_status(facts.placebo_pass, facts),
            "Link vanishes when timing is scrambled (only needed when the main test passes)",
            f"session-shift permutation p of the HAC t of b0+b1+b2 = "
            f"{_fmt(plc['permutation_p'])} over {plc['n_shifts']} shifts (passes if < 0.10: "
            f"{'yes' if facts.placebo_pass else 'no'}; gates the verdict only when the primary "
            "is significant, prereg A28)",
        ),
    ]


def fed_result(core: FedCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> ResultsDoc:
    return _base_doc(
        ("fed_decision", "TLT"),
        facts,
        bh,
        studies,
        rows=_fed_rows(core, facts),
        tail=[_robust_row(core.robustness, facts)],
        xcorr={tk: xcorr_json(r) for tk, r in core.xcorr.items()},
        stocks_first=core.xcorr["TLT"].stocks_first if "TLT" in core.xcorr else None,
        n_events=extra.get("n_events"),
        details={
            "primary": core.reg.as_dict(),
            "placebo_shift": core.placebo,
            "robustness": core.robustness,
            "secondary": {k: v.as_dict() for k, v in core.secondary.items()},
        },
        extra=extra,
    )


# ---------------------------------------------------------------- BTC


def _btc_rows(core: BtcCore, facts: Facts) -> list[CheckRowDoc]:
    t = core.reg.tests["lag1"]
    nc = core.reg_nocontrol.tests["lag1"]
    xlu = core.xlu.tests["lag1"] if core.xlu else None
    if facts.control_misaligned:  # A29: the with-control side of this row is biased
        beyond = verdict.NOT_VALID
    elif not facts.bh_reject and nc.p_one < verdict.NO_EXTRA_P:
        beyond = "Failed"
    else:
        beyond = verdict.primary_status(facts)
    a29 = f" Prereg A29: {verdict.A29_NOTE}" if facts.control_misaligned else ""
    if xlu is None:
        placebo = "Not run"
    elif facts.control_misaligned:  # A29 addendum 2: XLU runs with the same spot control
        placebo = verdict.NOT_VALID
    else:
        placebo = "Passed" if facts.placebo_pass else "Failed"
    return [
        _row(
            "Primary test",
            verdict.primary_status(facts),
            "Odds an hour earlier help predict the Bitcoin ETF beyond Bitcoin's own price",
            f"IBIT on Δln(ladder) at t-1 with BTC-USD lags 0-3: {_fmt(t.estimate)} bp per 1% "
            f"(90% CI {_fmt(t.ci_low)} to {_fmt(t.ci_high)}), one-sided HAC p = {_fmt(t.p_one)}, "
            f"n = {core.reg.n}.{a29}",
        ),
        _row(
            "Beyond Bitcoin's own price",
            beyond,
            "The odds add something beyond Bitcoin's own price",
            f"without the spot control: {_fmt(nc.estimate)} bp per 1% (one-sided p = "
            f"{_fmt(nc.p_one)}); with it: one-sided p = {_fmt(t.p_one)}.{a29}",
        ),
        _row(
            "Placebo",
            placebo,
            "No link to an unrelated control stock (utilities); a pass is weak evidence at "
            "this sample size",
            ""
            if xlu is None
            else f"XLU: {_fmt(xlu.estimate)} bp per 1% (90% CI "
            f"{_fmt(xlu.ci_low)} to {_fmt(xlu.ci_high)}), two-sided p = {_fmt(xlu.p_two)} "
            f"(passes if > 0.10).{a29}",
        ),
    ]


def _btc_xcorr(core: BtcCore, note: dict[str, str]) -> dict[str, XCorrDoc]:
    """Raw and spot-residualised Chart 1; every residualised panel carries the A29 note."""
    xc: dict[str, XCorrDoc] = {}
    for tk, raw in core.xcorr_raw.items():
        xc[tk] = {**xcorr_json(raw), "residualised": {**xcorr_json(core.xcorr_resid[tk]), **note}}
    return xc


def btc_result(core: BtcCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> ResultsDoc:
    note = {"note": verdict.A29_NOTE} if facts.control_misaligned else {}
    doc = _base_doc(
        ("bitcoin_monthly_ladder", "IBIT"),
        facts,
        bh,
        studies,
        rows=_btc_rows(core, facts),
        tail=[_robust_row(core.robustness, facts)],
        xcorr=_btc_xcorr(core, note),
        stocks_first=core.xcorr_resid["IBIT"].stocks_first if "IBIT" in core.xcorr_resid else None,
        n_events=extra.get("n_events"),
        details={
            "primary": core.reg.as_dict(),
            "no_control": core.reg_nocontrol.as_dict(),
            "xlu_placebo": core.xlu.as_dict() if core.xlu else None,
            "placebo_shift_reported_only": core.placebo_shift,
            "robustness": core.robustness,
            "exploratory": {k: {**v.as_dict(), **note} for k, v in core.exploratory.items()},
        },
        extra=extra,
    )
    for study in doc["event_study"].values():  # Chart 2 is residualised on the same control
        study.update(note)
    return doc


# ---------------------------------------------------------------- CPI


def _cpi_rows(core: CpiCore, facts: Facts) -> list[CheckRowDoc]:
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
    return [
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
            _relative_placebo_status(None if plc is None else plc["passes"], facts),
            "Link vanishes on random non-release days (only needed when the main test passes)",
            ""
            if plc is None
            else f"release rho {_fmt(plc['release_rho'])} vs 10th percentile "
            f"{_fmt(plc['p10_of_placebo_rho'])} of {plc['n_sets']} random sets (passes: "
            f"{'yes' if plc['passes'] else 'no'}; gates the verdict only when the primary is "
            "significant, prereg A28)",
        ),
    ]


def cpi_result(core: CpiCore, facts: Facts, bh: dict, studies: dict, extra: dict) -> ResultsDoc:
    t = core.test
    return _base_doc(
        ("us_cpi_inflation", "TLT"),
        facts,
        bh,
        studies,
        rows=_cpi_rows(core, facts),
        tail=[],
        xcorr=NOT_IN_PLAN,
        stocks_first=None,
        n_events=core.n_usable,
        details={
            "usable_releases": core.n_usable,
            "validation": core.validation.__dict__,
            "primary": t.as_dict() if t else None,
            "close_proxy": core.close_proxy.as_dict() if core.close_proxy else None,
            "robust_R2_drop_largest": core.robust_r2.as_dict() if core.robust_r2 else None,
            "placebo_random_dates": core.placebo,
        },
        extra=extra,
    )


# ---------------------------------------------------------------- recession


def recession_result(main: dict, sensitivity: dict) -> ResultsDoc:
    """Pair 4: "Descriptive only", confidence Low, and no p-value anywhere (A27 rule 5)."""
    facts = Facts(pair="recession")
    label, reason = verdict.verdict(facts)
    level, why = verdict.confidence(facts)
    rises = main["groups"]["rises"]["tickers"]
    studies: dict[str, dict[str, Any]] = {}
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
        "primary_ticker": "IWM-SPY",
        "verdict": label,
        "verdict_reason": reason,
        "confidence": {"level": level, "reason": why},
        "stocks_first": None,
        "n_events": len(main["groups"]["rises"]["dates"]),
        "params": Params(**{k: v for k, v in PARAMS.items() if k != "bh_q"}),
        "xcorr": NOT_IN_PLAN,
        "event_study": studies,
        "checklist": rows,
        "details": {
            "main_change_in_probability": main,
            "sensitivity_change_in_log_odds": sensitivity,
        },
    }


# ---------------------------------------------------------------- writing


def jsonable(obj: object) -> Any:
    """Replace NaN/inf by None and numpy scalars/arrays by Python values (strict JSON).

    Raises ``TypeError`` for any other type, so a stray object fails here, by name.
    """
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
    if obj is None or isinstance(obj, str | int):  # int covers bool
        return obj
    raise TypeError(f"not JSON-serialisable: {type(obj).__name__}")


def write_json(doc: ResultsDoc | dict[str, Any], path: Path) -> None:
    """Strict JSON, written atomically (see `write_text_atomic`)."""
    write_text_atomic(json.dumps(jsonable(doc), indent=1, allow_nan=False), path)


def write_text_atomic(text: str, path: Path, newline: str | None = None) -> None:
    """Write to a uniquely named temp file in the same folder, then rename (atomic).

    ``newline`` is passed to `open` (None = platform default, "\\n" = LF everywhere)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

"""Every word of the election presentation and of `docs/studies/election/findings.md`. Pure
functions of the results bundle: no Streamlit, no I/O, no statistics (formatting and look-ups only).

Wording follows the pre-registered verdicts in ``results["headline"]``. A chart's action title is
computed from the results and never says more than the verdict does. A value the bundle lacks is
shown as "not in the results"; a block whose inputs are missing says so instead of raising.

Units: ``b10_pct`` is % log return per +10 probability points; ``*_pct`` are percent; odds are
probabilities in [0, 1] and are printed as percent or as points (x100).
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import wraps
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

Results = Mapping[str, Any]

MISSING = "not in the results"
VALID_NULL = "That's a valid result, not a failure."
H3_LABEL = "Descriptive only: one night, and the futures path was seen before the plan was frozen"
EXPLORATORY = "Exploratory"
DESCRIPTIVE = "Descriptive only"
FOOTER = "Not financial advice. Paper only: no part of this project places orders or moves money."

# Verdict labels of the pre-registered table (docs/studies/election/preregistration.md).
H1_AI = "AI carried a partisan beta"
H1_SHARED = "Election beta, not AI-specific"
H1_BOUNDED = "No partisan beta (bounded)"
H1_NOISY = "Too noisy to tell"
H2_YES = "Betas predicted the election-night winners"
H2_NO = "Betas did not predict election night"

QUESTION = (
    "Did AI stocks move with the odds that Democrats would take Congress, over and above the "
    "broad market? And did each stock's sensitivity, measured before the election, tell you which "
    "names would reprice on election night?"
)
WHY_IT_MATTERS = (
    "If the sensitivity is real and stable, election risk in an AI book can be sized and hedged "
    "ahead of time. If it is zero, there was no election beta in AI names to hedge."
)

SUB_LABELS = {
    "semis": "Semiconductors",
    "hyperscalers": "Hyperscalers and AI cloud",
    "power_infra": "Power and data-centre infrastructure",
    "software": "AI software",
}
BASKET_LABELS = {
    "ai": "AI basket",
    "placebo": "Non-AI basket (placebo)",
    "diff": "AI minus non-AI",
}
SERIES_LABELS = {
    "ai_composite": "AI basket",
    "placebo": "Non-AI basket",
    "RSP": "Equal-weight S&P 500",
    **SUB_LABELS,
}
SIGNAL_LABELS = {
    "p_sen": "Democratic Senate",
    "p_house": "Democratic House",
    "p_sweep": "Democratic sweep",
    "p_rr": "Republican sweep",
}
INSTRUMENT_LABELS = {
    "NQ": "Nasdaq-100 futures",
    "ES": "S&P 500 futures",
    "RTY": "Russell 2000 futures",
    "NQ-ES": "Nasdaq minus S&P",
    "RTY-ES": "Russell minus S&P",
}
WINDOW_LABELS = {
    "close3_close4": "election-day close to next close",
    "close3_open4": "election-day close to next open",
    "close3_close6": "election-day close to three sessions later",
}
GROUP_LABELS = {"ai": "AI names", "placebo": "Non-AI names", "pooled58": "Both groups pooled"}

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------- formatting


def get(node: Any, *path: str | int) -> Any:
    """Walk dict keys and list indices; ``None`` as soon as a step is missing."""
    for key in path:
        if isinstance(node, Mapping):
            node = node.get(key)
        elif isinstance(node, Sequence) and not isinstance(node, str) and isinstance(key, int):
            node = node[key] if -len(node) <= key < len(node) else None
        else:
            return None
    return node


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def num(v: Any, decimals: int = 2, signed: bool = False) -> str:
    """Fixed decimals with a typographic minus; "not in the results" for a missing value."""
    if not _is_num(v):
        return MISSING
    out = f"{v:+.{decimals}f}" if signed else f"{v:.{decimals}f}"
    if float(out) == 0:  # never print a signed zero
        out = f"{0:.{decimals}f}"
    return out.replace("-", "−")


def pct(v: Any, decimals: int = 2, signed: bool = True) -> str:
    out = num(v, decimals, signed)
    return out if out == MISSING else f"{out}%"


def count(v: Any) -> str:
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else MISSING


def pval(p: Any) -> str:
    if not _is_num(p):
        return MISSING
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def p_eq(p: Any) -> str:
    """'p = 0.507' or 'p < 0.001'."""
    out = pval(p)
    return f"p {out}" if out.startswith("<") else f"p = {out}"


def points(dp: Any, decimals: int = 1, signed: bool = False) -> str:
    """A probability change as points: 0.2545 -> '25.5 points'."""
    if not _is_num(dp):
        return MISSING
    return f"{num(100 * dp, decimals, signed)} points"


def span(ci: Any, decimals: int = 2, unit: str = "%") -> str:
    """'−1.65% to +0.52%' from a [low, high] pair."""
    if not (isinstance(ci, Sequence) and len(ci) == 2 and all(_is_num(v) for v in ci)):
        return MISSING
    return f"{num(ci[0], decimals, True)}{unit} to {num(ci[1], decimals, True)}{unit}"


def day(iso: Any, year: bool = True) -> str:
    """'2026-11-03' -> '3 Nov 2026'."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return MISSING
    out = f"{d.day} {_MONTHS[d.month - 1]}"
    return f"{out} {d.year}" if year else out


def _spans_zero(ci: Any) -> bool:
    return bool(ci) and ci[0] <= 0 <= ci[1]


def _lag(lag: int) -> str:
    """A signed lag with a typographic minus: -1 -> '−1'."""
    return f"{lag:+d}".replace("-", "−")


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------- bundle look-ups


def verdicts(res: Results) -> tuple[str, str]:
    """(H1 verdict, H2 verdict) exactly as the bundle's pre-registered table gave them."""
    return (
        str(get(res, "headline", "h1_verdict") or MISSING),
        str(get(res, "headline", "h2_verdict") or MISSING),
    )


def event_dates(res: Results) -> tuple[str, str]:
    """(election-day close, next close) ISO dates from ``meta.event_window``."""
    found = _ISO_DATE.findall(str(get(res, "meta", "event_window") or ""))
    return (found[0], found[1]) if len(found) >= 2 else ("", "")


def primary_h2(res: Results, group: str = "ai") -> Mapping[str, Any]:
    window = get(res, "h2", "primary_window") or "close3_close4"
    return get(res, "h2", "groups", group, "windows", window) or {}


def sub_of(res: Results) -> dict[str, str]:
    """Ticker -> sub-basket key, from the H5 membership lists."""
    subs = get(res, "h5", "subs") or {}
    return {t: s for s, body in subs.items() for t in body.get("names", [])}


def n_names(res: Results, group: str = "ai") -> Any:
    return get(primary_h2(res, group), "n")


# ---------------------------------------------------------------- headline and scorecard


@dataclass(frozen=True)
class Confidence:
    word: str
    filled: int  # meter segments lit, of 3
    reason: str


@dataclass(frozen=True)
class Card:
    key: str  # "H1" | "H2"
    question: str
    verdict: str
    finding: str
    confidence: Confidence


_H1_HEAD = {
    H1_AI: "AI stocks carried a partisan beta",
    H1_SHARED: "Stocks moved with Senate odds, but AI stocks no more than the rest",
    H1_BOUNDED: "AI stocks carried no partisan beta of a size this test could see",
    H1_NOISY: "Too noisy to tell whether AI stocks carried a partisan beta",
}
_H2_HEAD = {
    H2_YES: "pre-election betas picked the election-night winners",
    H2_NO: "pre-election betas did not predict election night",
}
_FILLED = {"Low": 1, "Medium": 2, "High": 3}


def headline(res: Results) -> str:
    """The plain one-line answer, built only from the two pre-registered verdicts."""
    v1, v2 = verdicts(res)
    return f"{_H1_HEAD.get(v1, v1)}, and {_H2_HEAD.get(v2, v2)}"


def headline_technical(res: Results) -> str:
    """The bundle's own headline sentence, shown as written."""
    return str(get(res, "headline", "sentence") or MISSING)


def _h1_reason(verdict: str, level: str) -> str:
    if verdict == H1_NOISY:
        return "The estimate is too imprecise to rule a partisan beta in or out."
    if verdict == H1_BOUNDED:
        return "A null with a tight bound: anything larger would likely have shown up."
    if verdict == H1_SHARED:
        return "The link is there, but the non-AI basket shares it."
    if level == "High":
        return "The main test, the placebo check, election night and the walk-forward all agree."
    return "The main test and the placebo check pass; high needs election night to agree too."


def _h2_reason(verdict: str, level: str) -> str:
    if verdict == H2_NO:
        return "One election night is a single observation, and the test did not pass on it."
    if level == "Medium":
        return "Election night and the out-of-sample walk-forward point the same way."
    return "It held on one night only; the out-of-sample walk-forward did not confirm it."


def confidence(res: Results, key: str) -> Confidence:
    level = str(get(res, "headline", f"{key.lower()}_confidence") or MISSING)
    verdict = verdicts(res)[0 if key == "H1" else 1]
    reason = _h1_reason(verdict, level) if key == "H1" else _h2_reason(verdict, level)
    return Confidence(level, _FILLED.get(level, 0), reason)


def h1_finding(res: Results) -> str:
    ai, verdict = get(res, "h1", "ai") or {}, verdicts(res)[0]
    b, mde = get(ai, "b10_pct"), pct(get(ai, "mde10_pct"), signed=False)
    est = (
        f"The AI basket's estimated move is {pct(b)} for every +10 points of Democratic Senate "
        f"odds, with a 90% range of {span(get(ai, 'ci10_pct'))}."
    )
    if verdict == H1_NOISY:
        return (
            f"{est} The range includes zero, and the test could only have reliably detected an "
            f"effect of about {mde} per 10 points or more."
        )
    if verdict == H1_BOUNDED:
        return (
            f"{est} The range includes zero, and an effect of about {mde} per 10 points or more "
            "would likely have been detected."
        )
    way = "rose" if _is_num(b) and b > 0 else "fell"
    lead = (
        f"AI names {way} about {pct(abs(b) if _is_num(b) else b, signed=False)} for every "
        "+10 points of Democratic Senate odds"
    )
    if verdict == H1_SHARED:
        return f"{lead}, but the non-AI basket moved the same way, so it is not an AI effect."
    return f"{lead}, and the non-AI basket did not."


def h2_finding(res: Results) -> str:
    w, verdict = primary_h2(res), verdicts(res)[1]
    p = f"one-sided {p_eq(get(w, 'p_one'))}"
    if verdict == H2_YES:
        return (
            "Names with higher pre-election betas did better on election night "
            f"(rank correlation {num(get(w, 'rho'), signed=True)}, {p})."
        )
    return f"Names with higher pre-election betas did not do better on election night ({p})."


def cards(res: Results) -> tuple[Card, Card]:
    v1, v2 = verdicts(res)
    return (
        Card("H1", "Was there a partisan beta?", v1, h1_finding(res), confidence(res, "H1")),
        Card(
            "H2",
            "Did the betas predict election night?",
            v2,
            h2_finding(res),
            confidence(res, "H2"),
        ),
    )


def what_it_means(res: Results) -> list[tuple[str, str]]:
    """(lead, text) points for someone running an AI book into an election. Follows the verdicts."""
    v1, v2 = verdicts(res)
    ai, pl = get(res, "h1", "ai") or {}, get(res, "h1", "placebo") or {}
    mde = pct(get(ai, "mde10_pct"), signed=False)
    n = count(get(ai, "n"))
    out: list[tuple[str, str]] = []
    if v1 == H1_NOISY:
        out.append(
            (
                "No measured beta to size a hedge on.",
                f"Over {n} pre-election sessions the AI basket's sensitivity to Senate odds could "
                "not be told from zero. The data gave no basis for sizing an election hedge on AI "
                "names from prediction-market odds.",
            )
        )
        out.append(
            (
                "That is not the same as no exposure.",
                f"A sensitivity below about {mde} per 10 points would likely have been missed, "
                "so this null does not rule out an exposure of that order. It bounds what the "
                "data could see; it does not measure what was there.",
            )
        )
    elif v1 == H1_BOUNDED:
        out.append(
            (
                "No partisan beta worth hedging was found.",
                f"Over {n} pre-election sessions the estimate could not be told from zero, and an "
                f"effect of about {mde} per 10 points or more would likely have been detected.",
            )
        )
    elif v1 == H1_SHARED:
        out.append(
            (
                "An election effect, not an AI effect.",
                "The AI basket moved with Senate odds, and so did the non-AI basket. A hedge "
                "sized on it is a market hedge, not an AI-specific one.",
            )
        )
    else:
        out.append(
            (
                "A measurable partisan beta.",
                f"{h1_finding(res)} This is a measured sensitivity over {n} sessions, not a causal "
                "claim and not a trading recommendation.",
            )
        )
    out.append(
        (
            "The non-AI basket is the reference point.",
            f"Its estimate is {pct(get(pl, 'b10_pct'))} per 10 points, and an effect of about "
            f"{pct(get(pl, 'mde10_pct'), signed=False)} or more would likely have been detected. "
            "The same method gives a tighter answer on ordinary large caps; the AI estimate "
            "is less precise.",
        )
    )
    b2 = get(res, "h2b", "ai") or {}
    if v2 == H2_NO:
        out.append(
            (
                "Betas were not a guide to who repriced.",
                "Ranking AI names by their pre-election beta would not have picked the "
                "election-night winners. On other large-odds days before the election the same "
                f"ranking averaged {num(get(b2, 'mean'), signed=True)} on a −1 to +1 scale "
                f"(one-sided {p_eq(get(b2, 'p'))}), which is not reliably better than chance.",
            )
        )
    else:
        out.append(
            (
                "Betas ranked the election-night move.",
                f"{h2_finding(res)} One night is one observation; the walk-forward average on "
                f"other large-odds days was {num(get(b2, 'mean'), signed=True)} "
                f"(one-sided {p_eq(get(b2, 'p'))}).",
            )
        )
    out.append(
        (
            "What the night itself looked like (descriptive).",
            "Over the event window the AI names' mean return, after taking out the market and "
            f"bonds, was {pct(get(primary_h2(res), 'mean_ar_pct'))} against "
            f"{pct(get(primary_h2(res, 'placebo'), 'mean_ar_pct'))} for the non-AI names. "
            "That is one night, and the design cannot say what caused it.",
        )
    )
    return out


# ---------------------------------------------------------------- checklist


def checklist_lines(res: Results, key: str) -> list[tuple[str, str]]:
    """(plain line, technical line) per pre-registered check of H1 or H2.

    Status and plain wording come from the bundle; the technical line is formatted here from
    the bundle's numbers."""
    h1, w, b2 = get(res, "h1") or {}, primary_h2(res), get(res, "h2b", "ai") or {}
    holm = get(res, "headline", "holm", "threshold", 0)
    technical = {
        "H1": [
            f"permutation {p_eq(get(h1, 'ai', 'p_perm'))}, Holm threshold {num(holm, 3)}",
            f"AI minus non-AI b = {pct(get(h1, 'diff', 'b10_pct'))} per 10 pts, permutation "
            f"{p_eq(get(h1, 'diff', 'p_perm'))}",
            f"minimum detectable effect = {pct(get(h1, 'ai', 'mde10_pct'), signed=False)} "
            "per 10 pts",
        ],
        "H2": [
            f"Spearman rho = {num(get(w, 'rho'), signed=True)}, one-sided permutation "
            f"{p_eq(get(w, 'p_one'))}",
            f"mean signed rho = {num(get(b2, 'mean'), 3, True)}, n = {count(get(b2, 'n'))} days, "
            f"one-sided {p_eq(get(b2, 'p'))}",
        ],
    }[key]
    rows = get(res, "checklist", key) or []
    out = []
    for i, row in enumerate(rows):
        status = {"✓": "✓ Passed", "✗": "✗ Not passed"}.get(row.get("status"), "· Not scored")
        plain = str(row.get("plain", "")).strip()
        plain = plain[:1].upper() + plain[1:]
        out.append((f"{status}: {plain}", technical[i] if i < len(technical) else ""))
    return out


# ---------------------------------------------------------------- chart text


@dataclass(frozen=True)
class ChartText:
    """The four parts of every chart, plus the expert note and an optional tag."""

    kicker: str
    title: str
    how_to_read: str
    so_what: str
    expert: str
    tag: str | None = None  # EXPLORATORY | DESCRIPTIVE | None
    missing: bool = False


def _guarded(
    kicker: str, tag: str | None = None
) -> Callable[[Callable[..., ChartText]], Callable[..., ChartText]]:
    """A block whose inputs are missing from the bundle says so instead of raising. The cause
    is logged with its traceback, so a malformed bundle or a real bug is not silently hidden."""

    def wrap(fn: Callable[..., ChartText]) -> Callable[..., ChartText]:
        @wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> ChartText:
            try:
                return fn(*args, **kwargs)
            except (KeyError, TypeError, IndexError, ValueError, AttributeError):
                log.warning("Block %r not rendered from the bundle", fn.__name__, exc_info=True)
                return ChartText(kicker, MISSING.capitalize(), "", "", "", tag, missing=True)

        return inner

    return wrap


def _level_pct(log_level: float) -> float:
    """Cumulative log return -> percent change (a chart transform, not a statistic)."""
    return 100 * (math.exp(log_level) - 1)


@_guarded("The signal")
def odds_chart(res: Results, odds: pd.DataFrame) -> ChartText:
    start, end = res["h1"]["ai"]["first"], res["h1"]["ai"]["last"]
    in_sample = (odds["session"] >= start) & (odds["session"] <= end)
    sen = odds[(odds["signal"] == res["meta"]["primary_signal"]) & in_sample]
    first, last = sen.iloc[0], sen.iloc[-1]
    a, b = 100 * first["p"], 100 * last["p"]
    verb = "climbed" if b > a else "fell" if b < a else "ended where they started,"
    return ChartText(
        "The signal",
        f"Odds of a Democratic Senate {verb} from {num(a, 0)}% to {num(b, 0)}% before election day",
        "Each line is a Polymarket price read at the stock-market close, shown as a probability. "
        "The Senate line is the study's signal because that chamber was the one in doubt. After "
        "the election each line sits at its settled value.",
        "This is the input, not a result. The tests below ask whether the day-to-day changes in "
        "the Senate line showed up in AI stocks.",
        f"Daily as-of readings from {day(first['session'])}; a reading too old at the close is "
        f"missing. The pre-election sample ends on {day(end)}. Primary signal: Yes price of the "
        "Democratic-Senate market; the other three are secondary.",
    )


@_guarded("The stocks")
def returns_chart(res: Results, cum: pd.DataFrame) -> ChartText:
    end = res["meta"]["pre_sample"][1]
    row = cum[cum["session"] <= end].iloc[-1]
    ai, pl, mkt = (_level_pct(row[k]) for k in ("ai_composite", "placebo", "RSP"))
    return ChartText(
        "The stocks",
        f"By election day the AI basket was {pct(ai, 0)} since the odds markets opened, against "
        f"{pct(pl, 0)} for the non-AI basket and {pct(mkt, 0)} for the equal-weight S&P 500",
        "Cumulative return of each equal-weight basket from the first session of the sample. "
        "The four thinner coloured lines are the parts of the AI basket. Click a legend entry to "
        "hide a line.",
        "Use this chart to get your bearings, not to judge. Two lines that rise together cannot "
        "tell you whether one responds to the other. The daily-change tests below do that job.",
        f"Equal-weight mean of daily log returns, cumulated and shown as a percent change. "
        f"Baskets are fixed in the pre-registration ({count(n_names(res))} AI names, "
        f"{count(n_names(res, 'placebo'))} non-AI names).",
    )


def _beta_how_to_read() -> str:
    return (
        "Each dot is the estimated change in a basket's daily return for every +10 points of "
        "Democratic Senate odds, after taking out the equal-weight market and long bonds. The "
        "line through the dot is the 90% range. The grey bar is the zone where an effect would "
        "be too small for this test to detect reliably. A range that crosses zero means no "
        "effect was detected."
    )


def h1_title(res: Results) -> str:
    verdict, ai = verdicts(res)[0], res["h1"]["ai"]
    b, mde = ai["b10_pct"], pct(ai["mde10_pct"], signed=False)
    size = pct(abs(b), signed=False)
    way = "rose" if b > 0 else "fell"
    if verdict == H1_AI:
        return (
            f"AI names {way} about {size} for every +10 points of Democratic Senate odds, and "
            "the non-AI basket did not"
        )
    if verdict == H1_SHARED:
        return (
            f"AI names {way} about {size} for every +10 points of Democratic Senate odds, but "
            "so did the non-AI basket"
        )
    if verdict == H1_BOUNDED:
        return (
            "No partisan sensitivity detected: an effect of about "
            f"{mde} per 10 points or more would likely have shown up"
        )
    return (
        "Too noisy to tell: the AI basket's range spans zero, and only an effect of about "
        f"{mde} per 10 points or more could have been detected"
    )


@_guarded("H1 · Was there a partisan beta?")
def h1_chart(res: Results) -> ChartText:
    h1, verdict = res["h1"], verdicts(res)[0]
    ai, pl = h1["ai"], h1["placebo"]
    if verdict == H1_NOISY:
        so_what = (
            f"{VALID_NULL} But it is a weak one: it does not show that AI stocks have no "
            "partisan beta. It shows that the daily data could not tell an effect of up to about "
            f"{pct(ai['mde10_pct'], signed=False)} per 10 points from zero. The non-AI basket is "
            f"the useful contrast: its estimate is pinned near zero (an effect of about "
            f"{pct(pl['mde10_pct'], signed=False)} or more would likely have been detected)."
        )
    elif verdict == H1_BOUNDED:
        so_what = (
            f"{VALID_NULL} The estimate is close to zero and the test was sharp enough to see an "
            f"effect of about {pct(ai['mde10_pct'], signed=False)} per 10 points or more."
        )
    elif verdict == H1_SHARED:
        so_what = (
            "The AI basket moved with Senate odds, but the non-AI basket moved the same way. "
            "This is an election effect on stocks in general, not on the AI trade."
        )
    else:
        so_what = (
            "The AI basket moved with Senate odds and the non-AI basket did not. This is a "
            "measured sensitivity, not a causal claim about policy."
        )
    expert = (
        "Daily close-to-close log return of the basket regressed on the change in P(Democratic "
        f"Senate), {_join(list(h1['controls']))} returns; Newey-West HAC with {h1['hac_lag']} "
        f"lags; n = {count(ai['n'])} sessions, {day(ai['first'])} to {day(ai['last'])}. "
        f"AI basket: b = {pct(ai['b10_pct'], 3)} per +10 pts (HAC se {num(ai['se10_pct'], 3)}, "
        f"HAC {p_eq(ai['p_hac'])}), R² {num(ai['r2'], 3)}, partial R² of the odds change "
        f"{num(ai['partial_r2'], 3)}. Reported p-value: circular-shift permutation, "
        f"{p_eq(ai['p_perm'])} ({count(ai['n_shifts'])} draws from "
        f"{count(ai['n_distinct_shifts'])} distinct shifts). Holm threshold for the primary "
        f"family: {num(get(res, 'headline', 'holm', 'threshold', 0), 3)}. Minimum detectable "
        f"effect at 80% power: {pct(ai['mde10_pct'], 3, signed=False)} per 10 pts."
    )
    return ChartText(
        "H1 · Was there a partisan beta?", h1_title(res), _beta_how_to_read(), so_what, expert
    )


def mde_plain(res: Results) -> str:
    """The detectable effect size, in plain words."""
    ai = get(res, "h1", "ai") or {}
    bound = next(
        (
            r.get("name", "")
            for r in get(res, "checklist", "H1") or []
            if "MDE" in r.get("name", "")
        ),
        "",
    )
    rule = f" The pre-registered bar for calling a null bounded was {bound}." if bound else ""
    return (
        "What size of effect could this test see? With 80% power we could have detected a move "
        f"of about {pct(get(ai, 'mde10_pct'), signed=False)} in the AI basket for every +10 "
        f"points of Senate odds. Anything smaller could be there and go unnoticed.{rule}"
    )


_ROBUSTNESS_NAMES = (
    ("baseline", "Baseline (as pre-registered)"),
    ("SPY instead", "Cap-weighted S&P 500 as the market control"),
    ("no controls", "No market or bond control"),
    ("logit", "Odds change measured in log-odds"),
    ("E4 p_house", "House odds as the signal"),
    ("E4 p_sweep", "Democratic-sweep odds as the signal"),
    ("E4 p_rr", "Republican-sweep odds as the signal"),
    ("drop", "Without the largest odds-move days"),
)


def _hac_only(row: Mapping[str, Any], alpha: Any) -> bool:
    """Below alpha on the HAC p but not on the permutation p (the reported one)."""
    p_hac, p_perm = row.get("p_hac"), row.get("p_perm")
    if not (_is_num(alpha) and _is_num(p_hac) and _is_num(p_perm)):
        return False
    return p_hac < alpha <= p_perm


def robustness_table(res: Results) -> list[dict[str, str]]:
    """Display rows of the H1 robustness checks (AI basket)."""
    rows = []
    for r in get(res, "robustness") or []:
        name = str(r.get("name", ""))
        label = next((plain for key, plain in _ROBUSTNESS_NAMES if name.startswith(key)), name)
        logit = "unit" in r
        kind = "Exploratory (E4)" if name.startswith("E4") else "Robustness"
        rows.append(
            {
                "Check": label,
                "Kind": kind,
                "Estimate": pct(r.get("b10_pct")),
                "90% range": span(r.get("ci10_pct")),
                "Unit": "per +0.1 log-odds" if logit else "per +10 points",
                "HAC p": pval(r.get("p_hac")),
                "Permutation p": pval(r.get("p_perm")),
                "Sessions": count(r.get("n")),
            }
        )
    return rows


def robustness_note(res: Results) -> str:
    rows = get(res, "robustness") or []
    alpha = get(res, "headline", "holm", "alpha")
    if not rows or not _is_num(alpha):
        return MISSING.capitalize() + "."
    hit = [r for r in rows if _is_num(r.get("p_perm")) and r["p_perm"] < alpha]
    hac_only = [r for r in rows if _hac_only(r, alpha)]
    if hit:
        lead = (
            f"{len(hit)} of {len(rows)} rows have a permutation p below {num(alpha)}, before any "
            "correction for the number of rows."
        )
    else:
        lead = f"No row has a permutation p below {num(alpha)}."
    extra = ""
    if hac_only:
        table = robustness_table(res)
        names = _join(
            [t["Check"].lower() for r, t in zip(rows, table, strict=True) if r in hac_only]
        )
        extra = (
            f" Below {num(alpha)} on the HAC p only, and not on the permutation p: {names}. "
            f"Uncorrected across {len(rows)} rows, that is not read as evidence."
        )
    return (
        f"{lead}{extra} The log-odds row is in a different unit and cannot be compared in size "
        "with the others."
    )


@_guarded("H5 · Which part of the AI trade?")
def h5_chart(res: Results) -> ChartText:
    subs, wald = res["h5"]["subs"], res["h5"]["wald_equal"]
    alpha = res["headline"]["holm"]["alpha"]
    hits = [SUB_LABELS.get(k, k) for k, v in subs.items() if v["bh_reject"]]
    if hits:
        title = f"{_join(hits)} moved with Senate odds; the other parts show no clear link"
    else:
        title = "No part of the AI trade shows a clear link to Senate odds on its own"
    signs = {k: v["b10_pct"] > 0 for k, v in subs.items()}
    odd = [k for k, pos in signs.items() if list(signs.values()).count(pos) == 1]
    so_what = VALID_NULL if not hits else "This is a secondary test, corrected across the parts."
    if wald["p"] < alpha:
        so_what += (
            f" One joint test says the four estimates are not all equal (Wald {p_eq(wald['p'])})"
        )
        if len(odd) == 1:
            so_what += f", with {SUB_LABELS.get(odd[0], odd[0]).lower()} on the other side of zero"
        so_what += (
            ". That is a single secondary test with no part individually different from zero: "
            "a lead for the next election, not a result."
        )
    else:
        so_what += f" A joint test does not separate the four estimates (Wald {p_eq(wald['p'])})."
    parts = "; ".join(
        f"{SUB_LABELS.get(k, k)} {pct(v['b10_pct'])} ({span(v['ci10_pct'])}, permutation "
        f"{p_eq(v['p_perm'])}, BH-adjusted {p_eq(v['p_bh'])})"
        for k, v in subs.items()
    )
    expert = (
        f"The H1 regression per sub-basket. {parts}. Family: {res['h5']['family']}. Wald test of "
        f"equal b: W = {num(wald['wald'])}, df {wald['df']}, {p_eq(wald['p'])}."
    )
    return ChartText(
        "H5 · Which part of the AI trade?", title, _beta_how_to_read(), so_what, expert
    )


def h2_title(res: Results) -> str:
    if verdicts(res)[1] == H2_YES:
        return "Names with higher pre-election betas did better on election night"
    return (
        "No visible link of the kind the plan tested: names with higher pre-election betas "
        "did not do better on election night"
    )


def h2_exploratory_note(res: Results) -> str | None:
    """The one plain mention of an observed correlation against the pre-registered direction."""
    w = primary_h2(res)
    rho = get(w, "rho")
    if verdicts(res)[1] == H2_YES or not _is_num(rho) or rho >= 0:
        return None
    return (
        f"Exploratory, not a finding: the observed rank correlation was negative "
        f"({num(rho, signed=True)}, 90% range {span(get(w, 'ci90'), unit='')}, two-sided "
        f"{p_eq(get(w, 'p_two'))}). The frozen test was one-sided in the opposite direction, "
        "this is one night, and nothing here is corrected for the number of tests run."
    )


@_guarded("H2 · Did the betas predict election night?")
def h2_chart(res: Results) -> ChartText:
    h2, w, wp = res["h2"], primary_h2(res), primary_h2(res, "placebo")
    start, end = event_dates(res)
    if verdicts(res)[1] == H2_YES:
        so_what = (
            "Stocks that had moved more with Senate odds before the election did better when "
            "the odds jumped. One night is one observation, so the walk-forward below matters."
        )
    else:
        so_what = (
            f"{VALID_NULL} Ranking AI names by their pre-election beta would not have picked the "
            f"election-night winners. As a group the AI names returned {pct(w['mean_ar_pct'])} "
            f"over the window after taking out the market and bonds, against "
            f"{pct(wp['mean_ar_pct'])} for the non-AI names: a group-wide move that the "
            "pre-election betas did not point to."
        )
    two = "" if h2_exploratory_note(res) else f" (two-sided {p_eq(w['p_two'])})"
    expert = (
        f"Per-stock b from the H1 regression on sessions up to {day(h2['est_end'])} "
        f"({count(get(h2, 'groups', 'ai', 'n_est'))} sessions). Abnormal return = return minus "
        "the stock's own market and bond terms. Senate odds changed by "
        f"{points(h2['event_dp_sen'], signed=True)} over the window. Spearman rho across "
        f"{count(w['n'])} AI names = {num(w['rho'], 3, True)}, one-sided {p_eq(w['p_one'])}{two} "
        f"by {count(w['n_perm'])} label permutations. Non-AI names: rho = "
        f"{num(wp['rho'], 3, True)}, one-sided {p_eq(wp['p_one'])}. The direction of the test was "
        "fixed from the sign of the odds move, which was known before the freeze (amendment A1)."
    )
    return ChartText(
        "H2 · Did the betas predict election night?",
        h2_title(res),
        "Each dot is one stock. Left to right: its sensitivity to Senate odds, measured before "
        f"election week. Bottom to top: its return from the {day(start, False)} close to the "
        f"{day(end, False)} close, after taking out the market and bonds. If the betas had "
        "worked, the dots in the left panel would rise from left to right. The right panel "
        "shows the non-AI names for comparison.",
        so_what,
        expert,
    )


def h2_windows_table(res: Results) -> list[dict[str, str]]:
    """Rank correlation per group and window, with the pre-registered one-sided p."""
    rows = []
    for group, body in (get(res, "h2", "groups") or {}).items():
        for window in get(res, "h2", "windows") or []:
            w = get(body, "windows", window) or {}
            rows.append(
                {
                    "Group": GROUP_LABELS.get(group, group),
                    "Window": WINDOW_LABELS.get(window, window),
                    "Rank correlation": num(w.get("rho"), 2, True),
                    "One-sided p": pval(w.get("p_one")),
                    "Mean abnormal return": pct(w.get("mean_ar_pct")),
                    "Names": count(w.get("n")),
                }
            )
    return rows


@_guarded("H2b · Beyond one night")
def h2b_chart(res: Results) -> ChartText:
    b, ai, pl = res["h2b"], res["h2b"]["ai"], res["h2b"]["placebo"]
    passed = ai["p"] is not None and ai["p"] < 0.10 and ai["mean"] > 0  # the checklist's bar
    row = get(res, "checklist", "H2", 1, "status")
    if row is not None:
        passed = row == "✓"
    title = (
        "On other large-odds days the betas ranked stocks in the right direction"
        if passed
        else "On other large-odds days the betas ranked stocks no better than chance"
    )
    so_what = (
        f"The average score is {num(ai['mean'], signed=True)} over {count(ai['n'])} days "
        f"(one-sided {p_eq(ai['p'])}); for the non-AI names it is {num(pl['mean'], signed=True)} "
        f"({p_eq(pl['p'])}). "
    )
    so_what += (
        "Out of sample, the betas carried ranking information."
        if passed
        else f"Out of sample, the betas carried no reliable ranking information. {VALID_NULL}"
    )
    return ChartText(
        "H2b · Beyond one night",
        title,
        "Each bar is one pre-election day with a large move in Senate odds. The betas are "
        "re-estimated using only earlier days, then scored on how well they ranked that day's "
        "stock moves: above zero means the right direction, below zero the wrong one. The "
        "dashed line is the average.",
        so_what,
        f"Walk-forward after the first {count(b['warmup'])} sessions: days whose absolute odds "
        f"change is at or above the running {num(100 * b['top_quantile'], 0)}th percentile to "
        "date; b estimated on earlier sessions only; score = sign of the odds change × Spearman "
        f"rho of b against that day's abnormal returns. t = {num(ai['t'])}. Ties at the threshold "
        "are all included, so more than a tenth of days qualify (amendment A2).",
    )


def _clears_zero(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    return [r["lag"] for r in rows if not _spans_zero(r["ci10_pct"])]


@_guarded("H3 · Election night, minute by minute", DESCRIPTIVE)
def h3_night_chart(res: Results) -> ChartText:
    h3 = res["h3"]
    return ChartText(
        "H3 · Election night, minute by minute",
        "Senate odds and index futures through election night, on one clock",
        "Top: Polymarket odds. Bottom: each index future as a percent change from the start of "
        "the evening window. Both panels share the same clock in Eastern Time, so you can look "
        "straight down from a jump in the odds to the futures. A flat odds line at the end is "
        "the market after it settled.",
        f"{H3_LABEL}. Read it as a picture of the night, not as a test.",
        f"Five-minute bars, {count(h3['n_window_bars'])} in the window. "
        f"{num(100 * h3['share_fresh_odds'], 0)}% of bars have a fresh odds reading and "
        f"{num(100 * h3['share_resolved'], 0)}% fall after the Senate market resolved, where the "
        "odds change is zero by rule (amendment A1).",
        DESCRIPTIVE,
    )


@_guarded("H3 · Did futures follow the odds that night?", DESCRIPTIVE)
def h3_lag_chart(res: Results) -> ChartText:
    h3 = res["h3"]
    nq = h3["instruments"]["NQ"]["rows"]
    clear = _clears_zero(nq)
    if clear:
        title = (
            "Some bars clear zero on this one night, with "
            + (
                "mixed signs"
                if len({r["b10_pct"] > 0 for r in nq if r["lag"] in clear}) > 1
                else "one sign"
            )
            + ": a pattern to note, not evidence of an ordering"
        )
    else:
        title = "No bar clears zero on this one night"
    lags = _join([_lag(x) for x in clear])
    seen = f" For Nasdaq futures the bars at lag {lags} clear zero." if clear else ""
    spreads = "; ".join(
        f"{INSTRUMENT_LABELS.get(k, k)}: lags clearing zero "
        + (_join([_lag(x) for x in _clears_zero(v["rows"])]) or "none")
        for k, v in h3["instruments"].items()
    )
    return ChartText(
        "H3 · Did futures follow the odds that night?",
        title,
        "Each bar is the futures move per +10 points of Senate odds at one time offset, in "
        "five-minute steps. Bars to the right of zero pair a futures move with an earlier odds "
        "move; bars to the left pair it with a later one. The thin lines are 90% ranges.",
        f"{H3_LABEL}.{seen} With a single night there is nothing to compare it against.",
        f"One joint distributed-lag regression per instrument on "
        f"{count(nq and h3['instruments']['NQ']['n_bars'])} bars, HAC. {spreads}.",
        DESCRIPTIVE,
    )


def h4_title(res: Results) -> str:
    h4 = res["h4"]
    verdict, rows = h4["verdict"], h4["rows"]
    if verdict == "no detectable ordering":
        if any(r["beyond_band"] for r in rows):
            return (
                "No detectable ordering between Senate odds and AI stocks: only isolated bars "
                "poke out of the noise zone"
            )
        return (
            "No detectable ordering between Senate odds and AI stocks: every bar sits in the "
            "noise zone"
        )
    peak = max(rows, key=lambda r: abs(r["t"]))["lag"]
    hours = f"{abs(peak)} hour" + ("" if abs(peak) == 1 else "s")
    if verdict == "odds first":
        return f"Senate odds tended to move about {hours} before AI stocks"
    if verdict == "stocks first":
        return f"AI stocks tended to move about {hours} before Senate odds"
    return "Senate odds and AI stocks moved in the same hour, so neither had a head start"


@_guarded("H4 · Who moved first?")
def h4_chart(res: Results) -> ChartText:
    h4 = res["h4"]
    null = h4["verdict"] == "no detectable ordering"
    best = min(h4["rows"], key=lambda r: r["p_bh"])
    so_what = (
        f"{VALID_NULL} Hour by hour, there is no sign that the prediction market moved ahead of "
        "AI stocks or behind them."
        if null
        else "This is a secondary test on hourly data; it describes timing, not cause."
    )
    return ChartText(
        "H4 · Who moved first?",
        h4_title(res),
        "Each bar is the strength of the link between the hourly move in the AI basket and the "
        "hourly change in Senate odds at one time offset. Right of zero: the odds moved earlier. "
        "Left of zero: the stocks moved earlier. Bars inside the grey zone are what chance "
        "alone produces.",
        so_what,
        f"Regular-session hours, pre-election sample, {count(h4['n_sessions'])} sessions. AI "
        f"basket hourly return residualised on {_join(list(h4['residual_on']))}; one HAC "
        "regression per lag; Benjamini-Hochberg across the lags. Noise zone: 95% band of the "
        f"largest absolute t over {count(h4['n_shifts'])} whole-session shifts = "
        f"{num(h4['band_max_abs_t_95'])}. Smallest adjusted p: lag "
        f"{_lag(best['lag'])} h, b = {pct(best['b10_pct'], 3)} per 10 pts, "
        f"BH {p_eq(best['p_bh'])}.",
    )


@_guarded("E2 · Volatility term structure", EXPLORATORY)
def e2_term_chart(res: Results) -> ChartText:
    years = [e[:4] for e in res["exploratory"]["e2"]["elections"]]
    return ChartText(
        "E2 · Volatility term structure",
        f"Index volatility around the {years[-1]} election, next to {_join(years[:-1])}",
        "Day 0 is election day; the x-axis counts trading sessions. Top: short-dated against "
        "one-month S&P implied volatility; above 1 means the market pays up for the days just "
        "ahead. Middle: one-month against three-month. Bottom: Nasdaq minus S&P implied "
        "volatility, in vol points. The coloured line is the latest election.",
        f"{EXPLORATORY}. {len(years)} elections are {len(years)} data points: this shows what "
        "happened, and it cannot show what is typical.",
        "Ratios of Cboe indices at the daily close: VIX9D/VIX, VIX/VIX3M and VXN − VIX. "
        "No test is run on these.",
        EXPLORATORY,
    )


@_guarded("E2 · Implied against realised", EXPLORATORY)
def e2_moves_chart(res: Results) -> ChartText:
    moves = res["exploratory"]["e2"]["moves"]
    keys = sorted(moves)
    last = moves[keys[-1]]
    year = keys[-1][:4]
    earlier = [moves[k] for k in keys[:-1]]
    below = last["ratio_abs_realised_to_implied"] < 1
    same = [m for m in earlier if (m["ratio_abs_realised_to_implied"] < 1) == below]
    side = "inside" if below else "outside"
    if not same:
        other = "outside" if below else "inside"
        tail = f"; in the {len(earlier)} earlier elections shown it landed {other}"
    elif len(same) == len(earlier):
        tail = f", as in the {len(earlier)} earlier elections shown"
    else:
        tail = f", as in {len(same)} of the {len(earlier)} earlier elections shown"
    w = primary_h2(res)
    return ChartText(
        "E2 · Implied against realised",
        f"In {year} the Nasdaq-100's next-day move landed {side} what options had priced{tail}",
        "Each grey bar is the one-day move that Nasdaq options implied on election day, drawn "
        "both ways from zero. The dot is what the index did the next session. A dot outside the "
        "bar means the move was bigger than priced.",
        f"{EXPLORATORY}. In {year} options implied a one-day move of "
        f"{pct(last['implied_1d_pct'], signed=False)} and the index moved "
        f"{pct(last['realised_next_day_pct'])}. Over the same window the AI names' mean return "
        f"after market and bonds was {pct(get(w, 'mean_ar_pct'))}. The two figures measure "
        "different things, an index and a basket of single names, and are shown side by side "
        "with no claim that one explains the other. One night; descriptive.",
        "Implied one-day move = VXN / √(trading days in a year) at the election-day close. "
        + "; ".join(
            f"{k[:4]}: implied {pct(moves[k]['implied_1d_pct'], signed=False)}, realised "
            f"{pct(moves[k]['realised_next_day_pct'])}, ratio "
            f"{num(moves[k]['ratio_abs_realised_to_implied'])}"
            for k in keys
        )
        + ".",
        EXPLORATORY,
    )


@_guarded("E1 · Was the sensitivity stable?", EXPLORATORY)
def e1_chart(res: Results, rolling: pd.DataFrame | None = None) -> ChartText:
    """Built from ``exploratory.e1`` alone; the rolling series only adds its range."""
    e1 = res["exploratory"]["e1"]
    shift = e1["last30_minus_before_b10_pct"]
    way = "lower" if shift < 0 else "higher"
    swing = ""
    if rolling is not None and len(rolling) and "b10_pct" in rolling.columns:
        lo, hi = rolling["b10_pct"].min(), rolling["b10_pct"].max()
        sides = ", on both sides of zero" if lo < 0 < hi else ""
        swing = (
            f" Across the year the rolling estimate ranged from {pct(lo, 1)} to {pct(hi, 1)} "
            f"per 10 points{sides}."
        )
    return ChartText(
        "E1 · Was the sensitivity stable?",
        "The estimate was not stable through the year: it was "
        f"{pct(abs(shift), 1, signed=False)} per 10 points {way} in the last sessions before the "
        "election, a split made after the fact",
        f"The line is the H1 estimate re-run on each trailing window of {count(e1['window'])} "
        "sessions. The shaded band is its 90% range. Where the band covers zero, that window "
        "shows no detectable sensitivity.",
        f"{EXPLORATORY}.{swing} Before {day(e1['last30_start'])} the estimate was "
        f"{pct(e1['before_b10_pct'])} per 10 points; from that date it was {pct(shift)} against "
        f"before (90% range {span(e1['last30_minus_before_ci10_pct'])}). The split point was "
        "not chosen in advance and the late slice covers one regime, so this is a hypothesis "
        "for the next election, not a result.",
        f"Rolling {count(e1['window'])}-session regression, same specification as H1. Late-sample "
        f"shift from an interaction term, HAC {p_eq(e1['p_hac'])}, uncorrected and post hoc.",
        EXPLORATORY,
    )


@_guarded("E3 · State data-centre moratorium markets", EXPLORATORY)
def e3_chart(res: Results) -> ChartText:
    e3 = res["exploratory"]["e3"]
    clear = not _spans_zero(e3["ci90"])
    title = (
        "Moratorium odds and power stocks moved together over a short sample"
        if clear
        else "No clear link between moratorium odds and power stocks over a short sample"
    )
    return ChartText(
        "E3 · State data-centre moratorium markets",
        title,
        "Each dot is one trading day. Left to right: the average change in Polymarket odds that "
        "a state passes a data-centre moratorium. Bottom to top: the power and data-centre "
        "basket's return minus the utilities sector that day.",
        f"{EXPLORATORY}. {count(e3['n'])} sessions is too short a sample to conclude anything "
        "in either direction.",
        f"Spearman rho = {num(e3['rho'], signed=True)}, 90% range {span(e3['ci90'], unit='')}, "
        f"two-sided {p_eq(e3['p_two'])}, n = {count(e3['n'])}.",
        EXPLORATORY,
    )


@_guarded("E5 · After the election", EXPLORATORY)
def e5_chart(res: Results) -> ChartText:
    e5 = res["exploratory"]["e5"]
    total, after = e5["car_top_minus_bottom_pct"], e5["car_top_minus_bottom_ex_event_day_pct"]
    verb = "trailed" if total < 0 else "beat"
    if (total < 0) != (after < 0):  # the sign flipped once the event day is left out
        tail = f"after the event day the gap ran the other way ({pct(after, 1)})"
    else:
        tail = f"the gap kept going the same way after the event day ({pct(after, 1)})"
    return ChartText(
        "E5 · After the election",
        f"High-beta names {verb} low-beta names by {pct(abs(total), 1, signed=False)} through "
        f"{day(e5['end'], False)}; {tail}",
        "Cumulative return after market and bonds for the third of AI names with the highest "
        "pre-election betas, the third with the lowest, and the difference between them.",
        f"{EXPLORATORY}. {count(len(e5['top']))} names in each group over a handful of "
        "sessions: a description of what followed, with no test behind it.",
        f"Top minus bottom tercile from {day(e5['start'])} to {day(e5['end'])}: {pct(total)}; "
        f"excluding the event day: {pct(after)}.",
        EXPLORATORY,
    )


def chart_texts(res: Results, series: Mapping[str, pd.DataFrame]) -> dict[str, ChartText]:
    """Every chart block of the page, keyed by a short id (page order)."""
    odds, cum = series.get("odds_daily"), series.get("cum_log_returns")
    absent = ChartText("", MISSING.capitalize(), "", "", "", missing=True)
    return {
        # Built from a chart series only: without the series there is nothing to try.
        "odds": odds_chart(res, odds) if odds is not None else replace(absent, kicker="The signal"),
        "returns": returns_chart(res, cum)
        if cum is not None
        else replace(absent, kicker="The stocks"),
        "h1": h1_chart(res),
        "h5": h5_chart(res),
        "h2": h2_chart(res),
        "h2b": h2b_chart(res),
        "h3_night": h3_night_chart(res),
        "h3_lags": h3_lag_chart(res),
        "h4": h4_chart(res),
        "e2_term": e2_term_chart(res),
        "e2_moves": e2_moves_chart(res),
        "e1": e1_chart(res, series.get("e1_rolling")),
        "e3": e3_chart(res),
        "e5": e5_chart(res),
    }


# ---------------------------------------------------------------- set-up, methods, limits


def setup_text(res: Results) -> str:
    start, end = event_dates(res)
    return (
        "Democrats took both chambers in the midterm. The House was expected to flip; the Senate "
        "was the chamber in doubt, so the Polymarket odds of a Democratic Senate are the signal "
        f"used throughout. Between the {day(start, False)} close and the {day(end, False)} close "
        f"those odds moved by {points(get(res, 'h2', 'event_dp_sen'), signed=True)}."
    )


def methods(res: Results) -> list[tuple[str, list[str]]]:
    """'How this was done': four blocks of (heading, points)."""
    ai, h2 = get(res, "h1", "ai") or {}, primary_h2(res)
    age = get(res, "coverage", "odds_daily", "in_life", "median_s")
    age_note = (
        f" The median odds reading at a daily close was {num(age, 0)} seconds old."
        if _is_num(age)
        else ""
    )
    return [
        (
            "What a specialist does that a casual look misses",
            [
                "Factor-neutral returns. Each basket's return is measured after taking out the "
                "market and long bonds, so a general risk-on day is not mistaken for an election "
                "effect.",
                "An equal-weight market control. AI names dominate cap-weighted indices, so a "
                "cap-weighted control would absorb the very effect being tested. The control "
                "here is the equal-weight S&P 500; the cap-weighted version is a robustness row.",
                f"A placebo basket. {count(n_names(res, 'placebo'))} large caps with no AI "
                "thesis, picked before any return was seen, go through the same tests. An effect "
                "they share is not an AI effect.",
                "A fixed event window on abnormal returns. Election night is measured from the "
                "election-day close to the next close, against each stock's own market and bond "
                "sensitivity, not as a raw price change.",
                "Power, so a null is bounded. The smallest effect the test could reliably detect "
                "is reported next to every null, so 'nothing found' is never read as 'nothing "
                "there'.",
                "Out-of-sample checks. Betas are scored on days they were not estimated on "
                "(walk-forward), and election week is kept out of the betas tested on election "
                "night.",
            ],
        ),
        (
            "Primary sources",
            [
                "Polymarket CLOB order-book price history for the odds, sampled as-of: the last "
                "trade price at or before each timestamp, never after." + age_note,
                "Polymarket Gamma market rules and resolutions, to pick the markets by their "
                "resolution text and to know when each one settled.",
                "The exchange session calendar (NYSE), for session closes, early closes and "
                "daylight-saving changes.",
                "Yahoo Finance price bars for the stocks, the index futures on election night, "
                "and the Cboe volatility indices.",
            ],
        ),
        (
            "Methods and tools",
            [
                "Regression with HAC (Newey-West) standard errors, "
                f"{count(get(res, 'h1', 'hac_lag'))} lags on daily data.",
                f"Circular-shift permutation of the odds series ({count(get(ai, 'n_shifts'))} "
                f"draws from {count(get(ai, 'n_distinct_shifts'))} distinct shifts) for the "
                "reported p-values, which keeps the autocorrelation of both series intact.",
                f"Spearman rank correlation with {count(get(h2, 'n_perm'))} permutations of the "
                "stock labels for the cross-section.",
                "Holm correction across the two primary tests; Benjamini-Hochberg within each "
                "secondary family.",
                "An event study around election night, and a five-minute distributed-lag "
                "regression for the night itself.",
                "A DuckDB, Parquet and pandas pipeline: raw pulls are immutable, clean tables "
                "are derived, and every timestamp is UTC.",
                "A pre-registration frozen before any return was compared with odds, with dated "
                "amendments, and an independent validator agent that re-checks each step.",
            ],
        ),
        (
            "How usefulness was tested",
            [
                "A verdict table written in advance. Each headline is the row of that table the "
                "numbers land in, applied mechanically.",
                "A minimum detectable effect next to the main null "
                f"({pct(get(ai, 'mde10_pct'), signed=False)} per 10 points for the AI basket).",
                "Placebo names through the same tests, so an effect has to be specific to AI.",
                f"A walk-forward test over {count(get(res, 'h2b', 'ai', 'n'))} large-odds days, "
                "so 'did it predict' does not rest on one night.",
                f"{count(len(get(res, 'robustness') or []))} robustness and alternative-signal "
                "rows, shown whether or not they agree.",
            ],
        ),
    ]


def does_not_show(res: Results) -> list[str]:
    """'What this does not show', following the verdicts."""
    v1, v2 = verdicts(res)
    mde = pct(get(res, "h1", "ai", "mde10_pct"), signed=False)
    out = []
    if v1 == H1_NOISY:
        out.append(
            "It does not show that AI stocks have no partisan beta. The estimate is too "
            f"imprecise: an effect up to about {mde} per 10 points could have been missed."
        )
    elif v1 == H1_BOUNDED:
        out.append(f"It does not rule out a partisan beta smaller than about {mde} per 10 points.")
    else:
        out.append(
            "It does not show why the sensitivity exists. A measured co-movement is not a "
            "causal claim about policy."
        )
    if v2 == H2_NO:
        out.append(
            "It does not show that betas are useless in general. It shows they did not rank "
            "this election night, and did not rank other large-odds days reliably."
        )
    else:
        out.append("It does not show that betas will rank the next election night.")
    out += [
        "One midterm is one observation of the event. Only the pre-election daily and hourly "
        "samples have more than one.",
        "Election night, the volatility charts and every block tagged exploratory describe what "
        "happened. They are not tests.",
        "Nothing here is causal, and nothing is a trading recommendation.",
    ]
    return out


DISCLOSURE = (
    "This is a retrospective study: the plan was frozen after the election, so it could not be "
    "blind to the outcome. Before the freeze the following had been seen: who won each chamber, "
    "a handful of Polymarket price points, the hourly Nasdaq futures path on election night and "
    "the last prices of a few tickers. No return series of the AI names against the odds, no "
    "regression, correlation, basket return or volatility path had been seen. Because the "
    "futures path had been seen, the election-night block is capped at descriptive. The "
    "direction of the H2 test rests on the sign of the election-night odds move, which was "
    "known. Changes and disclosures made after the freeze are dated amendments (A1, A2, A3) in "
    "the pre-registration."
)


def amendments(res: Results) -> list[str]:
    """The dated amendments of the pre-registration, in plain words (no rule or verdict changed
    by A2 or A3). Numbers come from the bundle; the validator's own recomputations are not in
    it and are described without figures."""
    ai = get(res, "h1", "ai") or {}
    drop = next(
        (r for r in get(res, "robustness") or [] if str(r.get("name", "")).startswith("drop")), {}
    )
    return [
        "A1, before any return was compared with odds: once a market has settled its price is "
        "its last traded price; returns and staleness limits were pinned down; and the "
        "direction of the H2 test was disclosed as resting on a known sign.",
        "A2, after the run, disclosure only: odds move in coarse steps, so the walk-forward "
        "keeps every day tied at its threshold and scores "
        f"{count(get(res, 'h2b', 'ai', 'n'))} days; the H1 permutation draws "
        f"{count(get(ai, 'n_shifts'))} times from {count(get(ai, 'n_distinct_shifts'))} distinct "
        "shifts; and the H2 correlation came out against the tested direction.",
        "A3, from the independent validation, disclosure only: the first odds change in the "
        "sample is the market finding its opening level after a week without trades, not news. "
        "It stays in under the frozen sample rule, and the pre-registered row without the "
        f"largest odds-move days covers it ({pct(drop.get('b10_pct'))} per 10 points, "
        f"permutation {p_eq(drop.get('p_perm'))}). Counting every admissible shift once gives a "
        "slightly different H1 permutation p and the same verdict. The exploratory H2 "
        "observation sits at the conventional line within simulation error and stays not a "
        "finding.",
    ]


GLOSSARY: tuple[tuple[str, str, str], ...] = (
    (
        "Partisan beta",
        "How much a stock or basket moves, on average, when the odds of a Democratic Congress "
        "change, after the market's own move is taken out.",
        "regression slope b on the daily change in P(Democratic Senate), per +10 points",
    ),
    (
        "90% range",
        "The band the true value plausibly sits in. If it includes zero, no effect was detected.",
        "90% confidence interval, HAC standard errors",
    ),
    (
        "Detectable effect",
        "The smallest effect the test would have caught four times out of five.",
        "minimum detectable effect at 80% power",
    ),
    (
        "Non-AI basket",
        "Large companies with no AI story, run through the same tests as a control.",
        "placebo basket",
    ),
    (
        "Could it be luck?",
        "How often a result this strong shows up when there is no real link.",
        "permutation p-value; Holm or Benjamini-Hochberg adjusted across tests",
    ),
    (
        "Return after market and bonds",
        "A stock's move minus what its usual link to the market and to long bonds explains.",
        "abnormal return; residual of the factor regression",
    ),
    (
        "Rank correlation",
        "Whether the stocks ordered one way are also ordered that way on another measure, from "
        "−1 (reversed) through 0 (unrelated) to +1 (same order).",
        "Spearman rho",
    ),
    (
        "Walk-forward",
        "Estimating on the past only, then scoring on a day the estimate never saw.",
        "out-of-sample test, expanding window",
    ),
    (
        "Exploratory",
        "Something looked at without a rule fixed in advance. A lead for next time, not a result.",
        "not pre-registered as a confirmatory test; uncorrected",
    ),
)


def data_line(res: Results) -> str:
    """Sample facts shown under the headline."""
    ai = get(res, "h1", "ai") or {}
    return (
        f"{count(get(ai, 'n'))} pre-election sessions, {day(get(ai, 'first'))} to "
        f"{day(get(ai, 'last'))} · {count(n_names(res))} AI names and "
        f"{count(n_names(res, 'placebo'))} non-AI names · data to "
        f"{day(get(res, 'meta', 'data_last_session'))}"
    )


def missing_bundle_message(command: str) -> str:
    return f"No results to show yet. Build them with: `{command}`"

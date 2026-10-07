"""Reader-facing sentences, as pure functions of the results. No Streamlit, no I/O.

Static wording lives in `wording.py`. Nothing here invents a number: parameters shown to the
reader (lags, bands, interval levels) are read from the results file, and with no results
every function says "not run yet".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .chart_text import (  # re-exported: the app and tests read them via `text`
    XcorrShape,
    classify_xcorr,
    event_study_expert,
    event_study_how_to_read,
    event_study_so_what,
    event_study_title,
    fmt_time,
    label_panel,
    pair_info,
    preview_title,
    stocks_first_note,
    ticker_label,
    xcorr_expert,
    xcorr_how_to_read,
    xcorr_so_what,
    xcorr_title,
)
from .contract import (
    CONFIDENCE_LEVELS,
    CheckRow,
    Confidence,
    EventStudy,
    PairResults,
    Params,
    XCorr,
)
from .wording import (
    CHECKLIST_ROWS,
    CONTROL_TICKERS,
    COUNTS,
    DOES_NOT_COUNT,
    FOOTER,
    GLOSSARY,
    NOT_COMPUTED_NOTE,
    NOT_IN_PLAN,
    NOT_IN_PLAN_NOTE,
    NOT_RUN,
    NOT_RUN_BANNER,
    NOT_RUN_HEADLINE,
    NOT_RUN_REASON,
    NOTHING_TO_CONCLUDE,
    NULL_RESULT,
    SIGNAL_LABELS,
    STATUS_ICON,
    TICKER_PLAIN,
    VERDICT_SENTENCE,
    VERDICT_SO_WHAT,
)

__all__ = [
    "XcorrShape",
    "classify_xcorr",
    "event_study_expert",
    "event_study_how_to_read",
    "event_study_so_what",
    "event_study_title",
    "fmt_time",
    "label_panel",
    "pair_info",
    "stocks_first_note",
    "ticker_label",
    "xcorr_expert",
    "xcorr_how_to_read",
    "xcorr_so_what",
    "xcorr_title",
    "COUNTS",
    "DOES_NOT_COUNT",
    "FOOTER",
    "NOT_IN_PLAN",
    "NOT_IN_PLAN_NOTE",
    "NOT_RUN",
    "NOT_RUN_BANNER",
    "NOT_RUN_HEADLINE",
    "NULL_RESULT",
    "SIGNAL_LABELS",
]

CONFIDENCE_FILLED = dict(zip(CONFIDENCE_LEVELS, (0, 1, 2, 3), strict=True))

Results = dict[str, PairResults | None]


def ticker_plain(ticker: str) -> str:
    return TICKER_PLAIN.get(ticker, "")


def ticker_chip(ticker: str) -> str:
    """'TLT long-term bonds' / 'XLU utilities (control)' for the chips row."""
    parts = [ticker, ticker_plain(ticker), "(control)" if ticker in CONTROL_TICKERS else ""]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------- glossary


def params_of(results: Results) -> Params:
    """Analysis parameters as written by the analysis (first pair that has them)."""
    for r in results.values():
        if r is not None and r.params:
            return r.params
    return {}


def glossary(params: Params) -> tuple[tuple[str, str, str], ...]:
    """(term, plain words, technical term). Numbers come from the results, never from here."""
    lags = params.get("xcorr_lags")
    band = params.get("band_level")
    ci = params.get("ci_level")
    q = params.get("bh_q")
    draws = params.get("event_band_draws")
    plain: dict[str, str] = {}
    tech: dict[str, str] = {}
    if lags:
        plain["Who moves first"] = (
            f"Comparing the two series at time gaps from {abs(lags[0])} hours one way to "
            f"{lags[1]} hours the other."
        )
        tech["Who moves first"] = (
            f"lead-lag cross-correlation, lags {lags[0]} to +{lags[1]} session bars"
        )
    if band:
        tech["Noise zone"] = f"simultaneous {band:.0%} band from session-shifted data"
    if ci:
        tech["Shaded range"] = f"{ci:.0%} confidence interval (BCa bootstrap)"
    if draws:
        tech["Ordinary-day band"] = f"random-date band, {draws} draws"
    if q:
        tech["Many-pairs correction"] = f"Benjamini-Hochberg false discovery rate, q = {q}"
    return tuple((term, plain.get(term, p), tech.get(term, t)) for term, p, t in GLOSSARY)


# ---------------------------------------------------------------- banner, headline, tally


def banner(results: Results) -> str | None:
    """Shown while any pair has no results; ``None`` once every pair has some."""
    missing = [p for p, r in results.items() if r is None]
    if not missing:
        return None
    if len(missing) == len(results):
        return NOT_RUN_BANNER
    return (
        f"Analysis not run for {len(missing)} of {len(results)} pairs: "
        "those cards say so, and the others show real results"
    )


_SHORT = {
    "Polymarket moves first": "leads",
    "Moves at the same time": "no head start",
    "No head start": "no head start",
    "No extra information": "no head start",
    "Too early to tell": "needs data",
    "Descriptive only": "descriptive",
}


def _short_verdict(r: PairResults | None) -> str:
    if r is None or r.verdict is None:
        return "needs data"
    return _SHORT[r.verdict]


def tally(results: Results) -> str:
    """'1 leads, 2 no head start, 1 needs data'; with no results, says so."""
    if all(r is None for r in results.values()):
        return f"{len(results)} pairs waiting for the tests to run"
    counts: dict[str, int] = {}
    for r in results.values():
        key = _short_verdict(r)
        counts[key] = counts.get(key, 0) + 1
    order = ("leads", "no head start", "needs data", "descriptive")
    return ", ".join(f"{counts[k]} {k}" for k in order if k in counts)


def headline(results: Results) -> str:
    """One sentence generated from the per-pair verdicts; never claims more than they do."""
    verdicts = [r.verdict for r in results.values() if r is not None and r.verdict]
    if not verdicts:
        return NOT_RUN_HEADLINE
    n = len(results)
    leads = verdicts.count("Polymarket moves first")
    if leads:
        return f"Polymarket odds moved ahead of stocks in {leads} of {n} pairs we tested"
    undecided = n - sum(_SHORT[v] == "no head start" for v in verdicts)
    if undecided == n:
        return "Too early to tell for every pair so far"
    if undecided:
        return (
            "So far no pair shows Polymarket odds moving ahead of stocks; "
            f"{undecided} of {n} are still undecided or descriptive only"
        )
    return "So far, Polymarket odds have not moved ahead of stocks in any pair we tested"


# ---------------------------------------------------------------- verdict panel, checklist


def check_line(row: CheckRow) -> str:
    """'✓ Passed: Odds help predict prices beyond their own past'."""
    return f"{STATUS_ICON[row.status]} {row.status}: {row.plain}"


def checklist_lines(results: PairResults | None) -> list[tuple[str, str]]:
    """(plain line, technical text) per row; five 'Not run' rows when nothing is available."""
    if results is None or results.checklist is None:
        return [(f"{STATUS_ICON['Not run']} Not run: {name}", "") for name in CHECKLIST_ROWS]
    return [(check_line(row), row.technical) for row in results.checklist]


@dataclass(frozen=True)
class ConfidenceView:
    word: str
    filled: int  # 0-3 meter bars
    reason: str


def confidence_view(conf: Confidence | None) -> ConfidenceView:
    if conf is None:
        return ConfidenceView("Not available", 0, NOT_RUN_REASON)
    return ConfidenceView(conf.level, CONFIDENCE_FILLED[conf.level], conf.reason)


def badge_label(results: PairResults | None) -> str:
    return results.verdict if results and results.verdict else NOT_RUN


def tab_label(pair_id: str, results: PairResults | None) -> str:
    return f"{pair_info(pair_id).short} · {_short_verdict(results)}"


def is_preview(results: PairResults | None) -> bool:
    """Too little data: charts are titled as previews, not results."""
    return bool(results and results.confidence and results.confidence.level == "Not enough data")


def xcorr_for(results: PairResults | None, ticker: str) -> XCorr | None:
    return results.xcorr.get(ticker) if results and results.xcorr else None


def event_study_for(results: PairResults | None, ticker: str) -> EventStudy | None:
    return results.event_study.get(ticker) if results and results.event_study else None


def verdict_sentence(pair_id: str, results: PairResults) -> str:
    """The pre-registered verdict in words, about the pair's primary stock only."""
    info = pair_info(pair_id)
    ticker = results.primary_ticker
    stock = ticker_label(ticker) if ticker else "related stocks"
    return VERDICT_SENTENCE[results.verdict].format(
        odds=info.odds, odds_mid=info.odds_mid, stock=stock
    )


def finding(pair_id: str, results: PairResults | None) -> str:
    """Headline of the scorecard and the verdict panel: the pre-registered verdict for the
    primary stock, never an exploratory chart (validator r1 M1)."""
    if results is None or results.verdict is None:
        return NOT_RUN
    return preview_title(verdict_sentence(pair_id, results), is_preview(results))


def so_what(results: PairResults | None) -> str:
    """Verdict-panel "so what", read from the verdict only."""
    if results is None or results.verdict is None:
        return NOTHING_TO_CONCLUDE
    return VERDICT_SO_WHAT[results.verdict]


def event_study_note(results: PairResults | None, ticker: str) -> str | None:
    """Why chart 2 is missing for a ticker (e.g. too few signed events), if the results say."""
    if results is None or not results.event_study_notes:
        return None
    return results.event_study_notes.get(ticker)


def chart1_state(results: PairResults | None, ticker: str) -> str:
    """'chart' | 'not_in_plan' | 'not_computed' | 'not_run'."""
    if results is None:
        return "not_run"
    if results.xcorr_not_in_plan:
        return "not_in_plan"
    if xcorr_for(results, ticker) is not None:
        return "chart"
    return "not_computed" if results.verdict else "not_run"


def chart2_state(results: PairResults | None, ticker: str) -> str:
    if event_study_for(results, ticker) is not None:
        return "chart"
    return "not_computed" if results is not None and results.verdict else "not_run"


def not_run_chart_note() -> str:
    return "This chart appears once the tests have run. No numbers are shown until then."


def not_computed_note() -> str:
    return NOT_COMPUTED_NOTE


def coverage_line(first: datetime, last: datetime, both: int, age_s: float | None) -> str:
    """Real facts about the aligned data, shown under the ticker chips."""
    age = f"; Polymarket quotes are a median {age_s / 60:.0f} min old" if age_s is not None else ""
    return (
        f"Data on hand: {first:%Y-%m-%d} to {last:%Y-%m-%d} (UTC), "
        f"{both:,} hours when both markets trade{age}."
    )

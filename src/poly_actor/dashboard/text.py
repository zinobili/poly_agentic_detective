"""All reader-facing wording, as pure functions of the results. No Streamlit, no I/O.

Rule: a lay reader never sees pair ids, config file names, commands or step numbers.
Nothing here invents a number: with no results every function says "not run yet".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contract import (
    CONFIDENCE_LEVELS,
    CheckRow,
    Confidence,
    EventStudy,
    PairResults,
    XCorr,
)

NOT_RUN = "Not run yet"
NOT_RUN_BANNER = "Analysis not run yet: only the raw data below is real"
NOT_RUN_HEADLINE = "We haven't run the tests yet"
NOT_RUN_REASON = "Tests not run"
NOTHING_TO_CONCLUDE = "Nothing to conclude until the tests have run."


@dataclass(frozen=True)
class PairInfo:
    name: str
    short: str
    question: str
    odds: str  # start of a sentence
    odds_mid: str  # inside a sentence


_PAIR_INFO = {
    "fed_decision": PairInfo(
        "Fed rate decision",
        "Fed",
        "Do bets on the next Fed rate move run ahead of bond and bank prices?",
        "Fed odds",
        "Fed odds",
    ),
    "us_recession": PairInfo(
        "US recession",
        "Recession",
        "Does the crowd's recession chance move before stocks and bonds do?",
        "Recession odds",
        "recession odds",
    ),
    "bitcoin_monthly_ladder": PairInfo(
        "Bitcoin price ladder",
        "Bitcoin",
        "Do bets on where Bitcoin will trade this month tell us anything "
        "Bitcoin's own price doesn't?",
        "Bitcoin price odds",
        "Bitcoin price odds",
    ),
    "us_cpi_inflation": PairInfo(
        "US inflation (CPI)",
        "Inflation",
        "Do bets on the next inflation report move bonds and tech stocks before the release?",
        "Inflation odds",
        "inflation odds",
    ),
}

SIGNAL_LABELS = {
    "fed_decision": "Expected Fed rate change (pts)",
    "us_recession": "Chance of US recession (%)",
    "bitcoin_monthly_ladder": "Crowd-implied Bitcoin price ($k)",
    "us_cpi_inflation": "Implied inflation, year on year (%)",
}

TICKER_PLAIN = {
    "TLT": "long-term bonds",
    "SPY": "S&P 500",
    "XLF": "banks",
    "XLU": "utilities",
    "IWM": "small companies",
    "IWM-SPY": "small vs large companies",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    "IBIT": "Bitcoin ETF",
    "BTC-USD": "Bitcoin itself",
    "QQQ": "Nasdaq 100",
}
CONTROL_TICKERS = frozenset({"XLU"})

CHECKLIST_ROWS = (
    "Odds move first",
    "Odds help predict prices beyond their own past",
    "Link vanishes when timing is scrambled",
    "Holds after the many-pairs correction",
    "Enough cases to be sure",
)
STATUS_ICON = {"Passed": "✓", "Failed": "✗", "Weak": "!", "Not needed": "–", "Not run": "·"}

CONFIDENCE_FILLED = dict(zip(CONFIDENCE_LEVELS, (0, 1, 2, 3), strict=True))

GLOSSARY = (
    (
        "Odds",
        "Polymarket's price for a yes/no outcome, read as a crowd-estimated probability.",
        "analysis uses hourly changes in log-odds",
    ),
    (
        "Who moves first",
        "Comparing the two series at time gaps from 12 hours one way to 12 hours the other.",
        "lead-lag cross-correlation, lags -12 to +12 h",
    ),
    (
        "Link strength",
        "From -1 to 1. Zero means no link. In markets, 0.1 to 0.2 is already notable.",
        "Pearson correlation",
    ),
    ("Noise zone", "The range that pure chance would produce.", "95% band under no relationship"),
    (
        "Big odds jump",
        "An hour in which the odds moved far more than usual.",
        "hourly change beyond 2 standard deviations",
    ),
    (
        "Shaded range",
        "Where the true average plausibly lies. If it includes zero, the effect could be chance.",
        "95% confidence interval",
    ),
    (
        "Helps predict beyond its own past",
        "Do the odds add anything once we know the stock's recent moves?",
        "Granger causality test",
    ),
    (
        "Scrambled-timing test",
        "Rerun with shuffled times. A real signal should vanish.",
        "placebo test",
    ),
    (
        "Many-pairs correction",
        "Raises the bar because we test many pairs at once.",
        "Benjamini-Hochberg FDR adjustment",
    ),
    (
        "Control asset",
        "A stock that should have no link, used to check that the method isn't inventing patterns.",
        "negative control",
    ),
)

COUNTS = (
    "The odds change **before** the stock, again and again, not just once.",
    "Knowing the odds helps predict the stock **even after** we account for the stock's own "
    "recent moves.",
    "The pattern **disappears** when we deliberately scramble the timing. If it doesn't, the "
    "method is fooling us.",
    "It holds up even though we tested **many pairs**. If you test enough things, one of them "
    "will look good by luck.",
)
DOES_NOT_COUNT = (
    "Two lines that look alike on a chart.",
    "One dramatic day.",
    "Both moving in the same hour. That just means both reacted to the same news.",
    "A link that shows up in one hand-picked stock but not in the others.",
)
NULL_RESULT = (
    "If the odds only mirror what stocks are already doing, that is worth knowing. It means "
    "you can ignore them for timing and skip the effort. Proving there's nothing there is half "
    "of what this lab is for."
)
FOOTER = (
    "Hourly data, all times UTC. Research only: this lab places no trades and is not "
    "investment advice."
)

Results = dict[str, PairResults | None]


def pair_info(pair_id: str) -> PairInfo:
    """Wording for a pair; an unknown id falls back to a readable name, never the raw id."""
    known = _PAIR_INFO.get(pair_id)
    if known:
        return known
    name = pair_id.replace("_", " ").capitalize()
    return PairInfo(name, name, f"Does {name.lower()} move before related stocks?", name, name)


def ticker_plain(ticker: str) -> str:
    return TICKER_PLAIN.get(ticker, "")


def ticker_label(ticker: str) -> str:
    """'TLT (long-term bonds)' for sentences."""
    plain = ticker_plain(ticker)
    return f"{ticker} ({plain})" if plain else ticker


def ticker_chip(ticker: str) -> str:
    """'TLT long-term bonds' / 'XLU utilities (control)' for the chips row."""
    parts = [ticker, ticker_plain(ticker), "(control)" if ticker in CONTROL_TICKERS else ""]
    return " ".join(p for p in parts if p)


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


def _short_verdict(r: PairResults | None) -> str:
    if r is None or r.verdict is None:
        return "needs data"
    return {
        "Polymarket moves first": "leads",
        "Moves at the same time": "no head start",
        "No extra information": "no head start",
        "Too early to tell": "needs data",
    }[r.verdict]


def tally(results: Results) -> str:
    """'1 leads, 2 no head start, 1 needs data'; with no results, says so."""
    if all(r is None for r in results.values()):
        return f"{len(results)} pairs waiting for the tests to run"
    counts: dict[str, int] = {}
    for r in results.values():
        key = _short_verdict(r)
        counts[key] = counts.get(key, 0) + 1
    order = ("leads", "no head start", "needs data")
    return ", ".join(f"{counts[k]} {k}" for k in order if k in counts)


def headline(results: Results) -> str:
    """One sentence generated from the per-pair verdicts."""
    if not any(r is not None and r.verdict for r in results.values()):
        return NOT_RUN_HEADLINE
    if all(r is None or r.verdict == "Too early to tell" for r in results.values()):
        return "Too early to tell for every pair so far"
    leads = sum(1 for r in results.values() if r and r.verdict == "Polymarket moves first")
    if leads == 0:
        return "So far, Polymarket odds have not moved ahead of stocks in any pair we tested"
    return f"Polymarket odds moved ahead of stocks in {leads} of {len(results)} pairs we tested"


# ---------------------------------------------------------------- chart 1 (who moves first)


@dataclass(frozen=True)
class XcorrShape:
    kind: str  # lead | lag | same | isolated | none
    peak_lag: int | None


def classify_xcorr(xc: XCorr) -> XcorrShape:
    """A single outside bar is not a link: the peak needs an adjacent same-sign outside bar."""
    outside = [abs(r) > xc.band for r in xc.r]
    if not any(outside):
        return XcorrShape("none", None)
    peak = min(
        (i for i, o in enumerate(outside) if o),
        key=lambda i: (-abs(xc.r[i]), abs(xc.lags[i])),
    )
    neighbours = (j for j in (peak - 1, peak + 1) if 0 <= j < len(xc.r))
    if not any(outside[j] and xc.r[j] * xc.r[peak] > 0 for j in neighbours):
        return XcorrShape("isolated", xc.lags[peak])
    lag = xc.lags[peak]
    return XcorrShape("same" if lag == 0 else "lead" if lag > 0 else "lag", lag)


def _hours(n: int) -> str:
    return f"{abs(n)} hour" if abs(n) == 1 else f"{abs(n)} hours"


def _preview(title: str, preview: bool) -> str:
    return f"Preview: {title}" if preview else title


def xcorr_title(pair_id: str, xc: XCorr | None, preview: bool = False) -> str:
    """Action title for chart 1, computed from the results."""
    if xc is None:
        return NOT_RUN
    info, stock = pair_info(pair_id), ticker_label(xc.ticker)
    shape = classify_xcorr(xc)
    if shape.kind == "lead":
        title = f"{info.odds} tend to move about {_hours(shape.peak_lag)} before {stock}"
    elif shape.kind == "lag":
        title = f"{stock} tends to move about {_hours(shape.peak_lag)} before {info.odds_mid}"
    elif shape.kind == "same":
        title = f"{info.odds} and {stock} move in the same hour, so neither gets a head start"
    elif shape.kind == "isolated":
        title = (
            f"No clear timing link between {info.odds_mid} and {stock}: only isolated bars "
            "poke out, which is likely luck"
        )
    else:
        title = (
            f"No clear timing link between {info.odds_mid} and {stock}: every bar sits in the "
            "noise zone"
        )
    return _preview(title, preview)


def xcorr_so_what(xc: XCorr | None) -> str:
    if xc is None:
        return NOTHING_TO_CONCLUDE
    kind = classify_xcorr(xc).kind
    if kind == "lead":
        return (
            "This is the kind of early signal we're looking for, but it only counts if the "
            "checklist above also holds up."
        )
    if kind == "lag":
        return "The stock moves first, so the odds are following the market, not leading it."
    if kind == "same":
        return (
            "The odds work like a mirror, not a crystal ball. They show what the market is "
            "already pricing in, so they give no early warning."
        )
    note = (
        "That's a valid result, not a failure. It means the odds gave no timing edge over "
        "this stock in this data."
    )
    if xc.ticker in CONTROL_TICKERS:
        note += (
            " This is a control asset, so no link is good news: the method isn't inventing "
            "patterns."
        )
    return note


def xcorr_how_to_read() -> str:
    return (
        "Each bar is how closely the odds and the stock move together at a given time gap. "
        "Bars to the right mean the odds moved first. Grey bars are inside the noise zone and "
        "mean nothing, and a lone blue bar is usually luck. A bar below the line still counts "
        "as a link: it means the two move in opposite directions."
    )


def xcorr_expert(xc: XCorr) -> str:
    return (
        f"Correlation of hourly changes, lags {xc.lags[0]:+d} to {xc.lags[-1]:+d} h "
        f"(positive lag: odds first). Noise zone: +/-{xc.band:.3f}."
    )


# ---------------------------------------------------------------- chart 2 (event study)


def event_study_title(pair_id: str, es: EventStudy | None, preview: bool = False) -> str:
    if es is None:
        return NOT_RUN
    stock = ticker_label(es.ticker)
    moved = any(
        h > 0 and (lo > 0 or hi < 0)
        for h, lo, hi in zip(es.hours, es.ci_low, es.ci_high, strict=True)
    )
    if moved:
        title = f"After a big odds jump, {stock} shows a move that is unlikely to be chance"
    else:
        title = f"After a big odds jump, {stock} shows no move we can tell apart from chance"
    return _preview(title, preview)


def event_study_how_to_read() -> str:
    return (
        "Time zero is an hour when the odds jumped. The line is the stock's average move "
        "before and after. The shaded range is where the true average plausibly lies. If it "
        "includes zero, the move could be chance."
    )


def event_study_so_what(es: EventStudy | None) -> str:
    if es is None:
        return NOTHING_TO_CONCLUDE
    return "Use this to see whether the stock reacts after the odds do, and for how long."


def event_study_expert(es: EventStudy, n_events: int | None) -> str:
    count = n_events if n_events is not None else len(es.event_times)
    span = ""
    if es.event_times:
        span = f" (first {fmt_time(min(es.event_times))}, last {fmt_time(max(es.event_times))})"
    return (
        f"Mean {es.ticker} move in percent, hours {es.hours[0]:+d} to {es.hours[-1]:+d} around "
        f"each event, with a 95% interval. Events: {count}{span}."
    )


# ---------------------------------------------------------------- verdict panel, checklist


def fmt_time(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


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


def finding(pair_id: str, results: PairResults | None, ticker: str) -> str:
    """One-sentence finding for the scorecard and the verdict panel title."""
    xc = xcorr_for(results, ticker)
    return NOT_RUN if xc is None else xcorr_title(pair_id, xc, is_preview(results))


def so_what(results: PairResults | None, ticker: str) -> str:
    return xcorr_so_what(xcorr_for(results, ticker))


def not_run_chart_note() -> str:
    return "This chart appears once the tests have run. No numbers are shown until then."


def coverage_line(first: datetime, last: datetime, both: int, age_s: float | None) -> str:
    """Real facts about the aligned data, shown under the ticker chips."""
    age = f"; Polymarket quotes are a median {age_s / 60:.0f} min old" if age_s is not None else ""
    return (
        f"Data on hand: {first:%Y-%m-%d} to {last:%Y-%m-%d} (UTC), "
        f"{both:,} hours when both markets trade{age}."
    )

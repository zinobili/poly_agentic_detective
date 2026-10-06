"""Chart 1 and chart 2 sentences (titles, how-to-read, so-what, expert notes). Pure.

Split out of `text.py`; `text` re-exports these names for the app and the tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contract import GAP_STEP, EventStudy, PairResults, XCorr
from .wording import (
    CONTROL_TICKERS,
    NOT_RUN,
    NOTHING_TO_CONCLUDE,
    PAIR_INFO,
    TICKER_PLAIN,
    PairInfo,
)


def pair_info(pair_id: str) -> PairInfo:
    """Wording for a pair; an unknown id falls back to a readable name, never the raw id."""
    known = PAIR_INFO.get(pair_id)
    if known:
        return known
    name = pair_id.replace("_", " ").capitalize()
    return PairInfo(
        name, name, f"Does {name.lower()} move before related stocks?", name, name, "each event"
    )


def ticker_label(ticker: str) -> str:
    """'TLT (long-term bonds)' for sentences."""
    plain = TICKER_PLAIN.get(ticker, "")
    return f"{ticker} ({plain})" if plain else ticker


def fmt_time(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- chart 1 (who moves first)


@dataclass(frozen=True)
class XcorrShape:
    kind: str  # lead | lag | same | none
    peak_lag: int | None


def classify_xcorr(xc: XCorr) -> XcorrShape:
    """A27 rule 12: a clear link is a peak outside the simultaneous band (the band already
    covers every lag at once, so no neighbouring bar is required)."""
    outside = [abs(r) > xc.band for r in xc.r]
    if not any(outside):
        return XcorrShape("none", None)
    peak = min(range(len(xc.r)), key=lambda i: (-abs(xc.r[i]), abs(xc.lags[i])))
    lag = xc.lags[peak]
    return XcorrShape("same" if lag == 0 else "lead" if lag > 0 else "lag", lag)


def _hours(n: int) -> str:
    return f"{abs(n)} hour" if abs(n) == 1 else f"{abs(n)} hours"


def preview_title(title: str, preview: bool) -> str:
    return f"Preview: {title}" if preview else title


def label_panel(xc: XCorr) -> XCorr:
    """The panel the label is read from: the spot-adjusted one when there is one (BTC)."""
    return xc.residualised or xc


def xcorr_title(pair_id: str, xc: XCorr | None, preview: bool = False) -> str:
    """Action title for chart 1, computed from the results."""
    if xc is None:
        return NOT_RUN
    info, stock = pair_info(pair_id), ticker_label(xc.ticker)
    shape = classify_xcorr(label_panel(xc))
    if shape.kind == "lead":
        title = f"{info.odds} tend to move about {_hours(shape.peak_lag)} before {stock}"
    elif shape.kind == "lag":
        title = f"{stock} tends to move about {_hours(shape.peak_lag)} before {info.odds_mid}"
    elif shape.kind == "same":
        title = f"{info.odds} and {stock} move in the same hour, so neither gets a head start"
    else:
        title = (
            f"No clear timing link between {info.odds_mid} and {stock}: every bar sits in the "
            "noise zone"
        )
    return preview_title(title, preview)


def xcorr_so_what(xc: XCorr | None) -> str:
    if xc is None:
        return NOTHING_TO_CONCLUDE
    kind = classify_xcorr(label_panel(xc)).kind
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


def xcorr_how_to_read(adjusted: bool = False) -> str:
    text = (
        "Each bar is how closely the odds and the stock move together at a given time gap. "
        "Bars to the right mean the odds moved first. Grey bars are inside the noise zone and "
        "mean nothing; the zone already allows for looking at many gaps at once. A bar below "
        "the line still counts as a link: it means the two move in opposite directions."
    )
    if adjusted:
        text += (
            " The first chart takes out what Bitcoin's own price explains; the second shows the "
            "raw link."
        )
    return text


def xcorr_expert(xc: XCorr) -> str:
    out = (
        f"Correlation of hourly changes, lags {xc.lags[0]:+d} to {xc.lags[-1]:+d} session bars "
        f"(positive lag: odds first). Simultaneous noise zone: +/-{xc.band:.3f}."
    )
    if xc.residualised:
        out += (
            f" Spot-adjusted panel (returns net of BTC-USD lags 0-3): noise zone "
            f"+/-{xc.residualised.band:.3f}; the title is read from it."
        )
    return out


def stocks_first_note(results: PairResults | None) -> str | None:
    if results is None or not results.stocks_first:
        return None
    return (
        "Exploratory: the strongest bar is on the stock-first side. The odds are about 10 "
        "minutes old, which can push a shared reaction one hour that way."
    )


# ---------------------------------------------------------------- chart 2 (event study)


def _after_zero(es: EventStudy) -> list[int]:
    start = es.steps.index("0") if "0" in es.steps else 0
    return list(range(start, len(es.steps)))


def event_study_title(pair_id: str, es: EventStudy | None, preview: bool = False) -> str:
    if es is None:
        return NOT_RUN
    info, stock = pair_info(pair_id), ticker_label(es.ticker)
    moved = any(es.ci_low[i] > 0 or es.ci_high[i] < 0 for i in _after_zero(es))
    lead = f"On {info.events}" if es.unit == "days" else f"Around {info.events}"
    if moved:
        title = f"{lead}, {stock} shows a move that is unlikely to be chance"
    else:
        title = f"{lead}, {stock} shows no move we can tell apart from chance"
    return preview_title(title, preview)


def event_study_how_to_read(es: EventStudy | None = None) -> str:
    if es is not None and es.unit == "days":
        return (
            "Day 0 is the day of a big move in the odds (close to close); day +1 is the next "
            "day. One line shows the days with the biggest rises, the other the biggest falls. "
            "The shaded range is where the true average plausibly lies."
        )
    text = (
        "Time zero is the first hour after the event. The line is the stock's average move "
        "added up from the start of the window, in percent. Each event is flipped so that 'up' "
        "means the stock moved the same way as the odds just before it. The shaded range is "
        "where the true average plausibly lies. If it includes zero, the move could be chance."
    )
    if es is not None and (GAP_STEP in es.steps or any(es.gap_marks)):
        text += " A marked step is the overnight jump at the next morning's open."
    if es is not None and es.band_low is not None:
        text += " The grey band shows what ordinary days look like."
    return text


def event_study_so_what(es: EventStudy | None) -> str:
    if es is None:
        return NOTHING_TO_CONCLUDE
    return "Use this to see whether the stock reacts after the odds do, and for how long."


def event_study_expert(es: EventStudy, n_events: int | None, ci_level: float | None) -> str:
    count = len(es.paths) if es.paths else (n_events if n_events is not None else 0)
    span = ""
    if es.event_times:
        span = f" (first {fmt_time(min(es.event_times))}, last {fmt_time(max(es.event_times))})"
    level = f"{ci_level:.0%}" if ci_level else "a"
    unsigned = f" Too small to sign and left out: {es.n_unsigned}." if es.n_unsigned else ""
    unit = "day" if es.unit == "days" else "session bar"
    return (
        f"Mean {es.ticker} move in percent per {unit}, steps {es.steps[0]} to {es.steps[-1]}, "
        f"with {level} interval (BCa bootstrap over events). Events: {count}{span}.{unsigned}"
    )

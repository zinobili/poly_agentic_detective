"""Static reader-facing wording (no logic). `text.py` turns results into sentences.

Rule: a lay reader never sees pair ids, config file names, commands or step numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PairInfo:
    name: str
    short: str
    question: str
    odds: str  # start of a sentence
    odds_mid: str  # inside a sentence
    events: str  # what chart 2 is centred on


PAIR_INFO = {
    "fed_decision": PairInfo(
        "Fed rate decision",
        "Fed",
        "Do bets on the next Fed rate move run ahead of bond and bank prices?",
        "Fed odds",
        "Fed odds",
        "each Fed decision",
    ),
    "us_recession": PairInfo(
        "US recession",
        "Recession",
        "Does the crowd's recession chance move before stocks and bonds do?",
        "Recession odds",
        "recession odds",
        "the days with the biggest moves in recession odds",
    ),
    "bitcoin_monthly_ladder": PairInfo(
        "Bitcoin price ladder",
        "Bitcoin",
        "Do bets on where Bitcoin will trade this month tell us anything "
        "Bitcoin's own price doesn't?",
        "Bitcoin price odds",
        "Bitcoin price odds",
        "the 20 biggest moves in the odds",
    ),
    "us_cpi_inflation": PairInfo(
        "US inflation (CPI)",
        "Inflation",
        "Do bets on the next inflation report move bonds and tech stocks before the release?",
        "Inflation odds",
        "inflation odds",
        "each inflation release day",
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
ROUND_THE_CLOCK = frozenset({"BTC-USD"})  # trades 24/7: no overnight breaks in chart 3

CHECKLIST_ROWS = (
    "Odds move first",
    "Odds help predict prices beyond their own past",
    "Link vanishes when timing is scrambled",
    "Holds after the many-pairs correction",
    "Enough data for the test",
)
STATUS_ICON = {
    "Passed": "✓",
    "Failed": "✗",
    "Failed (opposite sign)": "✗",
    "Weak": "!",
    "Not needed": "–",
    "Not run": "·",
    "Not valid": "⚠",
}

VERDICT_SENTENCE = {
    "Polymarket moves first": "{odds} tend to move before {stock}",
    "Moves at the same time": "{odds} and {stock} move together, so neither gets a head start",
    "No head start": "{odds} give no head start on {stock}",
    "No extra information": "{odds} only echo Bitcoin's own price, so they add nothing",
    "Too early to tell": "Too early to tell whether {odds_mid} move before {stock}",
    "Descriptive only": "A description of how {stock} moved on the biggest days for {odds_mid}",
}

# "So what" of the verdict panel, by verdict. It reads the pre-registered verdict only; the
# exploratory charts never feed the headline (validator r1 M1).
VERDICT_SO_WHAT = {
    "Polymarket moves first": "This is the kind of early signal we're looking for. Check how "
    "sure we are below before relying on it.",
    "Moves at the same time": "The odds and the stock react together, so the odds give no "
    "early warning.",
    "No head start": "In this data the odds gave no early warning. A lead big enough to be "
    "useful would most likely have shown up.",
    "No extra information": "The odds add nothing to what Bitcoin's own price already tells you.",
    "Too early to tell": "There is no reliable answer yet, so don't use the odds for timing on "
    "the strength of this.",
    "Descriptive only": "This shows what happened on the biggest days. It is a description, "
    "not a test.",
}

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

NOT_RUN = "Not run yet"
NOT_RUN_BANNER = "Analysis not run yet: only the raw data below is real"
NOT_RUN_HEADLINE = "We haven't run the tests yet"
NOT_RUN_REASON = "Tests not run"
NOTHING_TO_CONCLUDE = "Nothing to conclude until the tests have run."
NOT_IN_PLAN = "Not part of the plan"
NOT_IN_PLAN_NOTE = (
    "We decided in advance not to run an hour-by-hour timing test for this pair: there are too "
    "few independent episodes. The verdict above comes from the release-day or big-day study "
    "in chart 2."
)
NOT_COMPUTED_NOTE = "This chart was not computed for this stock."

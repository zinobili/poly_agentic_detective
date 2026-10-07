"""Verdict, confidence and checklist, computed from test outcomes (A27 rules 5-10, as
amended by A28 items 2 and 3).

Nothing here is hand-written per pair: every label follows from `Facts`. Rule order is the
A27 order and the first matching row wins.
"""

from __future__ import annotations

from dataclasses import dataclass

BH_Q = 0.10  # A27 rule 6
OPPOSITE_P = 0.05  # two-sided p for "Failed (opposite sign)"
LEAD_ALPHA = 0.05  # Fed b1+b2 gatekeeping test
NO_EXTRA_P = 0.05  # BTC no-control lag-1 one-sided p
CPI_CLOSE_P = 0.10  # CPI proxy ending at the prior close
WEAK_P = 0.10  # display only: a non-significant primary with one-sided p < 0.10 is "Weak"

# A27 rule 9 (correlation units, 80% power, one-sided 5%).
MDE = {"fed": 0.051, "btc": 0.068, "cpi": 0.72}
# Margin a non-significant primary's one-sided 95% upper bound (H1 direction) must clear for
# "No head start". Fed/BTC: the MDE (A27 rule 5). CPI: 0.5, prereg A28 item 3 (the B3 wording,
# "underpowered unless the 90% CI excludes rho <= -0.5"; the stricter of the two). For CPI the
# H1-direction effect is -rho, so the bound is minus the lower end of the 90% Fisher interval.
NULL_MARGIN = {"fed": 0.051, "btc": 0.068, "cpi": 0.5}

DESCRIPTIVE = "Descriptive only"
TOO_EARLY = "Too early to tell"
NO_HEAD_START = "No head start"
NO_EXTRA = "No extra information"
FIRST = "Polymarket moves first"
SAME = "Moves at the same time"

# Prereg A28 item 2 (amends A27 rule 7.3). Fed (session shift) and CPI (random dates) placebos
# are RELATIVE: they pass only when the real statistic stands out from the placebo
# distribution, so a null primary "fails" them by construction. They gate the verdict only for
# a BH-significant primary; for a non-significant one they are reported, not used. The literal
# A27 reading is also computed and written (`verdict(literal_placebo=True)`, results key
# `verdict_if_placebo_read_literally`). BTC's XLU control is an absolute negative control and
# always gates.
RELATIVE_PLACEBO = frozenset({"fed", "cpi"})


@dataclass(frozen=True)
class Facts:
    """Everything the verdict rules read. Correlation-unit bounds are in the H1 direction."""

    pair: str  # fed | btc | cpi | recession
    sufficient: bool = False
    sufficiency_note: str = ""
    validation_ok: bool | None = None  # CPI only
    placebo_pass: bool | None = None
    placebo_note: str = ""
    p_one: float | None = None  # primary, one-sided in the H1 direction
    p_two: float | None = None
    estimate_h1_sign: bool = True  # estimate on the H1 side of zero
    bh_reject: bool = False
    bh_q: float | None = None
    upper_r: float | None = None  # one-sided 95% upper bound, H1 direction
    lower_r: float | None = None  # one-sided 95% lower bound, H1 direction
    lead_p: float | None = None  # Fed b1+b2
    nocontrol_p: float | None = None  # BTC
    close_proxy_ok: bool | None = None  # CPI
    robust_hold: bool | None = None

    @property
    def opposite_sign(self) -> bool:
        return bool(
            self.p_two is not None and self.p_two < OPPOSITE_P and not self.estimate_h1_sign
        )


def placebo_gates(f: Facts, literal: bool = False) -> bool:
    """True when a failed placebo decides the verdict (A27 rule 7.3 as amended by A28 item 2)."""
    if f.placebo_pass is not False:
        return False
    return literal or f.pair not in RELATIVE_PLACEBO or f.bh_reject


def verdict(f: Facts, literal_placebo: bool = False) -> tuple[str, str]:
    """(verdict, reason). A27 rule 7 (A28 items 2-3), first matching row wins."""
    if f.pair == "recession":
        return DESCRIPTIVE, "One episode, so no significance test is made (pre-registered)."
    if not f.sufficient:
        return TOO_EARLY, f"Not enough data: {f.sufficiency_note}"
    if f.validation_ok is False:
        return TOO_EARLY, "The method check on resolved months failed."
    if placebo_gates(f, literal_placebo):
        return TOO_EARLY, f"Placebo failed: {f.placebo_note}"
    if f.pair == "btc" and not f.bh_reject and (f.nocontrol_p or 1.0) < NO_EXTRA_P:
        return NO_EXTRA, "The odds track Bitcoin's own price; after it, they add nothing."
    if not f.bh_reject:
        if f.upper_r is not None and f.upper_r < NULL_MARGIN[f.pair]:
            return NO_HEAD_START, "The data rule out a lead of the size we could detect."
        return TOO_EARLY, "Underpowered: the data cannot rule out a useful lead yet."
    if f.pair == "fed":
        if f.lead_p is not None and f.lead_p < LEAD_ALPHA:
            return FIRST, "The lagged odds changes (1-2 bars earlier) carry the link."
        return SAME, "The link is there, but the lagged part alone is not significant."
    if f.pair == "btc":
        return FIRST, "The odds an hour earlier help beyond Bitcoin's own price."
    if f.close_proxy_ok:
        return FIRST, "The odds move had already happened by the previous close."
    return SAME, "The odds move may come from the same overnight news as the bond move."


def confidence(f: Facts) -> tuple[str, str]:
    """(level, reason). A27 rule 10."""
    if f.pair == "recession":
        return "Low", "One episode and no significance test; read as a description only."
    if not f.sufficient or f.validation_ok is False:
        return "Not enough data", f.sufficiency_note or "The method check failed."
    if placebo_gates(f):
        return "Low", "The placebo check did not pass."
    if not f.bh_reject:
        return "Low", "The main test is not significant after the many-pairs correction."
    if not f.robust_hold:
        return "Low", "Significant, but it does not survive every robustness check."
    high = (
        f.pair != "cpi"
        and f.bh_q is not None
        and f.bh_q < 0.01
        and f.lower_r is not None
        and f.lower_r > MDE[f.pair] / 2
    )
    if high:
        return "High", "Significant, placebo passes, robust, and the effect is clearly large."
    return "Medium", "Significant, placebo passes and robustness checks hold."


def primary_status(f: Facts) -> str:
    if f.opposite_sign:
        return "Failed (opposite sign)"
    if f.bh_reject:
        return "Passed"
    if f.p_one is not None and f.p_one < WEAK_P:
        return "Weak"
    return "Failed"

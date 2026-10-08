"""Wording rules as input -> expected-output examples (docs/handoff/step5.md, batch 5b)."""

from dashboard_helpers import granger_row, results, xcorr
from poly_actor.dashboard import text
from poly_actor.dashboard.contract import CheckRow, Confidence, EventStudy, XCorr, parse_results
from poly_actor.dashboard.wording import PAIR_INFO

PARAMS = {
    "xcorr_lags": [-6, 6],
    "band_level": 0.95,
    "ci_level": 0.9,
    "bh_q": 0.1,
    "event_band_draws": 1000,
}

NONE_RUN = {p: None for p in ("fed_decision", "us_recession", "bitcoin_monthly_ladder")}


def test_no_results_banner_headline_and_confidence():
    assert text.banner(NONE_RUN) == "Analysis not run yet: only the raw data below is real"
    assert text.headline(NONE_RUN) == "We haven't run the tests yet"
    assert text.badge_label(None) == "Not run yet"
    view = text.confidence_view(None)
    assert (view.filled, view.reason) == (0, "Tests not run")
    assert text.tally(NONE_RUN) == "3 pairs waiting for the tests to run"


def test_banner_goes_away_when_every_pair_has_results():
    assert text.banner({"fed_decision": results()}) is None


def test_lead_title_for_fed_and_tlt():
    xc = xcorr("TLT", p2=0.2, p3=0.15)
    assert (
        text.xcorr_title("fed_decision", xc)
        == "Fed odds tend to move about 2 hours before TLT (long-term bonds) (exploratory)"
    )


def test_one_hour_is_singular():
    title = text.xcorr_title("fed_decision", xcorr("TLT", p1=0.2, p2=0.15))
    assert "about 1 hour before" in title


def test_negative_lag_says_stock_moves_first():
    title = text.xcorr_title("fed_decision", xcorr("TLT", m2=0.2, m1=0.15))
    assert (
        title == "TLT (long-term bonds) tends to move about 2 hours before Fed odds (exploratory)"
    )


def test_peak_at_zero_is_an_exploratory_same_hour_reading_without_a_mirror_claim():
    """Validator r1 M1: chart 1 is exploratory; no "neither gets a head start", no "mirror"."""
    xc = xcorr("SPY", band=0.1, p0=0.25, p1=0.15)
    title = text.xcorr_title("us_recession", xc)
    assert title == (
        "The strongest link between recession odds and SPY (S&P 500) is in the same hour "
        "(exploratory)"
    )
    so_what = text.xcorr_so_what(xc)
    assert "mirror" not in so_what and "not the test" in so_what


def test_lone_bar_outside_the_simultaneous_band_is_a_link():
    """A27 rule 12: the band covers all lags at once, so no neighbour is required."""
    xc = xcorr("TLT", p2=0.2)
    assert text.xcorr_title("fed_decision", xc).startswith("Fed odds tend to move about 2 hours")


def test_opposite_sign_neighbour_does_not_cancel_the_peak():
    xc = xcorr("TLT", p2=0.2, p3=-0.15)
    assert text.classify_xcorr(xc).peak_lag == 2


def test_all_inside_band_is_a_valid_result():
    xc = xcorr("TLT", p2=0.09, m3=-0.05)
    assert text.xcorr_title("fed_decision", xc) == (
        "No clear timing link between Fed odds and TLT (long-term bonds): every bar sits in the "
        "noise zone"
    )
    assert "That's a valid result, not a failure." in text.xcorr_so_what(xc)


def test_robust_t_decides_the_link_when_the_results_carry_it():
    """A28 item 1: with a t band the title reads |t|, not |r|."""
    base = xcorr("TLT", p2=0.5, m1=0.02)  # by r alone: a 2-hour odds lead
    t = tuple(4.0 if lag == -1 else 1.0 for lag in base.lags)
    xc = XCorr(base.ticker, base.lags, base.r, 3.0, t=t)
    assert text.classify_xcorr(xc).kind == "lag" and text.classify_xcorr(xc).peak_lag == -1
    assert "|robust t| <= 3.00" in text.xcorr_expert(xc)


def test_bar_exactly_on_the_band_is_inside():
    assert text.classify_xcorr(xcorr("TLT", band=0.1, p2=0.1)).kind == "none"


def test_preview_prefix_when_not_enough_data():
    xc = xcorr("TLT", p2=0.2, p3=0.15)
    assert text.xcorr_title("fed_decision", xc, preview=True).startswith("Preview: Fed odds")
    res = results(
        xcorr={"TLT": xc},
        confidence=Confidence("Not enough data", "Only 2 releases."),
        verdict="Too early to tell",
        primary_ticker="TLT",
    )
    assert text.finding("fed_decision", res).startswith("Preview: Too early to tell")


def test_checklist_line_plain_first_technical_separate():
    row = granger_row("Passed")
    assert text.check_line(row) == "✓ Passed: Odds help predict prices beyond their own past"
    lines = text.checklist_lines(results(checklist=(row,)))
    assert lines == [
        (
            "✓ Passed: Odds help predict prices beyond their own past",
            "Granger causality, BH-adjusted p = 0.012",
        )
    ]


def test_checklist_without_results_is_five_not_run_rows():
    lines = text.checklist_lines(None)
    assert len(lines) == 5 and all(line.startswith("· Not run: ") for line, _ in lines)


def test_pair_id_never_shown_even_for_unknown_pairs():
    info = text.pair_info("some_new_pair")
    assert "_" not in info.name and "_" not in info.question
    assert text.pair_info("fed_decision").name == "Fed rate decision"


def test_ticker_wording():
    assert text.ticker_chip("XLU") == "XLU utilities (control)"
    assert text.ticker_chip("TLT") == "TLT long-term bonds"
    assert text.ticker_label("XLF") == "XLF (banks)"
    assert text.ticker_label("ZZZ") == "ZZZ"


def test_tally_and_headline_from_verdicts():
    res = {
        "a": results(verdict="Polymarket moves first"),
        "b": results(verdict="Moves at the same time"),
        "c": results(verdict="No extra information"),
        "d": None,
    }
    assert text.tally(res) == "1 leads, 2 no head start, 1 not run"
    assert text.headline(res) == "Polymarket odds moved ahead of stocks in 1 of 4 pairs we tested"
    assert "Analysis not run for 1 of 4 pairs" in text.banner(res)


def test_headline_when_nothing_leads():
    res = {"a": results(verdict="Moves at the same time")}
    assert text.headline(res).startswith("So far, Polymarket odds have not moved ahead")


def test_confidence_meter_levels():
    for level, filled in (("Not enough data", 0), ("Low", 1), ("Medium", 2), ("High", 3)):
        assert text.confidence_view(Confidence(level, "why")).filled == filled


def test_no_internal_names_in_reader_strings():
    blob = " ".join(
        [text.NOT_RUN_BANNER, text.NOT_RUN_HEADLINE, text.NULL_RESULT, text.FOOTER]
        + [t for g in text.glossary(PARAMS) for t in g]
        + [info.question for info in PAIR_INFO.values()]
    )
    for banned in (*PAIR_INFO, "pairs.yaml", "python -m", "step 6"):
        assert banned not in blob


def test_control_ticker_no_link_is_good_news():
    so_what = text.xcorr_so_what(xcorr("XLU"))
    assert "That's a valid result, not a failure." in so_what and "good news" in so_what
    assert "good news" not in text.xcorr_so_what(xcorr("TLT"))


def test_finding_comes_from_the_verdict_for_the_primary_ticker_not_from_chart1():
    """Validator r1 M1: an exploratory same-hour chart 1 never becomes the headline."""
    same_hour = xcorr("TLT", band=0.1, p0=0.25)
    res = results(
        xcorr={"TLT": same_hour, "SPY": xcorr("SPY", p2=0.3)},
        verdict="No head start",
        primary_ticker="TLT",
    )
    assert text.finding("fed_decision", res) == (
        "Fed odds give no head start on TLT (long-term bonds)"
    )
    assert "mirror" not in text.so_what(res) and "same hour" not in text.so_what(res)
    btc = results(
        "bitcoin_monthly_ladder",
        xcorr={"COIN": xcorr("COIN", p0=0.5)},
        verdict="Too early to tell",
        primary_ticker="IBIT",
    )
    assert text.finding("bitcoin_monthly_ladder", btc) == (
        "Too early to tell whether Bitcoin price odds move before IBIT (Bitcoin ETF)"
    )


def test_no_results_or_no_verdict_finding_is_not_run():
    assert text.finding("fed_decision", None) == "Not run yet"
    res = results(xcorr={"TLT": xcorr("TLT", p2=0.2, p3=0.15)})
    assert text.finding("fed_decision", res) == "Not run yet"
    assert text.so_what(res) == text.NOTHING_TO_CONCLUDE


def test_untested_ticker_never_gets_a_verdict_sentence():
    """BTC-USD (spot) is never a tested target: no sentence names it."""
    res = results("bitcoin_monthly_ladder", verdict="No head start", primary_ticker="IBIT")
    assert "BTC-USD" not in text.finding("bitcoin_monthly_ladder", res)
    no_primary = results("bitcoin_monthly_ladder", verdict="No head start")
    assert text.finding("bitcoin_monthly_ladder", no_primary) == (
        "Bitcoin price odds give no head start on related stocks"
    )


def test_headline_does_not_claim_a_finding_when_every_verdict_is_too_early():
    res = {"a": results(verdict="Too early to tell"), "b": results(verdict="Too early to tell")}
    assert text.headline(res) == "Too early to tell for every pair so far"


# ---------------------------------------------------------------- step 6 contract additions


def test_glossary_reads_its_numbers_from_the_results():
    terms = {t: (plain, tech) for t, plain, tech in text.glossary(PARAMS)}
    assert "from 6 hours one way to 6 hours the other" in terms["Who moves first"][0]
    assert terms["Noise zone"][1] == "simultaneous 95% band from session-shifted data"
    assert terms["Shaded range"][1].startswith("90% confidence interval")
    assert "q = 0.1" in terms["Many-pairs correction"][1]


def test_glossary_without_results_shows_no_numbers():
    blob = " ".join(t for g in text.glossary({}) for t in g)
    for parameter in ("hours one way", "%", "q =", "draws", "lags -"):
        assert parameter not in blob


def test_headline_mix_of_undecided_and_no_extra_information_does_not_overclaim():
    res = {
        "a": results(verdict="Too early to tell"),
        "b": results(verdict="No extra information"),
        "c": results(verdict="Descriptive only"),
    }
    assert text.headline(res) == (
        "So far no pair shows Polymarket odds moving ahead of stocks; 2 of 3 are still "
        "undecided or descriptive only"
    )
    assert text.tally(res) == "1 no head start, 1 undecided, 1 descriptive"


def test_headline_all_decided_nulls():
    res = {"a": results(verdict="No head start"), "b": results(verdict="Moves at the same time")}
    assert text.headline(res).startswith("So far, Polymarket odds have not moved ahead")


def test_btc_title_is_read_from_the_spot_adjusted_panel():
    raw = xcorr("IBIT", p0=0.5)  # raw: same-hour co-movement with Bitcoin itself
    adjusted = xcorr("IBIT")  # nothing left after taking out Bitcoin's own price
    xc = XCorr(raw.ticker, raw.lags, raw.r, raw.band, adjusted)
    assert text.xcorr_title("bitcoin_monthly_ladder", xc).startswith("No clear timing link")


def test_chart1_states():
    assert text.chart1_state(None, "TLT") == "not_run"
    plan = results("us_cpi_inflation", xcorr_not_in_plan=True, verdict="Too early to tell")
    assert text.chart1_state(plan, "TLT") == "not_in_plan"
    fed = results(xcorr={"TLT": xcorr("TLT")}, verdict="No head start")
    assert text.chart1_state(fed, "TLT") == "chart"
    assert text.chart1_state(fed, "SPY") == "not_computed"


def test_finding_without_a_chart1_uses_the_verdict():
    res = results(
        "us_cpi_inflation",
        xcorr_not_in_plan=True,
        verdict="Too early to tell",
        primary_ticker="TLT",
    )
    assert text.finding("us_cpi_inflation", res) == (
        "Too early to tell whether inflation odds move before TLT (long-term bonds)"
    )
    pre = results(
        "us_recession",
        verdict="Descriptive only",
        confidence=Confidence("Not enough data", "x"),
        primary_ticker="IWM-SPY",
    )
    assert text.finding("us_recession", pre).startswith("Preview: A description")


def test_biased_residualised_panel_is_not_read():
    """Prereg A29: a residualised panel with a caveat note gives no timing title."""
    raw = xcorr("IBIT", p0=0.5)
    biased = xcorr("IBIT", p1=-0.5)
    biased = XCorr(biased.ticker, biased.lags, biased.r, biased.band, note="Not read as evidence")
    xc = XCorr(raw.ticker, raw.lags, raw.r, raw.band, biased)
    title = text.xcorr_title("bitcoin_monthly_ladder", xc)
    assert title.startswith("Not read as evidence") and "before" not in title
    assert text.xcorr_so_what(xc) == "Not read as evidence"


def test_event_study_note_explains_a_missing_chart2():
    res = results(verdict="No head start", event_study_notes={"TLT": "Too few events"})
    assert text.event_study_note(res, "TLT") == "Too few events"
    assert text.event_study_note(res, "SPY") is None


def test_opposite_sign_status_line():
    row = CheckRow("Primary test", "Failed (opposite sign)", "Moves in the expected direction", "")
    assert text.check_line(row) == "✗ Failed (opposite sign): Moves in the expected direction"


def test_stocks_first_note_only_when_flagged():
    assert text.stocks_first_note(results(stocks_first=True)).startswith("Exploratory")
    assert text.stocks_first_note(results(stocks_first=False)) is None


# ---------------------------------------------------------------- step 7 carried minors


def _btc_chart2(note: str | None) -> EventStudy:
    # a clear move after bar 0: the title would claim a move if it were read
    return EventStudy("IBIT", ("0", "+1"), (0.5, 0.6), (0.2, 0.3), (0.8, 0.9), (), note=note)


def test_biased_chart2_is_not_read():
    """A29 addendum: a BTC Chart 2 residualised on the misaligned control gives no reading."""
    biased = _btc_chart2("Not read as evidence: biased")
    title = text.event_study_title("bitcoin_monthly_ladder", biased)
    assert title.startswith("Not read as evidence") and "unlikely to be chance" not in title
    assert text.event_study_so_what(biased) == "Not read as evidence: biased"
    clean = _btc_chart2(None)
    assert "unlikely to be chance" in text.event_study_title("bitcoin_monthly_ladder", clean)


def test_event_study_note_is_parsed_from_the_results():
    raw = {
        "pair_id": "bitcoin_monthly_ladder",
        "event_study": {
            "IBIT": {
                "steps": ["0", "+1"],
                "mean": [0.1, 0.2],
                "ci_low": [0.0, 0.1],
                "ci_high": [0.2, 0.3],
                "note": "Not read as evidence",
            }
        },
    }
    assert parse_results(raw).event_study["IBIT"].note == "Not read as evidence"


def test_tab_label_for_an_a29_verdict_is_undecided_not_needs_data():
    btc = results("bitcoin_monthly_ladder", verdict="Too early to tell")
    assert text.tab_label("bitcoin_monthly_ladder", btc) == "Bitcoin · undecided"
    assert text.tab_label("bitcoin_monthly_ladder", None) == "Bitcoin · not run"


def test_no_head_start_so_what_is_hedged():
    """step 6 r2 m3: next to Low confidence, the wording leaves room for a smaller lead."""
    words = text.so_what(results(verdict="No head start"))
    assert "would probably have shown up" in words and "can't be ruled out" in words
    assert "most likely" not in words

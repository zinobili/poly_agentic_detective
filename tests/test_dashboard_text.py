"""Wording rules as input -> expected-output examples (docs/handoff/step5.md, batch 5b)."""

from dashboard_helpers import granger_row, results, xcorr
from poly_actor.dashboard import text
from poly_actor.dashboard.contract import Confidence

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
        == "Fed odds tend to move about 2 hours before TLT (long-term bonds)"
    )


def test_one_hour_is_singular():
    title = text.xcorr_title("fed_decision", xcorr("TLT", p1=0.2, p2=0.15))
    assert "about 1 hour before" in title


def test_negative_lag_says_stock_moves_first():
    title = text.xcorr_title("fed_decision", xcorr("TLT", m2=0.2, m1=0.15))
    assert title == "TLT (long-term bonds) tends to move about 2 hours before Fed odds"


def test_peak_at_zero_means_same_hour():
    xc = xcorr("SPY", band=0.1, p0=0.25, p1=0.15)
    title = text.xcorr_title("us_recession", xc)
    assert title == (
        "Recession odds and SPY (S&P 500) move in the same hour, so neither gets a head start"
    )


def test_opposite_sign_neighbour_is_not_a_link():
    xc = xcorr("TLT", p2=0.2, p3=-0.15)
    assert "only isolated bars poke out" in text.xcorr_title("fed_decision", xc)


def test_lone_bar_is_luck():
    xc = xcorr("TLT", p2=0.2)  # neighbours at +1 and +3 stay inside the band
    title = text.xcorr_title("fed_decision", xc)
    assert title == (
        "No clear timing link between Fed odds and TLT (long-term bonds): only isolated bars "
        "poke out, which is likely luck"
    )


def test_all_inside_band_is_a_valid_result():
    xc = xcorr("TLT", p2=0.09, m3=-0.05)
    assert text.xcorr_title("fed_decision", xc) == (
        "No clear timing link between Fed odds and TLT (long-term bonds): every bar sits in the "
        "noise zone"
    )
    assert "That's a valid result, not a failure." in text.xcorr_so_what(xc)


def test_bar_exactly_on_the_band_is_inside():
    assert text.classify_xcorr(xcorr("TLT", band=0.1, p2=0.1)).kind == "none"


def test_preview_prefix_when_not_enough_data():
    xc = xcorr("TLT", p2=0.2, p3=0.15)
    assert text.xcorr_title("fed_decision", xc, preview=True).startswith("Preview: Fed odds")
    res = results(xcorr={"TLT": xc}, confidence=Confidence("Not enough data", "Only 2 releases."))
    assert text.finding("fed_decision", res, "TLT").startswith("Preview: ")


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
    assert text.tally(res) == "1 leads, 2 no head start, 1 needs data"
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
        + [t for g in text.GLOSSARY for t in g]
        + [info.question for info in text._PAIR_INFO.values()]
    )
    for banned in (*text._PAIR_INFO, "pairs.yaml", "python -m", "step 6"):
        assert banned not in blob


def test_control_ticker_no_link_is_good_news():
    so_what = text.xcorr_so_what(xcorr("XLU"))
    assert "That's a valid result, not a failure." in so_what and "good news" in so_what
    assert "good news" not in text.xcorr_so_what(xcorr("TLT"))


def test_per_ticker_finding_and_missing_ticker():
    res = results(xcorr={"TLT": xcorr("TLT", p2=0.2, p3=0.15), "XLU": xcorr("XLU")})
    assert text.finding("fed_decision", res, "TLT").startswith("Fed odds tend to move about 2")
    assert text.finding("fed_decision", res, "XLU").startswith("No clear timing link")
    assert text.finding("fed_decision", res, "SPY") == "Not run yet"
    assert text.so_what(res, "SPY") == text.NOTHING_TO_CONCLUDE


def test_headline_does_not_claim_a_finding_when_every_verdict_is_too_early():
    res = {"a": results(verdict="Too early to tell"), "b": results(verdict="Too early to tell")}
    assert text.headline(res) == "Too early to tell for every pair so far"

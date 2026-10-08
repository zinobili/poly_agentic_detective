"""Smoke tests for the Streamlit page via AppTest, on a tiny real-data fixture panel."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dashboard_helpers import LAGS

APP = Path(__file__).parents[1] / "src" / "poly_actor" / "dashboard" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures" / "dashboard_clean"
FORBIDDEN = (
    "fed_decision",
    "us_recession",
    "bitcoin_monthly_ladder",
    "us_cpi_inflation",
    "pairs.yaml",
    "python -m",
    "step 6",
)

FED_RESULTS = {
    "pair_id": "fed_decision",
    "xcorr": {
        "TLT": {
            "lags": list(LAGS),
            "r": [0.2 if lag in (2, 3) else 0.0 for lag in LAGS],
            "band": 0.1,
        },
        "XLU": {"lags": list(LAGS), "r": [0.0] * len(LAGS), "band": 0.1},
    },
    "verdict": "Polymarket moves first",
    "confidence": {"level": "Medium", "reason": "Only 2 meetings."},
    "checklist": [
        {
            "name": "Granger",
            "status": "Passed",
            "plain": "Odds help predict prices beyond their own past",
            "technical": "Granger causality, BH-adjusted p = 0.012",
        }
    ],
}


def _walk(node):
    yield node
    for child in getattr(node, "children", {}).values():
        yield from _walk(child)


def page_text(at: AppTest) -> str:
    """Every element's protobuf text: markdown, captions, labels, options, chart JSON."""
    protos = "\n".join(str(el.proto) for el in _walk(at.main) if hasattr(el, "proto"))
    return protos.replace("\\'", "'")  # protobuf text format escapes apostrophes


def run_app(monkeypatch, clean_dir: Path) -> AppTest:
    monkeypatch.setenv("POLY_ACTOR_CLEAN_DIR", str(clean_dir))
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_not_run_yet_page(monkeypatch):
    at = run_app(monkeypatch, FIXTURES)  # panel present, no results files
    body = page_text(at)
    assert "Analysis not run yet: only the raw data below is real" in body
    assert "We haven't run the tests yet" in body
    assert body.count("Not run yet") >= 8  # a badge and a finding on each of the 4 cards
    assert body.count("Tests not run") >= 5  # 4 card meters plus the open verdict panel
    for banned in FORBIDDEN:
        assert banned not in body


def test_not_run_page_shows_real_chart3_and_no_analysis_charts(monkeypatch):
    at = run_app(monkeypatch, FIXTURES)
    body = page_text(at)
    assert "Time (UTC)" in body
    assert body.count("This chart appears once the tests have run") == 2  # charts 1 and 2
    assert "Data on hand: 2025-03-10" in body


def test_cards_open_the_pair_without_reset(monkeypatch):
    at = run_app(monkeypatch, FIXTURES)
    at.button(key="open_1").click().run()
    assert at.session_state["selected_pair"] == "us_recession"
    assert "No aligned price data for this stock" in page_text(at)


def test_tabs_show_name_and_short_verdict(monkeypatch):
    at = run_app(monkeypatch, FIXTURES)
    assert at.radio[0].options[0] == "Fed · not run"


def test_page_with_results_computes_titles(monkeypatch, tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "fed_decision.json").write_text(json.dumps(FED_RESULTS))
    (tmp_path / "panel_fed_decision.parquet").write_bytes(
        (FIXTURES / "panel_fed_decision.parquet").read_bytes()
    )
    body = page_text(run_app(monkeypatch, tmp_path))
    assert "Fed odds tend to move about 2 hours before TLT (long-term bonds)" in body
    assert "✓ Passed: Odds help predict prices beyond their own past" in body
    assert "Granger causality, BH-adjusted p = 0.012" in body
    assert "Analysis not run for 3 of 4 pairs" in body
    assert "Analysis not run yet: only" not in body
    for banned in FORBIDDEN:
        assert banned not in body


@pytest.mark.parametrize("junk", ["{bad", '{"pair_id": "fed_decision", "xcorr": 5}'])
def test_junk_results_degrade_to_not_run(monkeypatch, tmp_path, junk):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "fed_decision.json").write_text(junk)
    body = page_text(run_app(monkeypatch, tmp_path))
    assert "Not run yet" in body


def _with_fed_results(tmp_path: Path) -> Path:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "fed_decision.json").write_text(json.dumps(FED_RESULTS))
    (tmp_path / "panel_fed_decision.parquet").write_bytes(
        (FIXTURES / "panel_fed_decision.parquet").read_bytes()
    )
    return tmp_path


def _picker(at: AppTest):
    return next(r for r in at.radio if r.label == "Compare against")


def test_ticker_picker_switches_between_link_and_control(monkeypatch, tmp_path):
    at = run_app(monkeypatch, _with_fed_results(tmp_path))
    picker = _picker(at)
    assert picker.options == [
        "TLT long-term bonds",
        "SPY S&P 500",
        "XLF banks",
    ]
    assert "Fed odds tend to move about 2 hours before TLT (long-term bonds)" in page_text(at)


def test_ticker_without_results_shows_not_computed(monkeypatch, tmp_path):
    at = run_app(monkeypatch, _with_fed_results(tmp_path))
    _picker(at).set_value("SPY").run()
    chart1 = page_text(at).split("1 · Who moves first?")[1].split("2 · What")[0]
    assert "No clear timing link" not in chart1
    assert chart1.count("This chart was not computed for this stock.") == 1


def test_control_ticker_picker_label_and_title(monkeypatch, tmp_path):
    (tmp_path / "results").mkdir()
    doc = {**FED_RESULTS, "pair_id": "bitcoin_monthly_ladder"}
    (tmp_path / "results" / "bitcoin_monthly_ladder.json").write_text(json.dumps(doc))
    at = run_app(monkeypatch, tmp_path)
    at.button(key="open_2").click().run()
    assert "XLU utilities (control)" in _picker(at).options
    _picker(at).set_value("XLU").run()
    body = page_text(at)
    assert "No clear timing link between Bitcoin price odds and XLU (utilities)" in body
    assert "good news" in body

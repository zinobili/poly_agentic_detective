"""Results contract parsing and read-only loading."""

import json
import logging
import shutil
from pathlib import Path

import pytest

from dashboard_helpers import LAGS
from poly_actor.dashboard.contract import load_results, parse_results
from poly_actor.dashboard.load import (
    available_tickers,
    load_pair_specs,
    load_panel,
    panel_coverage,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dashboard_clean"

FULL = {
    "pair_id": "fed_decision",
    "n_events": 19,
    "xcorr": {"TLT": {"lags": list(LAGS), "r": [0.0] * 25, "band": 0.05}},
    "event_study": {
        "TLT": {
            "steps": ["-1", "0", "+1"],
            "mean": [0.0, 0.1, 0.2],
            "ci_low": [-0.1, 0.0, 0.1],
            "ci_high": [0.1, 0.2, 0.3],
            "event_times": ["2025-03-19T18:00:00Z"],
        }
    },
    "checklist": [{"name": "x", "status": "Passed", "plain": "p", "technical": "t"}],
    "verdict": "Polymarket moves first",
    "confidence": {"level": "Medium", "reason": "Two meetings only."},
}


def _write(tmp_path: Path, doc) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "fed_decision.json").write_text(
        doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8"
    )


def test_full_file_parses(tmp_path):
    _write(tmp_path, FULL)
    res = load_results(tmp_path, "fed_decision")
    assert res.xcorr["TLT"].ticker == "TLT" and res.verdict == "Polymarket moves first"
    assert res.event_study["TLT"].event_times[0].utcoffset().total_seconds() == 0
    assert res.confidence.level == "Medium" and res.n_events == 19


def test_missing_file_is_none(tmp_path):
    assert load_results(tmp_path, "fed_decision") is None


def test_corrupt_file_is_none_and_names_the_path(tmp_path, caplog):
    _write(tmp_path, "{not json")
    with caplog.at_level(logging.WARNING):
        assert load_results(tmp_path, "fed_decision") is None
    assert "fed_decision.json" in caplog.text


def test_file_for_another_pair_is_ignored(tmp_path):
    _write(tmp_path, {**FULL, "pair_id": "us_recession"})
    assert load_results(tmp_path, "fed_decision") is None


@pytest.mark.parametrize(
    "slot,bad",
    [
        ("xcorr", {"TLT": {**FULL["xcorr"]["TLT"], "r": [0.0] * 24}}),  # length mismatch
        ("xcorr", {"TLT": {**FULL["xcorr"]["TLT"], "band": None}}),
        ("xcorr", {"TLT": {**FULL["xcorr"]["TLT"], "r": [float("nan")] * 25}}),
        ("xcorr", {"TLT": {**FULL["xcorr"]["TLT"], "band": float("inf")}}),
        ("xcorr", {"TLT": 5}),
        ("event_study", {"TLT": {**FULL["event_study"]["TLT"], "ci_low": [float("nan")] * 3}}),
        ("event_study", {"TLT": {**FULL["event_study"]["TLT"], "ci_high": [float("inf")] * 3}}),
        (
            "event_study",
            {"TLT": {**FULL["event_study"]["TLT"], "event_times": ["2025-03-19T18:00:00"]}},
        ),
        ("checklist", [{"name": "x", "status": "Maybe"}]),
        ("verdict", "Winner"),
        ("confidence", {"level": "Huge", "reason": "x"}),
        ("confidence", {"level": "High"}),
    ],
)
def test_bad_slot_becomes_none_and_others_survive(slot, bad):
    res = parse_results({**FULL, slot: bad})
    assert getattr(res, slot) is None
    assert res.n_events == 19


def test_empty_object_is_all_none():
    res = parse_results({"pair_id": "fed_decision"})
    assert (res.xcorr, res.event_study, res.checklist, res.verdict, res.confidence) == (None,) * 5


def test_unsorted_lags_are_sorted():
    xc = parse_results(
        {"pair_id": "p", "xcorr": {"T": {"lags": [1, 0], "r": [0.5, 0.1], "band": 0.1}}}
    ).xcorr["T"]
    assert xc.lags == (0, 1) and xc.r == (0.1, 0.5)


def test_pair_specs_from_real_pairs_file():
    specs = {s.pair_id: s.tickers for s in load_pair_specs()}
    assert specs["fed_decision"] == ("TLT", "SPY", "XLF")
    assert len(specs) == 4


def test_fixture_panel_loading_and_coverage():
    panel = load_panel(FIXTURES, "fed_decision")
    assert load_panel(FIXTURES, "us_recession") is None
    cov = panel_coverage(panel)
    assert cov.rows == len(panel) and cov.first.utcoffset().total_seconds() == 0
    assert cov.both_trading_rows == int(panel["both_trading"].sum())
    assert available_tickers(panel, ("TLT", "IWM-SPY", "XLF")) == ("TLT", "XLF")


def test_loading_does_not_write(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "c")
    before = sorted(p.name for p in (tmp_path / "c").rglob("*"))
    load_panel(tmp_path / "c", "fed_decision")
    load_results(tmp_path / "c", "fed_decision")
    assert sorted(p.name for p in (tmp_path / "c").rglob("*")) == before


def test_one_bad_ticker_does_not_drop_the_others():
    bad = {"lags": [0], "r": [float("nan")], "band": 0.1}
    res = parse_results({"pair_id": "p", "xcorr": {**FULL["xcorr"], "XLU": bad}})
    assert list(res.xcorr) == ["TLT"]


def test_bad_entries_are_logged(caplog):
    with caplog.at_level(logging.WARNING):
        parse_results({"pair_id": "p", "xcorr": {"TLT": {"lags": [0], "r": [float("nan")]}}})
    assert "invalid xcorr entry for TLT" in caplog.text


def test_corrupt_panel_is_none_and_names_the_path(tmp_path, caplog):
    (tmp_path / "panel_fed_decision.parquet").write_bytes(b"not a parquet file")
    with caplog.at_level(logging.WARNING):
        assert load_panel(tmp_path, "fed_decision") is None
    assert "panel_fed_decision.parquet" in caplog.text

"""End to end on synthetic inputs: phase-1 jobs, BH, verdicts, strict JSON, the dashboard
contract and the Streamlit page for all four pairs. Also hand-off rows 9-11."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

import analysis_synth as synth
from poly_actor.analysis import cpi, models, results, run, runners, verdict
from poly_actor.dashboard.contract import (
    VERDICTS,
    CheckRowDoc,
    ResultsDoc,
    XCorrDoc,
    load_results,
    parse_results,
)

PAIRS = ("fed_decision", "bitcoin_monthly_ladder", "us_cpi_inflation", "us_recession")
P_KEY = re.compile(r"(^p$|^p_|_p$|p_value|permutation_p|p_one|p_two|bh_adjusted|bh_q)")


@pytest.fixture(scope="module")
def written(analysis_written) -> tuple[Path, dict, dict]:
    """The synthetic run (session-scoped in conftest, shared with the findings tests)."""
    return analysis_written


def _strict(path: Path) -> dict:
    def bad(token):
        raise ValueError(f"non-finite number {token} in {path.name}")

    return json.loads(path.read_text("utf-8"), parse_constant=bad)


def test_every_pair_writes_strict_json_that_the_contract_accepts(written):
    clean, _, _ = written
    for pid in PAIRS:
        doc = _strict(clean / "results" / f"{pid}.json")
        assert doc["schema_version"] == 2
        res = load_results(clean, pid)
        assert res is not None and res.verdict in VERDICTS
        assert res.confidence is not None and res.checklist is not None
        assert res.event_study, pid  # chart 2 present for every pair
    _strict(clean / "results" / "summary.json")


def test_chart1_slots(written):
    clean, _, _ = written
    assert load_results(clean, "us_cpi_inflation").xcorr_not_in_plan
    assert load_results(clean, "us_recession").xcorr_not_in_plan
    btc = load_results(clean, "bitcoin_monthly_ladder").xcorr["IBIT"]
    assert btc.residualised is not None
    fed = load_results(clean, "fed_decision").xcorr
    assert set(fed) == {"TLT", "SPY", "XLF"} and fed["TLT"].lags == tuple(range(-6, 7))


def test_bh_family_is_the_three_primaries(written):
    _, _, summary = written
    assert [r["pair_id"] for r in summary["primary_family"]] == list(run.PRIMARY_ORDER)
    assert summary["exploratory_family"]  # separate, labelled family


def test_verdict_and_confidence_are_computed_not_typed(written):
    _, docs, summary = written
    fam = {r["pair_id"]: r for r in summary["primary_family"]}
    for pid in run.PRIMARY_ORDER:
        doc = docs[pid]
        row = next(r for r in doc["checklist"] if r["name"] == "Many-pairs correction")
        assert row["status"] == ("Passed" if fam[pid]["reject"] else "Failed")


def test_a29_btc_publication(written):
    """Prereg A29 items 1-4 on the written results."""
    clean, docs, summary = written
    btc = docs["bitcoin_monthly_ladder"]
    assert (btc["verdict"], btc["verdict_reason"]) == (verdict.TOO_EARLY, verdict.A29_REASON)
    assert btc["confidence"]["level"] == "Low"
    assert btc["verdict_if_a27_rule3_read_literally"] in VERDICTS
    blob = json.dumps(btc["checklist"]) + btc["verdict_reason"]
    assert "Failed (opposite sign)" not in blob and "rule out" not in blob
    status = {r["name"]: r["status"] for r in btc["checklist"]}
    assert status["Primary test"] == status["Beyond Bitcoin's own price"] == verdict.NOT_VALID
    for tk, x in btc["xcorr"].items():  # A29 addendum: every residualised panel, XLU too
        assert x["residualised"].get("note") == verdict.A29_NOTE, tk
    assert btc["event_study"]  # every BTC Chart 2 is residualised on the same control
    assert all(es.get("note") == verdict.A29_NOTE for es in btc["event_study"].values())
    assert "btc_overnight_IBIT_spot_control" in run.A29_EXPLORATORY
    assert all("note" not in {k for k in x if k != "residualised"} for x in btc["xcorr"].values())
    noted = {r["test"] for r in summary["exploratory_family"] if "note" in r}
    assert noted == set(run.A29_EXPLORATORY)
    assert {r["pair_id"] for r in summary["primary_family"]} == set(run.PRIMARY_ORDER)
    res = load_results(clean, "bitcoin_monthly_ladder")
    assert res.primary_ticker == "IBIT" and res.xcorr["IBIT"].residualised.note
    for pid in ("fed_decision", "us_cpi_inflation", "us_recession"):
        assert "verdict_if_a27_rule3_read_literally" not in docs[pid]


def test_primary_ticker_is_written_for_every_pair(written):
    _, docs, _ = written
    assert {p: docs[p]["primary_ticker"] for p in PAIRS} == {
        "fed_decision": "TLT",
        "bitcoin_monthly_ladder": "IBIT",
        "us_cpi_inflation": "TLT",
        "us_recession": "IWM-SPY",
    }


# ---------------------------------------------------------------- the typed contract


def test_every_doc_round_trips_through_the_typed_contract(written):
    """Producer and consumer share `ResultsDoc`: a renamed or dropped key fails here."""
    _, docs, _ = written
    for pid, doc in docs.items():
        raw = results.jsonable(doc)
        assert set(raw) <= set(ResultsDoc.__annotations__), pid
        assert ResultsDoc.__required_keys__ <= set(raw), pid
        assert all(set(r) == set(CheckRowDoc.__annotations__) for r in raw["checklist"])
        res = parse_results(raw)
        assert (res.pair_id, res.primary_ticker) == (pid, raw["primary_ticker"])
        assert (res.verdict, res.verdict_reason) == (raw["verdict"], raw["verdict_reason"])
        assert res.confidence.__dict__ == raw["confidence"]
        assert (res.n_events, res.stocks_first) == (raw["n_events"], raw["stocks_first"])
        assert res.params == raw["params"]
        assert [r.__dict__ for r in res.checklist] == raw["checklist"]
        assert set(res.event_study) == set(raw["event_study"])
        assert res.event_study_notes == (raw.get("event_study_notes") or None)
        if raw["xcorr"] == results.NOT_IN_PLAN:
            assert res.xcorr_not_in_plan and res.xcorr is None
            continue
        assert set(res.xcorr) == set(raw["xcorr"])
        for tk, x in raw["xcorr"].items():
            assert set(x) <= set(XCorrDoc.__annotations__), (pid, tk)
            assert res.xcorr[tk].lags == tuple(x["lags"])
            assert (res.xcorr[tk].residualised is None) == ("residualised" not in x)


def test_jsonable_names_an_unknown_type():
    assert results.jsonable({"a": (np.float64("nan"), np.int64(2), True, None)}) == {
        "a": [None, 2, True, None]
    }
    with pytest.raises(TypeError, match="object"):
        results.jsonable({"a": object()})


def test_write_json_leaves_no_temp_file(tmp_path):
    path = tmp_path / "results" / "x.json"
    results.write_json({"a": 1.0}, path)
    results.write_json({"a": 2.0}, path)
    assert json.loads(path.read_text("utf-8")) == {"a": 2.0}
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


# ---------------------------------------------------------------- row 11: pair 4


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def test_pair4_is_descriptive_low_and_has_no_p_value_anywhere(written):
    clean, _, _ = written
    doc = _strict(clean / "results" / "us_recession.json")
    assert doc["verdict"] == "Descriptive only" and doc["confidence"]["level"] == "Low"
    assert not [k for k in _keys(doc) if P_KEY.search(k)]
    blob = json.dumps(doc)
    assert "p =" not in blob and "p-value" not in blob


def test_pair4_lists_the_selected_dates(written):
    _, docs, _ = written
    rises = docs["us_recession"]["details"]["main_change_in_probability"]["groups"]["rises"]
    assert len(rises["dates"]) == 10 and len(set(rises["dates"])) == 10


# ---------------------------------------------------------------- rows 9-10: CPI


def _null_cpi(n: int = 11, seed: int = 0):
    """n releases with rho exactly 0 (a permutation found by fixed-seed search)."""
    rng = np.random.default_rng(seed)
    proxy = np.arange(n, dtype=float)
    while True:
        gap = rng.permutation(n).astype(float)
        if abs(models.spearman(proxy, gap)) < 1e-12:
            return proxy * 0.01, gap * 0.001


def _cpi_facts(validation_ok: bool, n: int = 11):
    proxy, gap = _null_cpi(n)
    valid = cpi.Validation(n, n if validation_ok else 2, validation_ok, [])
    rng = np.random.default_rng(1)
    core = runners.cpi_core(
        proxy, gap, proxy.copy(), valid, rng.standard_normal(300), rng.standard_normal(300)
    )
    reject, adj = models.bh([0.5, 0.5, core.p_one], verdict.BH_Q)
    return core, runners.cpi_facts(core, bool(reject[2]), float(adj[2]))


def test_cpi_eleven_usable_null_runs_and_is_underpowered():
    core, facts = _cpi_facts(validation_ok=True)
    assert core.n_usable == 11 and core.test is not None and core.test.method == "exact"
    label, reason = verdict.verdict(facts)
    assert label == "Too early to tell" and reason.startswith("Underpowered")
    # The frozen MDE (0.72) alone would have said "No head start": B3's 0.5 margin decides.
    assert 0.5 < facts.upper_r < verdict.MDE["cpi"]


def test_cpi_validation_failure_is_too_early_and_previews(tmp_path, monkeypatch):
    _, facts = _cpi_facts(validation_ok=False)
    assert verdict.verdict(facts)[0] == "Too early to tell"
    assert verdict.confidence(facts)[0] == "Not enough data"


def test_cpi_below_ten_usable_still_enters_bh():
    proxy, gap = _null_cpi(7)
    core = runners.cpi_core(proxy, gap, proxy, cpi.Validation(8, 8, True, []))
    jobs = {
        "fed_decision": run.fed_job(synth.fed_panel(1), {"fomc": set(), "cpi": set()}),
        "us_cpi_inflation": run.Job("us_cpi_inflation", core, {}, {}, {}),
    }
    _, summary = run.assemble(jobs)
    cpi_row = summary["primary_family"][2]
    assert cpi_row["p_one_sided"] == pytest.approx(core.p_one)


# ---------------------------------------------------------------- dashboard on the results


def test_dashboard_renders_all_four_pairs(written, monkeypatch, tmp_path):
    from test_dashboard_app import FORBIDDEN, page_text, run_app

    clean, docs, _ = written
    target = tmp_path / "clean"
    shutil.copytree(clean, target)
    at = run_app(monkeypatch, target)
    body = page_text(at)
    assert "Analysis not run" not in body
    for banned in FORBIDDEN:
        assert banned not in body
    seen = set()
    for i in range(len(PAIRS)):
        at.button(key=f"open_{i}").click().run()
        assert not at.exception
        pid = at.session_state["selected_pair"]
        seen.add(pid)
        body = page_text(at)
        if pid in ("us_cpi_inflation", "us_recession"):
            assert "Not part of the plan" in body
        assert "Why this verdict: " + docs[pid]["verdict_reason"] in body
        assert "work like a mirror" not in body and "so neither gets a head start" not in body
    assert seen == set(PAIRS)

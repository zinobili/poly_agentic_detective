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
from poly_actor.analysis import cpi, models, run, runners, verdict
from poly_actor.dashboard.contract import VERDICTS, load_results

PAIRS = ("fed_decision", "bitcoin_monthly_ladder", "us_cpi_inflation", "us_recession")
P_KEY = re.compile(r"(^p$|^p_|_p$|p_value|permutation_p|p_one|p_two|bh_adjusted|bh_q)")


def _jobs() -> dict[str, run.Job]:
    panel, spot = synth.btc_panel(0)
    cpi_panel, tab, placebo_tab = synth.cpi_inputs(0)
    return {
        "fed_decision": run.fed_job(synth.fed_panel(0), {"fomc": set(), "cpi": set()}),
        "bitcoin_monthly_ladder": run.btc_job(panel, spot),
        "us_cpi_inflation": run.cpi_job(cpi_panel, tab, placebo_tab),
        "us_recession": run.recession_job(synth.recession_panel(0)),
    }


@pytest.fixture(scope="module")
def written(tmp_path_factory) -> tuple[Path, dict, dict]:
    clean = tmp_path_factory.mktemp("clean")
    docs, summary = run.assemble(_jobs())
    run.write_all(docs, summary, clean)
    return clean, docs, summary


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
    assert seen == set(PAIRS)

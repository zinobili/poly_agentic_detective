"""Step 7: the generated findings report (rules-as-examples table of docs/handoff/step7.md)."""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from poly_actor.analysis import findings, run
from poly_actor.analysis.findings import EXPLORATORY, MOVES_WITH
from poly_actor.config import CLEAN_DIR
from poly_actor.dashboard import text
from poly_actor.dashboard.load import load_all_results, load_pair_specs

SPECS = load_pair_specs()
REAL_STATE = {
    "fed_decision": "No head start",
    "bitcoin_monthly_ladder": "Too early to tell",
    "us_cpi_inflation": "Too early to tell",
    "us_recession": "Descriptive only",
}
HEADLINE = (
    "So far no pair shows Polymarket odds moving ahead of stocks; 3 of 4 are still undecided or "
    "descriptive only"
)
HEX = re.compile(r"`[0-9a-f]{7,64}(-dirty)?`")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:e[-+]?\d+)?(?![\w])")


# ---------------------------------------------------------------- helpers


def _write(tmp: Path, docs: dict, summary: dict) -> Path:
    out = tmp / "results"
    out.mkdir(parents=True, exist_ok=True)
    for pid, doc in docs.items():
        (out / f"{pid}.json").write_text(json.dumps(doc), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return tmp


@pytest.fixture
def real_like(analysis_written, tmp_path) -> tuple[Path, dict, dict]:
    """The synthetic run with the verdicts of the real step-6 results (rules table row 1)."""
    clean, _, _ = analysis_written
    docs = {p: json.loads((clean / "results" / f"{p}.json").read_text("utf-8")) for p in REAL_STATE}
    summary = json.loads((clean / "results" / "summary.json").read_text("utf-8"))
    for pid, v in REAL_STATE.items():
        docs[pid]["verdict"] = v
    docs["bitcoin_monthly_ladder"]["verdict_if_a27_rule3_read_literally"] = "No head start"
    for row in summary["exploratory_family"]:
        if row["test"] in ("btc_overnight_IBIT", "fed_overnight_TLT", "btc_COIN_lag1"):
            row["reject"] = True
    return _write(tmp_path, docs, summary), docs, summary


def _render(clean: Path) -> str:
    return findings.render(findings.load_inputs(clean, SPECS))


def _section(md: str, number: int) -> str:
    parts = re.split(r"^## (\d+)\. ", md, flags=re.MULTILINE)
    return parts[parts.index(str(number)) + 1]


def _pair_block(md: str, name: str) -> str:
    sec = _section(md, 2)
    return sec.split(f"### {name}\n", 1)[1].split("\n### ", 1)[0]


def _json_numbers(node, out: set[float]) -> set[float]:
    """Every number in a results tree, including numbers inside its strings (absolute)."""
    if isinstance(node, dict):
        for v in node.values():
            _json_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _json_numbers(v, out)
    elif isinstance(node, bool) or node is None:
        pass
    elif isinstance(node, int | float):
        out.add(abs(float(node)))
    elif isinstance(node, str):
        out.update(float(t) for t in NUMBER.findall(node))
    return out


def untraced_numbers(md: str, results_dir: Path) -> list[str]:
    """Number tokens of the report that neither equal nor round from a results value."""
    values: set[float] = set()
    for path in results_dir.glob("*.json"):
        _json_numbers(json.loads(path.read_text("utf-8")), values)
    by_sig = {s: {float(f"{v:.{s}g}") for v in values} for s in range(1, 7)}
    by_dec = {d: {float(f"{v:.{d}f}") for v in values} for d in range(0, 7)}
    body = HEX.sub("", md)  # the results fingerprint and the code commit (hex ids, not numbers)
    body = re.sub(r"^#+ \d+\. ", "", body, flags=re.MULTILINE)  # section numbers
    missing = []
    for tok in sorted(set(NUMBER.findall(body))):
        x = float(tok)
        mantissa = tok.split("e")[0].replace(".", "").lstrip("0") or "0"
        sig = min(max(len(mantissa), 1), 6)
        dec = len(tok.split("e")[0].split(".")[1]) if "." in tok else 0
        if x in values or x in by_sig[sig] or ("e" not in tok and x in by_dec[min(dec, 6)]):
            continue
        missing.append(tok)
    return missing


# ---------------------------------------------------------------- rules as examples


def test_headline_is_the_dashboard_headline(real_like):
    """Row 1: same generator as the dashboard, so the two strings are equal."""
    clean, _, _ = real_like
    md = _render(clean)
    dashboard = text.headline(load_all_results(clean, SPECS))
    assert dashboard == HEADLINE
    assert f"**{dashboard}.**" in _section(md, 1)


def test_every_number_traces_to_the_results(real_like):
    """Row 2: each number token outside the template equals or rounds from a results value."""
    clean, _, _ = real_like
    md = _render(clean)
    assert NUMBER.findall(md), "the report must contain numbers to trace"
    assert untraced_numbers(md, clean / "results") == []


def test_the_tracer_catches_an_invented_number(real_like):
    """Mutation check of the row-2 test: a typed-in number is reported."""
    clean, _, _ = real_like
    md = _render(clean) + "\nThe lead is 123.457 hours.\n"
    assert untraced_numbers(md, clean / "results") == ["123.457"]


def test_template_prose_has_no_digits():
    """Row 3: digits only in amendment ids and section numbers."""
    source = findings.TEMPLATE_PATH.read_text(encoding="utf-8")
    stripped = re.sub(r"\bA\d+\b", "", source)
    stripped = re.sub(r"^#+ \d+\. ", "", stripped, flags=re.MULTILINE)
    assert re.findall(r".*\d.*", stripped) == []


def test_template_digit_rule_fails_on_a_typed_number():
    stripped = re.sub(r"\bA\d+\b", "", "A29 says twelve, not 12")
    assert re.findall(r".*\d.*", stripped) == [" says twelve, not 12"]


def test_btc_literal_verdict_only_in_the_post_hoc_section(real_like):
    """Row 4: published "Too early to tell" with the A29 reason; the literal verdict appears
    only in section 4, labelled post-hoc."""
    clean, docs, _ = real_like
    md = _render(clean)
    btc = _pair_block(md, "Bitcoin price ladder")
    assert "**Verdict: Too early to tell.**" in btc
    assert docs["bitcoin_monthly_ladder"]["verdict_reason"] in btc
    assert "No head start" not in btc
    for n in (1, 3, 5, 6):  # Fed's own "No head start" may appear; never next to Bitcoin
        lines = [ln for ln in _section(md, n).splitlines() if "No head start" in ln]
        assert not any("Bitcoin" in ln for ln in lines), lines
    post_hoc = _section(md, 4)
    assert "POST-HOC" in post_hoc
    assert 'computation gives "No head start". That literal verdict is **not** a finding' in (
        " ".join(post_hoc.split())
    )


def test_rejected_overnight_test_reads_moves_with_never_first_or_lead(real_like):
    """Row 5: a BH-rejected overnight test is listed under exploratory as "moves with"."""
    clean, _, _ = real_like
    md = _render(clean)
    for name in ("btc_overnight_IBIT", "fed_overnight_TLT"):
        row = next(line for line in _section(md, 5).splitlines() if f"`{name}`" in line)
        assert MOVES_WITH in row
        assert not re.search(r"\b(first|lead|leads|ahead)\b", row, re.IGNORECASE), row
    biased = next(line for line in _section(md, 5).splitlines() if "`btc_COIN_lag1`" in line)
    assert biased.endswith("| biased (A29), not read as evidence |")


def test_no_exploratory_description_uses_a_timing_word():
    for spec in EXPLORATORY.values():
        assert not re.search(r"\b(first|lead|leads|ahead)\b", spec.what, re.IGNORECASE)


def test_regenerating_is_byte_identical(real_like, tmp_path):
    clean, _, _ = real_like
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    findings.write_report(clean, SPECS, a)
    findings.write_report(clean, SPECS, b)
    assert a.read_bytes() == b.read_bytes()
    assert b"\r\n" not in a.read_bytes()


def test_required_sections_and_disclaimer(real_like):
    clean, _, _ = real_like
    md = _render(clean)
    titles = re.findall(r"^## (\d+)\. ", md, flags=re.MULTILINE)
    assert titles == ["1", "2", "3", "4", "5", "6"]
    assert "Not financial advice. Paper only." in md
    assert "python -m poly_actor.refresh" in _section(md, 6)
    assert "A28 (decided before the real run" in _section(md, 4)
    fed = _pair_block(md, "Fed rate decision")
    assert "BH-adjusted p = " in fed and "90% CI" in fed and "n = " in fed
    assert "is a bound, not a zero" in _section(md, 3)  # Fed: bounded by the MDE


def test_no_timing_claim_without_a_lead_verdict(real_like):
    """Checklist 5: no pair section says the odds lead when no verdict says so."""
    clean, _, _ = real_like
    md = _render(clean)
    for spec in SPECS:
        block = _pair_block(md, text.pair_info(spec.pair_id).name)
        claims = [ln for ln in block.splitlines() if ln.startswith("- ")]
        res = load_all_results(clean, SPECS)[spec.pair_id]
        verdict_line = f"- **Verdict: {res.verdict}.** {text.finding(spec.pair_id, res)}."
        assert claims[0].startswith(verdict_line)
        claim = re.compile(r"\bmoves? first\b|\btend to move before\b|\bleads? (stocks|TLT|IBIT)")
        assert not any(claim.search(ln) for ln in claims), block


def test_missing_slot_is_an_error_not_left_in_the_text():
    with pytest.raises(KeyError, match="upper"):
        findings.fill("bound {{upper}}", pair="Fed")


def test_report_cli_without_results_exits_nonzero(tmp_path, capsys):
    out = tmp_path / "findings.md"
    assert run.main(["report", "--clean-dir", str(tmp_path), "--out", str(out)]) == 2
    assert not out.exists()
    assert "run the analysis first" in capsys.readouterr().err


def test_report_cli_writes_the_file(real_like, tmp_path):
    clean, _, _ = real_like
    out = tmp_path / "f.md"
    assert run.main(["report", "--clean-dir", str(clean), "--out", str(out)]) == 0
    assert out.read_text("utf-8") == _render(clean)
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []  # atomic write


def test_report_cli_names_a_corrupt_results_file(real_like, tmp_path, capsys):
    clean, _, _ = real_like
    bad = next((clean / "results").glob("fed_decision.json"))
    bad.write_text(bad.read_text("utf-8")[:50], encoding="utf-8")  # truncated JSON
    out = tmp_path / "f.md"
    assert run.main(["report", "--clean-dir", str(clean), "--out", str(out)]) == 2
    assert not out.exists()
    assert "fed_decision.json" in capsys.readouterr().err


def test_a_missing_pair_says_not_run(real_like, tmp_path):
    clean, _, _ = real_like
    target = tmp_path / "partial"
    shutil.copytree(clean, target)
    (target / "results" / "us_recession.json").unlink()
    md = _render(target)
    assert "No results file for this pair yet." in _pair_block(md, "US recession")


def test_a_lead_verdict_replaces_the_no_lead_bullet(real_like, tmp_path):
    clean, docs, summary = real_like
    docs = copy.deepcopy(docs)
    docs["fed_decision"]["verdict"] = "Polymarket moves first"
    md = _render(_write(tmp_path / "lead", docs, summary))
    assert "No pair shows Polymarket odds moving ahead" not in md
    assert "Fed rate decision: a lead in this data is not proof" in _section(md, 3)


# ---------------------------------------------------------------- the real results, if present


@pytest.mark.skipif(not (CLEAN_DIR / "results" / "summary.json").is_file(), reason="no results")
def test_real_report_numbers_trace_to_the_real_results():
    md = _render(CLEAN_DIR)
    assert untraced_numbers(md, CLEAN_DIR / "results") == []
    assert f"**{text.headline(load_all_results(CLEAN_DIR, SPECS))}.**" in md

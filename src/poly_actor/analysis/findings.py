"""The findings report (`docs/findings.md`), generated from the results files. Pure rendering.

Every number in the report is read from `data/clean/results/*.json`; the prose lives in
`findings_template.txt`, which holds no digits except amendment ids and section numbers
(both rules are tested). The one-line answer is `dashboard.text.headline`, the same function
the dashboard uses, so the two cannot disagree. Rendering is deterministic: the same results
files give a byte-identical report.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from poly_actor.analysis import verdict
from poly_actor.analysis.results import write_text_atomic
from poly_actor.config import ROOT
from poly_actor.dashboard import text
from poly_actor.dashboard.contract import PairResults, parse_results, results_path
from poly_actor.dashboard.load import PairSpec

TEMPLATE_PATH = Path(__file__).with_name("findings_template.txt")
FINDINGS_PATH = ROOT / "docs" / "findings.md"
SUMMARY_FILE = "summary.json"

_BLOCK = re.compile(r"^<!-- block: (\w+) -->$", re.MULTILINE)
_SLOT = re.compile(r"\{\{(\w+)\}\}")


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Inputs:
    """What the report reads: raw docs and parsed results by pair id, and the BH summary."""

    specs: tuple[PairSpec, ...]
    docs: dict[str, dict[str, Any] | None]
    parsed: dict[str, PairResults | None]
    summary: dict[str, Any]
    fingerprint: str  # SHA-256 over the results files (names and bytes, sorted by name)


class ReportInputError(ValueError):
    """A results file exists but cannot be read as JSON; the message names the file."""


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportInputError(f"{path}: not valid JSON ({exc})") from exc
    return raw if isinstance(raw, dict) else None


def fingerprint(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(folder.glob("*.json")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def load_inputs(clean_dir: Path, specs: tuple[PairSpec, ...]) -> Inputs:
    """Read every results file. Raises FileNotFoundError when the analysis has not run."""
    folder = results_path(clean_dir, "any").parent
    summary = _read_json(folder / SUMMARY_FILE)
    if summary is None:
        raise FileNotFoundError(f"no {SUMMARY_FILE} in {folder}: run the analysis first")
    docs: dict[str, dict[str, Any] | None] = {}
    for s in specs:
        raw = _read_json(results_path(clean_dir, s.pair_id))
        docs[s.pair_id] = raw if raw is not None and raw.get("pair_id") == s.pair_id else None
    parsed = {pid: None if d is None else parse_results(d) for pid, d in docs.items()}
    return Inputs(specs, docs, parsed, summary, fingerprint(folder))


# ---------------------------------------------------------------- template


def template_blocks(source: str) -> dict[str, str]:
    """Named prose blocks of the template (the header comment is dropped)."""
    parts = _BLOCK.split(source)
    return {parts[i]: parts[i + 1].strip("\n") for i in range(1, len(parts), 2)}


def fill(block: str, **slots: str) -> str:
    """Replace every {{slot}}; a slot without a value is an error, never left in the text."""

    def one(m: re.Match[str]) -> str:
        if m.group(1) not in slots:
            raise KeyError(f"template slot {m.group(1)!r} has no value")
        return slots[m.group(1)]

    return _SLOT.sub(one, block)


# ---------------------------------------------------------------- number formatting


def num(v: object, sig: int = 3) -> str:
    """A results value as shown: 3 significant digits, or 'n/a'."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return "n/a"
    if isinstance(v, int):
        return str(v)
    return f"{v:.0f}" if abs(v) >= 10**sig else f"{v:.{sig}g}"


def _ci(t: dict[str, Any], level: str) -> str:
    return f"{level} CI {num(t.get('ci_low'))} to {num(t.get('ci_high'))}"


def _level(doc: dict[str, Any]) -> str:
    ci = doc.get("params", {}).get("ci_level")
    return f"{ci:.0%}" if isinstance(ci, float) else "two-sided"


def _get(node: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------- per-pair primary effect


def _fed_effect(doc: dict[str, Any]) -> list[str]:
    prim = _get(doc, "details", "primary") or {}
    t, lead = _get(prim, "tests", "sum") or {}, _get(prim, "tests", "lead") or {}
    lvl = _level(doc)
    return [
        f"**Primary effect:** TLT move per unit of odds change (Δdovishness, lags 0 to 2 "
        f"summed): {num(t.get('estimate'))} bp per bp ({_ci(t, lvl)}), one-sided p = "
        f"{num(t.get('p_one'))}.",
        f"**Lagged part only** (lags 1 and 2, the odds change an hour or two earlier): "
        f"{num(lead.get('estimate'))} bp per bp ({_ci(lead, lvl)}).",
        f"**Sample:** n = {num(prim.get('n'))} hourly bars in {num(prim.get('n_sessions'))} "
        "sessions.",
    ]


def _btc_effect(doc: dict[str, Any]) -> list[str]:
    det = doc.get("details") or {}
    t = _get(det, "primary", "tests", "lag1") or {}
    nc = _get(det, "no_control", "tests", "lag1") or {}
    lvl = _level(doc)
    label = (
        "Primary effect, biased (A29), not read as evidence"
        if doc.get("a29_note")
        else ("Primary effect")
    )
    return [
        f"**{label}:** IBIT move per 1% odds change one bar earlier, adjusted "
        f"for Bitcoin's own price: {num(t.get('estimate'))} bp ({_ci(t, lvl)}), one-sided p = "
        f"{num(t.get('p_one'))}.",
        f"**Without the price adjustment** (not affected by A29): {num(nc.get('estimate'))} bp "
        f"per 1% ({_ci(nc, lvl)}), one-sided p = {num(nc.get('p_one'))}.",
        f"**Sample:** n = {num(_get(det, 'primary', 'n'))} hourly bars in "
        f"{num(_get(det, 'primary', 'n_sessions'))} sessions.",
    ]


def _cpi_effect(doc: dict[str, Any]) -> list[str]:
    t = _get(doc, "details", "primary") or {}
    return [
        f"**Primary effect:** Spearman rho between the pre-release odds move and the TLT opening "
        f"gap (negative = in the expected direction): {num(t.get('rho'))} ({_ci(t, _level(doc))}"
        f"), exact one-sided p = {num(t.get('p_one'))}.",
        f"**Sample:** n = {num(t.get('n'))} usable releases.",
    ]


def _recession_effect(doc: dict[str, Any]) -> list[str]:
    tk = doc.get("primary_ticker")
    es = _get(doc, "event_study", tk) if isinstance(tk, str) else None
    if not isinstance(es, dict):
        return ["**Primary description:** not available."]
    lvl = _level(doc)

    def days(group: dict[str, Any]) -> str:
        return "; ".join(
            f"day {step}: {num(m)}% ({lvl} CI {num(lo)} to {num(hi)})"
            for step, m, lo, hi in zip(
                es["steps"], group["mean"], group["ci_low"], group["ci_high"], strict=True
            )
        )

    lines = [
        f"**Primary description (no test):** {text.ticker_label(tk)} on the "
        f"{num(doc.get('n_events'))} days with the largest rises in recession odds: {days(es)}."
    ]
    if isinstance(es.get("compare"), dict):
        lines.append(f"On the days with the largest falls: {days(es['compare'])}.")
    return lines


EFFECT: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "fed_decision": _fed_effect,
    "bitcoin_monthly_ladder": _btc_effect,
    "us_cpi_inflation": _cpi_effect,
    "us_recession": _recession_effect,
}


def _bh_line(inp: Inputs, pid: str) -> str | None:
    row = next((r for r in inp.summary.get("primary_family", []) if r["pair_id"] == pid), None)
    if row is None:
        return None
    held = "holds" if row["reject"] else "does not hold"
    return (
        f"**Many-pairs correction:** BH-adjusted p = {num(row['bh_adjusted'])} at q = "
        f"{num(inp.summary.get('q'))}; the result {held}."
    )


def pair_section(inp: Inputs, pid: str, blocks: dict[str, str]) -> str:
    info = text.pair_info(pid)
    doc, res = inp.docs[pid], inp.parsed[pid]
    out = [f"### {info.name}", "", f"*{info.question}*", ""]
    if doc is None or res is None or res.verdict is None:
        return "\n".join([*out, blocks["not_run"]])
    conf = res.confidence
    lines = [
        f"**Verdict: {res.verdict}.** {text.finding(pid, res)}. {res.verdict_reason or ''}".strip(),
        f"**Confidence: {conf.level}.** {conf.reason}" if conf else "**Confidence:** n/a.",
        *EFFECT.get(pid, lambda d: [])(doc),
    ]
    bh = _bh_line(inp, pid)
    if bh:
        lines.append(bh)
    if doc.get("a29_note"):
        scope = " ".join(blocks["bias_scope"].split())
        lines.append(f"**Caveat (A29):** {doc['a29_note']} {scope}")
    out += [f"- {line}" for line in lines]
    rows = doc.get("checklist") or []
    if rows:
        out += ["", "| Check | Status | Detail |", "|---|---|---|"]
        out += [
            f"| {_cell(r['plain'])} | {r['status']} | {_cell(r.get('technical', ''))} |"
            for r in rows
        ]
    return "\n".join(out)


# ---------------------------------------------------------------- section 3


def _upper_bound(pid: str, doc: dict[str, Any]) -> str | None:
    """The one-sided upper bound that made a "No head start" (H1 direction, correlation units)."""
    if pid == "fed_decision":
        return num(_get(doc, "details", "primary", "tests", "sum", "r_upper"))
    if pid == "bitcoin_monthly_ladder":
        return num(_get(doc, "details", "primary", "tests", "lag1", "r_upper"))
    if pid == "us_cpi_inflation":
        low = _get(doc, "details", "primary", "ci_low")
        return num(-low) if isinstance(low, float) else None
    return None


def does_not_show(inp: Inputs, blocks: dict[str, str]) -> str:
    out = [blocks["does_not_show"], ""]
    verdicts = {pid: r.verdict for pid, r in inp.parsed.items() if r is not None and r.verdict}
    leads = [pid for pid, v in verdicts.items() if v == verdict.FIRST]
    if leads:
        out += [fill(blocks["lead_found"], pair=text.pair_info(p).name) for p in leads]
    else:
        out.append(blocks["no_lead"])
    for pid, v in verdicts.items():
        doc, name = inp.docs[pid] or {}, text.pair_info(pid).name
        upper = _upper_bound(pid, doc)
        if v == verdict.NO_HEAD_START and upper:
            out.append(fill(blocks["bound_not_zero"], pair=name, upper=upper))
        if doc.get("a29_note"):
            out.append(fill(blocks["bias_unanswered"], pair=name, reason=doc["verdict_reason"]))
        if pid == "us_cpi_inflation":
            n = _get(doc, "details", "usable_releases")
            out.append(fill(blocks["small_sample"], pair=name, n=num(n)))
        if v == verdict.DESCRIPTIVE:
            out.append(fill(blocks["descriptive"], pair=name))
    out.append(blocks["timing_resolution"])
    notes = [
        (pid, tk, note)
        for pid, doc in inp.docs.items()
        if doc
        for tk, note in (doc.get("event_study_notes") or {}).items()
    ]
    if notes:
        out.append(blocks["missing_charts"])
        out += [f"  - {text.pair_info(p).name}, {tk}: {note}" for p, tk, note in notes]
    if any(p == "us_cpi_inflation" for p, _, _ in notes):
        out.append(blocks["cpi_signing"])
    return "\n".join(out)


# ---------------------------------------------------------------- section 4


def amendments(inp: Inputs, blocks: dict[str, str]) -> str:
    out = [blocks["amendments"], ""]
    a29 = [
        (pid, doc)
        for pid, doc in inp.docs.items()
        if doc and "verdict_if_a27_rule3_read_literally" in doc
    ]
    if a29:
        out.append(blocks["bias"])
        out += [
            fill(
                blocks["bias_literal"],
                pair=text.pair_info(pid).name,
                published=doc["verdict"],
                literal=doc["verdict_if_a27_rule3_read_literally"],
            )
            for pid, doc in a29
        ]
        out.append(blocks["bias_addendum"])
    out.append(blocks["placebo_rule"])
    out += [
        fill(
            blocks["placebo_literal"],
            pair=text.pair_info(pid).name,
            literal=doc["verdict_if_placebo_read_literally"],
            published=doc["verdict"],
        )
        for pid, doc in inp.docs.items()
        if doc and "verdict_if_placebo_read_literally" in doc
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- section 5


@dataclass(frozen=True)
class Exploratory:
    what: str
    pair_id: str
    path: tuple[str, ...]  # into the pair's `details`
    unit: str
    overnight: bool = False


EXPLORATORY = {
    "fed_SPY_sum": Exploratory(
        "SPY on the Fed odds, same model as the primary",
        "fed_decision",
        ("secondary", "SPY", "tests", "sum"),
        "bp per bp",
    ),
    "fed_XLF-SPY_sum": Exploratory(
        "Banks minus the S&P 500 on the Fed odds, same model as the primary",
        "fed_decision",
        ("secondary", "XLF-SPY", "tests", "sum"),
        "bp per bp",
    ),
    "fed_overnight_TLT": Exploratory(
        "TLT opening gap on the overnight change in the Fed odds",
        "fed_decision",
        ("overnight_TLT",),
        "bp per bp",
        overnight=True,
    ),
    "btc_COIN_lag1": Exploratory(
        "Coinbase on the odds one bar earlier, adjusted for Bitcoin's price",
        "bitcoin_monthly_ladder",
        ("exploratory", "COIN", "tests", "lag1"),
        "bp per 1%",
    ),
    "btc_MSTR_lag1": Exploratory(
        "MicroStrategy on the odds one bar earlier, adjusted for Bitcoin's price",
        "bitcoin_monthly_ladder",
        ("exploratory", "MSTR", "tests", "lag1"),
        "bp per 1%",
    ),
    "btc_IBIT_lag2": Exploratory(
        "Bitcoin ETF on the odds two bars earlier, adjusted for Bitcoin's price",
        "bitcoin_monthly_ladder",
        ("exploratory", "IBIT_lags1to3", "tests", "lag2"),
        "bp per 1%",
    ),
    "btc_IBIT_lag3": Exploratory(
        "Bitcoin ETF on the odds three bars earlier, adjusted for Bitcoin's price",
        "bitcoin_monthly_ladder",
        ("exploratory", "IBIT_lags1to3", "tests", "lag3"),
        "bp per 1%",
    ),
    "btc_IBIT_no_control": Exploratory(
        "Bitcoin ETF on the odds one bar earlier, no price adjustment",
        "bitcoin_monthly_ladder",
        ("no_control", "tests", "lag1"),
        "bp per 1%",
    ),
    "btc_overnight_IBIT": Exploratory(
        "Bitcoin ETF opening gap on the overnight change in the odds",
        "bitcoin_monthly_ladder",
        ("overnight_IBIT",),
        "bp per 1%",
        overnight=True,
    ),
    "btc_overnight_IBIT_spot_control": Exploratory(
        "Bitcoin ETF opening gap on the overnight odds change, adjusted for Bitcoin's price",
        "bitcoin_monthly_ladder",
        ("overnight_IBIT_spot_control",),
        "bp per 1%",
        overnight=True,
    ),
    "cpi_QQQ_spearman": Exploratory(
        "QQQ (Nasdaq) opening gap on the pre-release inflation odds move (Spearman)",
        "us_cpi_inflation",
        ("qqq_exploratory",),
        "rho",
    ),
}

BIASED = "biased (A29), not read as evidence"
MOVES_WITH = "moves with (same night, not a timing result)"


def exploratory_reading(row: dict[str, Any], q: str) -> str:
    """How an exploratory row reads. Never a timing word for an overnight test."""
    spec = EXPLORATORY.get(row["test"])
    if row.get("note"):
        return BIASED
    if not row["reject"]:
        return f"no link at q = {q}"
    if spec is not None and spec.overnight:
        return MOVES_WITH
    return f"link at q = {q} (exploratory)"


def _effect(inp: Inputs, spec: Exploratory | None) -> str:
    if spec is None:
        return "n/a"
    doc = inp.docs.get(spec.pair_id) or {}
    t = _get(doc.get("details"), *spec.path)
    if not isinstance(t, dict):
        return "n/a"
    ci = _ci(t, _level(doc))
    if spec.unit == "rho":
        return f"rho = {num(t.get('rho'))} ({ci})"
    return f"{num(t.get('estimate'))} {spec.unit} ({ci})"


def exploratory(inp: Inputs, blocks: dict[str, str]) -> str:
    rows = inp.summary.get("exploratory_family") or []
    q = num(inp.summary.get("q"))
    out = [blocks["exploratory"], ""]
    if not rows:
        return "\n".join([*out, "No exploratory tests in the results."])
    out += [
        "| Test | What it measures | Effect | p (two-sided) | BH-adjusted p | Reading |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        spec = EXPLORATORY.get(r["test"])
        out.append(
            f"| `{r['test']}` | {_cell(spec.what if spec else r['test'])} | "
            f"{_cell(_effect(inp, spec))} | {num(r['p_two_sided'])} | {num(r['bh_adjusted'])} | "
            f"{exploratory_reading(r, q)} |"
        )
    return "\n".join(out)


# ---------------------------------------------------------------- the document


def render(inp: Inputs, source: str | None = None) -> str:
    """The whole report as markdown (LF line ends, one trailing newline)."""
    blocks = template_blocks(
        TEMPLATE_PATH.read_text(encoding="utf-8") if source is None else source
    )
    pairs = [pair_section(inp, s.pair_id, blocks) for s in inp.specs]
    commit = inp.summary.get("code_commit") or "not recorded"
    parts = [
        blocks["title"],
        blocks["answer"],
        f"**{text.headline(inp.parsed)}.**\n\nTally: {text.tally(inp.parsed)}.",
        blocks["answer_note"],
        blocks["pairs"],
        *pairs,
        does_not_show(inp, blocks),
        amendments(inp, blocks),
        exploratory(inp, blocks),
        blocks["reproduce"],
        f"- Results fingerprint (sha256 over the results files): `{inp.fingerprint}`\n"
        f"- Analysis code commit recorded by the run: `{commit}`",
    ]
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def write_report(clean_dir: Path, specs: tuple[PairSpec, ...], out: Path = FINDINGS_PATH) -> Path:
    write_text_atomic(render(load_inputs(clean_dir, specs)), out, newline="\n")
    return out

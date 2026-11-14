"""The election findings report (`docs/studies/election/findings.md`), generated from the published
bundle. Pure rendering: every number is read from `results.json` through `report_text`, the same
functions the Streamlit page uses, so the two cannot disagree.

The prose lives in `findings_template.txt`, which holds no digits except section numbers and
hypothesis ids (tested). Rendering is deterministic: the same results file gives a byte-identical
report (no clock, no chart series).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from poly_actor.config import ROOT
from poly_actor.core.io import write_text_atomic
from poly_actor.studies.election import report_text as text
from poly_actor.studies.election.report_load import RESULTS_FILE, load_bundle

TEMPLATE_PATH = Path(__file__).with_name("findings_template.txt")
FINDINGS_PATH = ROOT / "docs" / "studies" / "election" / "findings.md"

_SLOT = re.compile(r"\{\{(\w+)\}\}")


class ReportInputError(ValueError):
    """The bundle is missing or unreadable; the message names the folder."""


def fingerprint(results_path: Path) -> str:
    """Short SHA-256 of the results file, so a reader can tell which bundle a report is from."""
    return hashlib.sha256(results_path.read_bytes()).hexdigest()[:12]


def table(rows: list[dict[str, str]]) -> str:
    """A Markdown table from display rows (keys are the headers)."""
    if not rows:
        return text.MISSING.capitalize() + "."
    head = list(rows[0])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(r.get(h, "")) for h in head) + " |" for r in rows]
    return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _beta_rows(res: text.Results, rows: list[tuple[str, object]]) -> list[dict[str, str]]:
    out = []
    for label, r in rows:
        out.append(
            {
                "Basket": label,
                "Estimate per +10 points": text.pct(text.get(r, "b10_pct")),
                "90% range": text.span(text.get(r, "ci10_pct")),
                "Permutation p": text.pval(text.get(r, "p_perm")),
                "Detectable from": text.pct(text.get(r, "mde10_pct"), signed=False),
            }
        )
    return out


def _cards(res: text.Results) -> str:
    rows = [
        {
            "": f"{c.key}: {c.question}",
            "Verdict": f"**{c.verdict}**",
            "Confidence": f"{c.confidence.word}. {c.confidence.reason}",
            "Finding": c.finding,
        }
        for c in text.cards(res)
    ]
    return table(rows)


def _checklists(res: text.Results) -> str:
    lines = []
    for key in ("H1", "H2"):
        for plain, technical in text.checklist_lines(res, key):
            lines.append(f"- {key}. {plain} ({technical})")
    return "\n".join(lines) if lines else text.MISSING.capitalize() + "."


def _exploratory(cts: dict[str, text.ChartText]) -> str:
    parts = []
    for key in ("e2_moves", "e2_term", "e1", "e3", "e5"):
        ct = cts[key]
        if ct.missing:
            parts.append(f"### {ct.kicker}\n\n{text.MISSING.capitalize()}.")
            continue
        parts.append(
            f"### {ct.kicker}\n\n**{ct.title}.**\n\n{ct.so_what}\n\nFor experts: {ct.expert}"
        )
    return "\n\n".join(parts)


def _methods(res: text.Results) -> str:
    return "\n\n".join(
        f"### {heading}\n\n{_bullets(items)}" for heading, items in text.methods(res)
    )


def slots(res: text.Results, results_fingerprint: str) -> dict[str, str]:
    """Every template slot, filled from the results."""
    cts = text.chart_texts(res, {})
    h1, subs = text.get(res, "h1") or {}, text.get(res, "h5", "subs") or {}
    h3 = cts["h3_lags"]
    return {
        "fingerprint": f"`{results_fingerprint}`",
        "data_line": text.data_line(res),
        "headline": text.headline(res),
        "headline_technical": text.headline_technical(res),
        "question": text.QUESTION,
        "why": text.WHY_IT_MATTERS,
        "cards": _cards(res),
        "checklists": _checklists(res),
        "meaning": _bullets([f"**{lead}** {body}" for lead, body in text.what_it_means(res)]),
        "h1_title": cts["h1"].title,
        "h1_so_what": cts["h1"].so_what,
        "mde": text.mde_plain(res),
        "h1_table": table(
            _beta_rows(res, [(text.BASKET_LABELS[k], h1.get(k)) for k in text.BASKET_LABELS])
        ),
        "h1_expert": cts["h1"].expert,
        "robustness_note": text.robustness_note(res),
        "robustness_table": table(text.robustness_table(res)),
        "h5_title": cts["h5"].title,
        "h5_so_what": cts["h5"].so_what,
        "h5_table": table(
            _beta_rows(res, [(label, subs.get(k)) for k, label in text.SUB_LABELS.items()])
        ),
        "h5_expert": cts["h5"].expert,
        "h2_title": cts["h2"].title,
        "h2_so_what": cts["h2"].so_what,
        "h2_note": text.h2_exploratory_note(res) or "",
        "h2_expert": cts["h2"].expert,
        "h2b_title": cts["h2b"].title,
        "h2b_so_what": cts["h2b"].so_what,
        "h2b_expert": cts["h2b"].expert,
        "h2_windows": table(text.h2_windows_table(res)),
        "h3_label": text.H3_LABEL,
        "h3_title": h3.title,
        "h3_so_what": h3.so_what,
        "h3_expert": f"{cts['h3_night'].expert} {h3.expert}".strip(),
        "h4_title": cts["h4"].title,
        "h4_so_what": cts["h4"].so_what,
        "h4_expert": cts["h4"].expert,
        "exploratory": _exploratory(cts),
        "methods": _methods(res),
        "does_not_show": _bullets(text.does_not_show(res)),
        "disclosure": text.DISCLOSURE + "\n\n" + _bullets(text.amendments(res)),
        "footer": text.FOOTER,
    }


def fill(source: str, values: dict[str, str]) -> str:
    """Replace every ``{{slot}}``; an unknown slot is an error, not a silent blank."""

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"template slot {{{{{name}}}}} has no value")
        return values[name]

    out = _SLOT.sub(sub, source)
    return re.sub(r"\n{3,}", "\n\n", out).rstrip("\n") + "\n"


def render(res: text.Results, results_fingerprint: str, source: str | None = None) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8") if source is None else source
    return fill(template, slots(res, results_fingerprint))


def write_report(bundle_folder: Path, out: Path | None = None) -> Path:
    """Render the bundle in ``bundle_folder`` to ``out`` (default `FINDINGS_PATH`; atomic, LF)."""
    bundle = load_bundle(bundle_folder)
    if bundle is None:
        raise ReportInputError(f"no readable {RESULTS_FILE} in {bundle_folder}")
    md = render(bundle.results, fingerprint(bundle_folder / RESULTS_FILE))
    out = FINDINGS_PATH if out is None else out
    write_text_atomic(md, out, newline="\n")
    return out

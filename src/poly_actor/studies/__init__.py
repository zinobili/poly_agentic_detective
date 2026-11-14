"""Registry of studies. Each study is a self-contained package under `poly_actor.studies`.

A study owns its question, pre-registration, data panels, analysis, findings and presentation.
Shared plumbing (data clients, time grid, statistics, storage, UI style) lives in
`poly_actor.core`. Rules, enforced by `tests/core/test_architecture.py`:

- `core` never imports from `studies`;
- a study never imports from another study;
- every study is registered here and has `docs/studies/<id>/`, `config/<id>/` and `tests/<id>/`.

How to add a study: `docs/studies/README.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from poly_actor.config import ROOT


@dataclass(frozen=True)
class Study:
    """Where one study's pieces live. Paths are relative to the repository root."""

    id: str  # package name under poly_actor.studies, and the folder name everywhere else
    title: str
    question: str
    status: str  # "done" | "in progress"
    cli: str  # `python -m <cli> --help` lists the study's commands
    app: str  # Streamlit page
    preregistration: str
    findings: str

    @property
    def docs_dir(self) -> str:
        return f"docs/studies/{self.id}"


STUDIES: tuple[Study, ...] = (
    Study(
        id="leadlag",
        title="Polymarket odds vs related stocks",
        question="Do Polymarket odds lead, lag, or move with related stocks?",
        status="done",
        cli="poly_actor.studies.leadlag.refresh",
        app="src/poly_actor/studies/leadlag/dashboard/app.py",
        preregistration="docs/studies/leadlag/preregistration.md",
        findings="docs/studies/leadlag/findings.md",
    ),
    Study(
        id="election",
        title="The partisan beta of AI (2026 US midterm)",
        question=(
            "Did AI stocks move with the odds that Democrats take Congress, beyond the broad "
            "market, and did pre-election sensitivities predict election night?"
        ),
        status="done",
        cli="poly_actor.studies.election",
        app="src/poly_actor/studies/election/app.py",
        preregistration="docs/studies/election/preregistration.md",
        findings="docs/studies/election/findings.md",
    ),
)


def get(study_id: str) -> Study:
    """The registered study with this id; a clear error names the known ids."""
    for s in STUDIES:
        if s.id == study_id:
            return s
    raise KeyError(f"unknown study {study_id!r}; known: {', '.join(s.id for s in STUDIES)}")


def describe() -> str:
    """A plain-text listing of every study and how to run it."""
    blocks = []
    for s in STUDIES:
        blocks.append(
            f"{s.id}  [{s.status}]  {s.title}\n"
            f"  question: {s.question}\n"
            f"  commands: python -m {s.cli} --help\n"
            f"  page:     streamlit run {s.app}\n"
            f"  findings: {s.findings}"
        )
    return "\n\n".join(blocks)


__all__ = ["ROOT", "STUDIES", "Study", "describe", "get"]

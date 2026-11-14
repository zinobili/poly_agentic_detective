"""The repository layout that lets several studies share one toolkit (see poly_actor.studies)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from poly_actor import studies

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "poly_actor"


def _imports(path: Path) -> set[str]:
    """Every absolute module name imported anywhere in the file (including inside functions)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def _study_packages() -> list[str]:
    return sorted(p.name for p in (PKG / "studies").iterdir() if (p / "__init__.py").is_file())


def test_core_never_imports_a_study():
    offenders = {
        str(f.relative_to(ROOT)): sorted(m for m in _imports(f) if ".studies" in m)
        for f in (PKG / "core").rglob("*.py")
    }
    assert {k: v for k, v in offenders.items() if v} == {}


@pytest.mark.parametrize("study_id", _study_packages())
def test_a_study_never_imports_another_study(study_id):
    others = [s for s in _study_packages() if s != study_id]
    offenders = {}
    for f in (PKG / "studies" / study_id).rglob("*.py"):
        bad = sorted(
            m for m in _imports(f) if any(m.startswith(f"poly_actor.studies.{o}") for o in others)
        )
        if bad:
            offenders[str(f.relative_to(ROOT))] = bad
    assert offenders == {}


def test_every_study_package_is_registered_once():
    ids = [s.id for s in studies.STUDIES]
    assert sorted(ids) == _study_packages() and len(set(ids)) == len(ids)


@pytest.mark.parametrize("study", studies.STUDIES, ids=lambda s: s.id)
def test_a_registered_study_has_its_standard_places(study):
    assert (ROOT / study.app).is_file()
    assert (ROOT / study.preregistration).is_file()
    assert (ROOT / study.findings).is_file()
    assert (ROOT / study.docs_dir / "README.md").is_file()
    assert any((ROOT / "config" / study.id).iterdir())
    assert any((ROOT / "tests" / study.id).glob("test_*.py"))
    cli = PKG.parent / Path(*study.cli.split("."))
    assert cli.with_suffix(".py").is_file() or (cli / "__main__.py").is_file()


def test_get_names_the_known_ids_on_a_typo():
    assert studies.get("election").id == "election"
    with pytest.raises(KeyError, match="leadlag"):
        studies.get("elections")


def test_describe_lists_every_study():
    text = studies.describe()
    assert all(s.id in text and s.app in text for s in studies.STUDIES)

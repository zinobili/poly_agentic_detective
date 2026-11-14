# Restructure validation r2 (a4e349b..a5bdf86)

Verdict: PASS

## Checked
1. Major closed. `config/leadlag/pairs.yaml` at a5bdf86 is byte-identical to `259fa35:config/pairs.yaml` (cmp). AST comparison of non-docstring string constants of all 11 `pairs_build/*.py` modules vs 259fa35 gives identical sets for every module. `scripts/build_pairs.py:56` writes `config/leadlag/pairs.yaml`; `emit.py:40` dump options (SafeDumper, sort_keys=False, allow_unicode, width=110) unchanged.
2. Shim removals: diff of the listed files shows only import changes (core.io/core.timeutil direct, `results.jsonable` -> `io.jsonable`, import reordering), plus the emitted-string restoration. No logic change.
3. Architecture test resolves relative imports. In a temp copy: `from ..election import config` in leadlag/pairs.py fails `test_a_study_never_imports_another_study[leadlag]`. `from ...studies.leadlag import pairs` in core/ingest/__init__.py fails `test_core_never_imports_a_study`; `from ..studies.leadlag import pairs` in core/io.py also fails. Note: `...studies` placed in core/io.py (depth-1 module) goes above the top-level package, so it is not a valid import and is not flagged; that is a mutation-choice issue, not a test gap.
4. `git diff a4e349b a5bdf86 -- reports docs/studies/election/findings.md` is empty; tests/election/test_election_report.py passes.
5. Per-file test counts at a4e349b equal a5bdf86 (33 files); def test_ names at a4e349b are a subset of a5bdf86 (one added: relative-import test).

## Issues
Blocker/major: none. Minor: none.

## Not checked
Full rebuild of pairs.yaml from the cache (inferred via byte equality plus string-constant equality); full test suite (relied on caller's check.sh).

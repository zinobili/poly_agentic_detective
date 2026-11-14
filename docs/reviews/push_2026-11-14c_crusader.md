# Pre-push review a4e349b (study restructure) - Clean Code Crusader

**Verdict: SHIP WITH FIXES** (no blockers, no majors; the fixes are small and can follow the push).
ruff: clean. Scope: structure only (behaviour is the validator's job).

Scores: design 4.5, readability 4.5, types 4, error handling n/a, tests 4, config 4, security n/a, perf n/a, consistency 4, docs 4.5.

## Blockers / majors
None.

## Minors
1. **Re-export shims remain** (`# noqa: F401 (re-exported)`): `studies/leadlag/pairs.py:17` (ET, et_to_utc, et_to_utc_dt from core.timeutil; used by `pairs_build/*` and `tests/leadlag/test_build_pairs.py`), `studies/leadlag/analysis/results.py:13` (jsonable, write_text_atomic), `studies/leadlag/align/consts.py:5` (core.timegrid.consts). Fix: import from `poly_actor.core.timeutil`, `core.io`, `core.timegrid.consts` directly and delete the shims. They hide where the code now lives, which is what this restructure is meant to make obvious. (`dashboard/text.py:13` re-export is an older, intra-study pattern; leave.)
2. **`core/ui/style.py:19-33` is partly study-specific.** `.st-key-pair_nav` and `NAV_COLORS` style the lead-lag pair bar. Generic page CSS belongs in core; move the pair-nav rule to `studies/leadlag/dashboard` and let it append to `page_css`.
3. **`core/store/raw_views.py` is lead-lag-shaped.** It hard-codes the top-level `data/raw/{polymarket,stocks}` layout (which the docs say only lead-lag uses), the `ohlc_all_nan` column, and a "step 4" docstring. Only lead-lag imports it. Either move it to `studies/leadlag/` or document it as layout-v1 and have new studies not use it. The Windows `chr(92)` path hack and the two long `noqa: E501` column strings could also become small constants/helper.
4. **Architecture test gaps** (`tests/core/test_architecture.py`): `_imports` ignores relative imports (`level > 0`), so `from ..election import x` inside a study, or `from ..studies` in core, passes. Add: for `level > 0` resolve against the file's package, or ruff `flake8-tidy-imports` `banned-api`/`TID252` (ban relative parent imports). Also `".studies" in m` is a substring test; use `m.startswith("poly_actor.studies")`. No test pins that core has no Streamlit-free requirement or that `data/` paths come from config; fine.
5. **Registry**: `studies/__init__.py:18,88` imports and exports `ROOT` unused. Drop it. `Study` stores five path strings that are all derivable from `id`; only `cli` and `app` differ between studies. Consider deriving docs/preregistration/findings from `docs_dir` to cut the chance of drift (the test already checks existence, so this is low risk).
6. **Docs/templates**: `docs/studies/README.md` is enough to add a study. Gaps: no template for `config/<id>/*.yaml` (rationale rule) or a `tests/<id>/` skeleton; step 4 says "a `__main__.py` or CLI module" but the registry `cli` field needs a runnable module path, say so; mention that `python -m poly_actor` output is generated from the registry; mention `package-data` entries in `pyproject.toml` for any `*.txt` template. `docs/README.md` old-to-new table is long but useful; fine as a one-time record.
7. **`pyproject.toml` package-data** lists two packages by hand; a new study with a findings template silently loses it on non-editable install. A note in the study README (see 6) is enough, or use a glob with `include-package-data`.
8. **CLAUDE.md** is accurate and not bloated (58 lines); step 3 still says "the pairs.yaml rebuild and the ingest dry run" without saying these are lead-lag-only. Say so, and have `check.sh` loop over studies when a third one needs a gate.
9. **Hygiene**: untracked leftover dirs `src/poly_actor/{ingest,store}/` (only `__pycache__`); delete locally. Empty `__init__.py` files are intentional (namespace markers) and fine. `.claude/launch.json` has both Windows and Linux election entries; harmless.

## What is good
- Clean, enforceable boundary: `core` imports no study, studies import no sibling, tested by AST in `test_architecture.py`.
- Registry is a plain frozen dataclass plus two tiny functions; `python -m poly_actor` is 5 lines. Not over-engineered.
- Test-per-study layout with local `fixtures/` and synth helpers; `core/timegrid/bars.py` and `core/stats/shifts.py` correctly extracted because election needed them.
- Docs map and old-to-new path table make history readable; `.gitattributes`, CI, `check.sh`, `pyproject` and README commands were all updated consistently.
- Findings stay generated-not-typed per study.

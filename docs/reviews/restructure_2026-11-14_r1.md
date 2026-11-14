# Restructure a4e349b (parent 259fa35), validator round 1

## Verdict: PASS WITH ISSUES

No behaviour change found. One major: the regenerated-file check for `config/leadlag/pairs.yaml` will fail as soon as a Gamma cache exists.

## Checked (evidence)
1. No logic change in `src/`. I filtered every non-rename hunk, removing import, path and docstring lines, and read the rest.
   - `core/io.py`, `core/timeutil.py`, `core/stats/shifts.py` and `core/timegrid/consts.py` are byte-identical in body to the originals in `analysis/results.py`, `pairs.py`, `align/consts.py` and the two `admissible_shifts` copies.
   - The `placebo` and `election/stats` wrappers delegate to `shifts.admissible_shifts` with the same arguments.
   - `results.py` keeps `jsonable` and `write_text_atomic` as re-exports.
   - `SESSION_MIN_SHIFT = 5` equals `placebo.MIN_SHIFT = 5` at 259fa35 (line 34), and the call is unchanged.
   - `refresh.py` stage strings expand to the same module names. `PKG` is the only new thing there.
   - The rewrapped `_err(...)` and `argparse` calls only reflow lines. The removed `models` import was moved to `core.stats`.
2. Election results are identical.
   - `git diff 259fa35 a4e349b -- reports/election/` shows only the `meta.preregistration` string.
   - `python -m poly_actor.studies.election analyse` gave a `data/clean/election/results/results.json` that is `cmp`-identical to `reports/election/results.json`.
   - `report` leaves `git status` clean. The only untracked file is `docs/reviews/push_2026-11-14c_crusader.md`, which is not mine; I assume the code reviewer wrote it.
3. Tests.
   - File-qualified `def test_*` names match in both revisions, and 6 are added, all in `tests/core/test_architecture.py`. With parametrisation over 2 studies that makes 8 more tests (595 to 603).
   - The count of skip and xfail markers is 11 in both revisions.
   - The only non-import changes in existing tests are path strings, `parents[N]` depth and the `analysis_written` fixture. That fixture moved from `tests/conftest.py` to `tests/leadlag/conftest.py`, so it is no longer visible to election or core tests, and none use it.
4. Mutation test on a `git archive` copy.
   - Adding a leadlag import to `core/timeutil.py` fails `test_core_never_imports_a_study`.
   - Adding one to election `stats.py` fails `test_a_study_never_imports_another_study[election]`.
5. Entry points all work.
   - `python -m poly_actor` lists both studies.
   - `leadlag.refresh --dry-run` lists the 4 stages with the new module names.
   - `studies.election --help` works.
   - Both Streamlit apps served HTTP 200 and `/_stcore/health` 200 headless. `AppTest` showed no exception in either app. The lead-lag app shows "Analysis not run yet".
6. Docs.
   - All relative markdown links resolve, 0 broken in the whole repo, including the historical records.
   - A grep for the old names found no hits in `CLAUDE.md`, `README.md`, `.claude/*`, `scripts/*`, `ci.yml`, `.gitattributes` or `pyproject.toml`.
   - It also found no hits in `src/`, `config/` or `notebooks/`.
7. The `HEADER` and path strings in `emit.py` match the head of `config/leadlag/pairs.yaml` exactly. The `preregistration` field and the `poly_actor.studies.leadlag.pairs.*` strings in `btc.py` also match the file text. The line wrapping is a different matter; see M1.

## Issues

### M1 (major): `config/leadlag/pairs.yaml` was text-substituted but not rewrapped, so the rebuild will differ
- Locations: `config/leadlag/pairs.yaml`, the BTC `A20/A21 RUNG SELECTION` note and the following `monotone_ladder_crossing). Then take the FIRST crossing` note. The sources are `pairs_build/btc.py:314-316`.
- The two strings got longer (`poly_actor.pairs` became `poly_actor.studies.leadlag.pairs`). `yaml.dump(..., width=110)` in `emit.py` folds these scalars at different points than the committed file.
- Repro: load the file, run `yaml.dump(d, Dumper=SafeDumper, sort_keys=False, allow_unicode=True, width=110)`, then compare those two scalars with the file. Line breaks differ, for example the first line ends at "...if any dip rung" in the file and at "...is TOUCHED" in the dump.
- Effect: the 259fa35 body round-trips with the same pattern, but the new file adds exactly these two differences. `scripts/check.sh` "pairs.yaml rebuild" runs `git diff --quiet -- config/leadlag/pairs.yaml`, so it will report non-reproducible on a machine with the cache. It passed here only because there is no cache.
- Fix: on a machine with the cache, run `python scripts/build_pairs.py` and commit the result. The values are unchanged, so the diff should be line breaks only.

### Minors
- m1. `tests/election/fixtures/bundle/results.json:3314` still carries `docs/election/preregistration.md`. This is frozen fixture data, so it is harmless, but a grep for old paths will flag it.
- m2. `tests/core/test_architecture.py::_imports` ignores relative imports (`node.level == 0`), so `from ..leadlag import x` bypasses the rule.
- m3. `docs/reviews/push_2026-11-14c_crusader.md` is untracked (another agent's file). Make sure it is committed or removed on purpose.

## Not checked
- The pairs rebuild itself (no cache).
- The live tests.
- Rendering of the `.png` and HTML moves, and git rename fidelity of the 249 files beyond `-M` stats. I read only the `src/` and `tests/` hunks.
- The `ruff` run and the full `check.sh` re-run (the caller reported it passed).

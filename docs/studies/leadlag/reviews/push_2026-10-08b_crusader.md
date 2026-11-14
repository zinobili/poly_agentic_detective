# Pre-push review: step 7 (findings generator, refresh CLI)

Scope: `git diff origin/master..master`. Ruff clean. Full test suite not run (per brief).

**Verdict: SHIP WITH FIXES** (no blockers; 2 majors, both small)

Scores: design 4, readability 4, types 3, errors 3, tests 4, config 4, security 5, performance 5, consistency 4, docs 4.

## Major
1. `src/poly_actor/analysis/findings.py:497-502` `write_report` writes `docs/findings.md` in place. A crash mid-write leaves a truncated published report. Fix: write `out.with_suffix(".md.tmp")` then `os.replace` (repo standard for safe writes).
2. `src/poly_actor/analysis/findings.py:48-52` with `run.py` `cmd_report` (~line 390): `_read_json` lets `json.JSONDecodeError` (a truncated or corrupt results file) escape as a traceback, while only `FileNotFoundError` is turned into a clean exit 2. In `refresh` this is caught by the generic handler, but standalone `report` is loud only by accident. Fix: catch `(FileNotFoundError, json.JSONDecodeError)` in `cmd_report`, or wrap in `_read_json` with the path in the message. Also, `parse_results(d)` failures carry no pair id.

## Minor
1. `findings.py:55,100,109,118,126,211,222,266,304,450` public functions lack docstrings (units and meaning of `num` sig digits, `fingerprint` ordering). `fingerprint` should say it covers all `*.json` in the folder including `summary.json`.
2. `findings.py:154-157` redundant parentheses and a ternary where `if` is clearer: `("Primary effect")`.
3. `findings.py:17,41-44` `Any` and loose `dict[str, Any]` throughout. A TypedDict for the results doc already exists in `contract` (`ResultsDoc`); reuse it for `Inputs.docs` where practical.
4. `findings.py:237-239,279-280` direct `doc["verdict_reason"]` and `doc["a29_note"]` indexing raises a bare KeyError on a malformed doc; use `.get` or a clear error.
5. `findings.py:106` `10**sig` threshold and `sig=3` are unnamed; name `SIG_DIGITS = 3`.
6. `findings.py:349-419` the EXPLORATORY registry is duplicated knowledge of the test ids in `run.py` (`A29_EXPLORATORY`); a unit test should assert every exploratory id in `summary.json` has a spec (the `n/a` fallback currently hides drift silently).
7. `run.py` `code_version`: untested (clean, dirty, no-git paths). Inject the git runner or add three small tests with monkeypatched `subprocess.run`. Also the `-dirty` check ignores untracked/`tests/` changes, which is fine but belongs in the docstring (it is, partly).
8. `run.py` `cmd_report`: `print(..., file=sys.stderr)` while the rest of the module logs; acceptable for CLI results, but use `log.error` for consistency.
9. `refresh.py:55` `except Exception` logs with traceback and returns 1; acceptable (loud, bounded), but `SystemExit(None)` maps to 0 correctly; add a test for `SystemExit(0)` if not present.
10. `refresh.py:68` `enumerate(plan, 1)` magic start; use `start=1` keyword for clarity. `refresh.py:79` the success message for a dry run is printed through `say` after the loop; fine.
11. `tests/conftest.py:30-40` the 40 s session fixture imports inside the function; ok for the sys.path trick, but add a comment saying why.
12. `test_findings.py:266` real-results test depends on local, git-ignored data; it skips in CI. Fine, but note it is not a regression gate.
13. `docs/findings.md` is a tracked generated file (190 lines, small; `.gitattributes` pins LF). Acceptable; mention in README that it is generated (README appears to).

## Good
- Clean split: pure `render(inp, source)` with thin `write_report`; template with no digits, enforced by tests, plus a tracer that fails on invented numbers.
- Headline reuses the dashboard function, so the two surfaces cannot disagree.
- Deterministic, byte-identical regeneration tested; missing-slot is an error, not left in the text.
- `refresh` injects runner and printer, so it is fully testable offline; dry run imports nothing; failure names the stage and stops.
- `code_version` uses an argv list with a timeout and no shell; `package-data` entry makes the template ship.
- A29 changes in `results.py` are simplified (the per-ticker special case removed) and tested.

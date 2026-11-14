# Crusader review: push 2026-10-05 (step 4 alignment), round 1

Scope: `git diff origin/master..master` (src/poly_actor/align, ingest/targets.py, pairs.py, tests, docs).
check.sh: pytest 284 passed, ruff check ok, **ruff format FAIL**, pairs rebuild reproducible, dry-run ok.

**Verdict: SHIP WITH FIXES.** No blockers. One major is a mechanical fix that turns check.sh green.

## Scores (1-5)
Design 4, Readability 4, Types 3, Error handling 4, Tests 5, Config/constants 4, Security 5, Performance 4, Consistency 3, Docs/hygiene 3.

## Major
1. **check.sh fails on ruff format.** `docs/reviews/step4_r2.md:77` (python code block) is unformatted (single quotes, long line). Fix: `ruff format docs/reviews/step4_r2.md` (or reformat the snippet), then re-run check.sh. Pushing with a red gate defeats the gate.

## Minor
1. `align/pipeline.py:~100` `next(p for p in cfg["pairs"] if p["id"] == pair_id)` raises bare StopIteration for an unknown id when called outside the CLI. Raise `KeyError(f"unknown pair {pair_id!r}")` (or ValueError) with context.
2. `align/cli.py:34,44,48,73,75` use `print` for status and errors; the repo uses `logging` elsewhere. Errors (unknown pair, no panels) should go to stderr/log. Report output via print is fine.
3. `align/cli.py:42,44` `time.time()` for elapsed time; use `time.perf_counter()`.
4. `align/cli.py:28,66` `cmd_run`/`cmd_report` have no docstrings; `summaries: dict[str, dict]` and `-> dict` are loose. A TypedDict or `dict[str, Any]` alias for the summary record would document its fields (also `load_config -> dict`, `diag` dicts in pipeline.py).
5. `align/cli.py` `_read_summary` then `_write_summary` is an unlocked read-modify-write; two concurrent `run` processes (e.g. strict plus normal) can drop each other's keys. Document "run one at a time" or merge under a lock. Also a corrupt summary JSON raises with no path in the message; wrap with context.
6. `align/pipeline.py` `build_pair_inputs` is ~65 lines (over the guideline). Extract the stock-restamp loop and the `diag` assembly into helpers.
7. `align/pipeline.py:event_tokens` mixes four event-family shapes inline; a method `Event.tokens()` would keep family knowledge with the Event type.
8. `align/pipeline.py:~118` `rows = rows[rows["end_s"] <= max(s["end_s"].max() ...)]` crashes with an unclear ValueError if `stamped` is empty (pair with only spot tickers). Guard with an explicit error.
9. `ingest/targets.py:30` comment on `FID_DENSE` says "for the fed and BTC-ladder tokens" but it now covers CPI and recession too; the module docstring already says so. Fix the comment.
10. `ingest/targets.py` module docstring line "Amendment A25 ..." exceeds the 100-col style used elsewhere only slightly; fine, but the `_plan_*` duplication of `(FID_LIFE, FID_DENSE)` loops is repeated in four places. A `_add_life(plan, pid, tok, start, end, covered)` helper removes it.
11. `pairs.py` Ladder Literal is a good tightening; `pairs_build/cpi.py` change not reviewed beyond diff size (6 lines), looks fine.
12. Stray `__pycache__` appears in grep output; confirm `.gitignore` covers it (it is not tracked per diff stat).

## Good
- Pure logic (grid, prices, splice, signals, evaluate) cleanly separated from the I/O wrapper (`pipeline.py`, `cli.py`); named constants in `consts.py` with units.
- Atomic writes (temp + `os.replace`) for panels and summary; parametrised SQL (`list_contains(?, ...)`), no shell, no eval, no asserts, no bare excepts.
- Test suite is large, offline, deterministic, with guard tests tied to the lessons (A22/A25 tolerance, DST, early closes).
- Dated amendment comments explain why, not what.

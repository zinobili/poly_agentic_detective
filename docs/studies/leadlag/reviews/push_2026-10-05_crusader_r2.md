# Pre-push review: step 5 (align cleanup + dashboard), r2

Scope: `git diff origin/master..master`. `scripts/check.sh`: PASS (343 tests, ruff clean, pairs reproducible).

**Verdict: SHIP WITH FIXES** (1 major, doc only; fix, then push). No blockers.

## Scores (1-5)
Design 5, Readability 4, Types 4, Error handling 4, Tests 4, Config 4, Security 5, Performance 4, Consistency 4, Docs 3.

## Major
1. **CLAUDE.md:15 is stale and contradicts the code.** The "No look-ahead" hard rule still documents the A22 exception (`PM_STAMP_TOLERANCE_S`, `pm_used_tolerance`, step 6 strict run). This diff removes all three (prereg A26: "no look-ahead has no exceptions"). CLAUDE.md is the first file every agent reads, so a stale exception invites someone to re-add the tolerance. Fix: replace the exception sentence with "No exceptions (A22 retired by A26, 2026-10-05)."

## Minor
1. `README.md`: no instructions for running the dashboard (`pip install -e ".[dashboard]"`, `streamlit run src/poly_actor/dashboard/app.py`, `POLY_ACTOR_CLEAN_DIR`).
2. `pyproject.toml`: `streamlit` is pinned identically in `dashboard` and `dev`. Use one source, e.g. `dev = ["poly_actor[dashboard]", ...]`.
3. `dashboard/load.py:51` `load_panel`: a corrupt parquet raises a raw pyarrow error inside the Streamlit render. Catch it, log it with the path, and return None, as `load_results` does.
4. `dashboard/load.py:55` `load_all_results` has no docstring. `contract.results_path` has none either. `load.py` PairSpec and Coverage fields lack units (seconds for `median_quote_age_s`).
5. `dashboard/app.py:233`: `load_all_results` re-reads every JSON on each rerun (every widget click). It is small, but cache it by file mtime or a TTL.
6. `dashboard/app.py:124-150` and 160-200: chart helpers repeat the "How to read / So what" literal strings. `_chart_card` (line 148) is defined but unused, so it is dead code. Use it or delete it.
7. `app.py:197` `main()` is invoked at module level. That is normal for Streamlit, but it means the module cannot be imported in tests without side effects. The tests already work around this; a `if __name__`-style guard is not possible, so document it.
8. `align/cli.py:27` `_summary_lock`: a stale lock after a crash blocks runs for 30 s and then raises TimeoutError. The message says to remove the lock, which is acceptable. `time.sleep` is untested; inject the sleep or add a test with a short timeout.
9. `align/cli.py:57` the `summaries: dict[str, dict]` annotations are loose. A TypedDict would be better. `print` is used for CLI output, which is consistent with the rest of the repo.
10. `text.py` is 473 lines of wording. It is pure and well tested, but consider moving the static strings into a data module if it keeps growing.

## Good
- Clean separation: `contract.py` (pure parse), `load.py` (I/O), `charts.py`, `text.py`, and `app.py` (layout only).
- The results contract validates each slot independently and logs the bad ones. It never invents numbers, rejects NaN/inf and bool-as-int, and has frozen dataclasses with full type hints.
- Safe YAML loader, `html.escape` before every `unsafe_allow_html`, and the server bound to localhost.
- Atomic summary writes, plus a lock whose timeout is bounded.
- Tests are offline, use a small committed fixture (23 KB), and cover the failure paths. The tolerance tests were replaced by "never use a point stamped after the instant".


## Main's triage (2026-10-06)
- Major (CLAUDE.md:15 still documents A22): **false positive.** CLAUDE.md already reads "No exceptions (A22 retired by A26)" since f08a0c4.
- Fixed: README run instructions; dead `_chart_card` removed.
- Remaining minors carried to docs/handoff/step6.md.

# Milestone 2 backlog (carried from milestone 1)

## From step 7 (docs/reviews/step7_r1.md)
- `tests/test_findings.py` `untraced_numbers`: a number passes if it matches any value in any results file, including 1-significant-figure rounding. Tighten to per-pair, per-field tracing.
- Findings section 6 fingerprints results JSON that lives in git-ignored `data/clean`; a public reader can't verify without re-running. Consider publishing the results JSON (or a hash manifest) with each release.
- Validator could not run source mutations (read-only); a builder should mutation-test the rules-as-examples tests.
- Not yet verified: a live (non-dry-run) `python -m poly_actor.refresh`, and that results reproduce from raw data end to end.

## From step 6/7 (research)
- BTC: re-specify the spot control with bar-aligned sub-hour spot data (each bar's own start and end), as a new pre-registered test.
- CPI Chart 2 signing window (all 20 releases unsigned; missing vs tiny moves not split).
- More CPI releases and recession episodes are needed before those pairs can be answered.

## From the step 7 pre-push review (docs/reviews/push_2026-10-08b_crusader.md; majors fixed in ad40399)
- 13 minors, e.g. docstrings on public functions in `analysis/findings.py`; `Any`/loose dicts where `ResultsDoc` exists; bare `KeyError` on `doc["verdict_reason"]`/`doc["a29_note"]`; unnamed `sig=3`; no test that every exploratory id in `summary.json` has an `EXPLORATORY` spec; `code_version` untested; `cmd_report` prints instead of logging.

## From the 2026-10-21 pre-push review (docs/reviews/push_2026-10-21_crusader.md)
- `pyproject.toml` pins `streamlit>=1.40` but `dashboard/app.py` uses `st.context.theme` (newer); raise the floor.
- `dashboard/style.py` builds CSS with `%` formatting; a literal `%` in the CSS would raise. Use token replace or note it.
- Dashboard test covers `page_css` but not the `main()` theme wiring.

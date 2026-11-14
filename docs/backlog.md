# Milestone 2 backlog (carried from milestone 1)

## From step 7 (docs/studies/leadlag/reviews/step7_r1.md)
- `tests/test_findings.py` `untraced_numbers`: a number passes if it matches any value in any results file, including 1-significant-figure rounding. Tighten to per-pair, per-field tracing.
- Findings section 6 fingerprints results JSON that lives in git-ignored `data/clean`; a public reader can't verify without re-running. Consider publishing the results JSON (or a hash manifest) with each release.
- Validator could not run source mutations (read-only); a builder should mutation-test the rules-as-examples tests.
- Not yet verified: a live (non-dry-run) `python -m poly_actor.refresh`, and that results reproduce from raw data end to end.

## From step 6/7 (research)
- BTC: re-specify the spot control with bar-aligned sub-hour spot data (each bar's own start and end), as a new pre-registered test.
- CPI Chart 2 signing window (all 20 releases unsigned; missing vs tiny moves not split).
- More CPI releases and recession episodes are needed before those pairs can be answered.

## From the step 7 pre-push review (docs/studies/leadlag/reviews/push_2026-10-08b_crusader.md; majors fixed in ad40399)
- 13 minors, e.g. docstrings on public functions in `analysis/findings.py`; `Any`/loose dicts where `ResultsDoc` exists; bare `KeyError` on `doc["verdict_reason"]`/`doc["a29_note"]`; unnamed `sig=3`; no test that every exploratory id in `summary.json` has an `EXPLORATORY` spec; `code_version` untested; `cmd_report` prints instead of logging.

## From the 2026-10-21 pre-push review (docs/studies/leadlag/reviews/push_2026-10-21_crusader.md)
- `pyproject.toml` pins `streamlit>=1.40` but `dashboard/app.py` uses `st.context.theme` (newer); raise the floor.
- `dashboard/style.py` builds CSS with `%` formatting; a literal `%` in the CSS would raise. Use token replace or note it.
- Dashboard test covers `page_css` but not the `main()` theme wiring.

## Election study (milestone 2, steps 8-10): open minors, 2026-11-14
- Engineering (docs/studies/election/reviews/push_2026-11-13b/c_crusader.md, push_2026-11-14/14b_crusader.md): shared
  regression helper in the election analysis; split long functions and `report_text.py` (1,300+
  lines); typed result objects; atomic writes of clean parquet and coverage.json in `panel.py`;
  lazy `coverage` import; chart palette duplicated from `poly_actor.dashboard`; E1 title labels a
  zero shift "higher"; fixture-coupled literals in report tests; machine-specific `election-linux`
  launch entry.
- Research (docs/studies/election/reviews/step9_r1.md, step10_r2.md): noise tests use few seeds and 400 shifts; the
  A3 recomputed figures are not in the bundle, so the page describes them without numbers.
- Policy to decide: `reports/election/` tracks derived series built from Yahoo and Polymarket data
  (basket-level returns, odds, one night of index-futures % changes, vol ratios). No raw per-ticker
  history is tracked. If that is not acceptable for a public repo, move the bundle to `data/`.
- Ideas the results point to (all would need a fresh pre-registration): the late-sample shift in
  the rolling estimate; the sub-basket inequality (power/data-centre on the other side of zero);
  the -5.4% vs +0.9% election-window gap between AI and non-AI names; single-name option-implied
  moves (needs paid options history).

## Repo layout (restructure of 2026-11-14): open minors
- `core/ui/style.py` still carries the lead-lag sticky pair-bar CSS (`.st-key-pair_nav`, `NAV_COLORS`); move it into `studies/leadlag/dashboard` when a third app needs the shared style.
- `studies/leadlag/align/consts.py` re-exports the generic grid constants on purpose; switch its users to `core.timegrid.consts` if that module grows.
- No config/tests template under `docs/studies/_template/` yet (only the pre-registration and hand-off templates).
- Lead-lag data still sits at the top of `data/raw/` and `data/clean/`; moving it under `data/*/leadlag/` needs a local data move on the machine that holds it.

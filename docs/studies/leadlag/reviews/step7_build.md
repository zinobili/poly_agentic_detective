# Step 7 build report (write-up)

Date: 2026-10-08. Branch `step7-writeup`. Commits: `e1f236b` (code, tests, README, prereg addendum), `ecf9408` (generated `docs/findings.md`). Not pushed or merged.

`bash scripts/check.sh`: **PASS**. 474 tests pass (4 min 38 s), ruff check and format are clean, pairs.yaml reproduces, and the ingest dry run plans 106 calls.

## What was built
- **`python -m poly_actor.analysis report`** writes `docs/findings.md`. The renderer is `src/poly_actor/analysis/findings.py` and the prose is in `src/poly_actor/analysis/findings_template.txt`, as named blocks with `{{slots}}`. The template has no digits except amendment ids, and a test enforces that. The one-line answer is `dashboard.text.headline`, the same function the dashboard uses. The report has the 6 required sections plus the disclaimer.
  - The prose blocks in sections 3 and 4 are chosen by the verdicts. For example, a "Polymarket moves first" verdict replaces the "no pair shows a lead" bullet.
  - Output is deterministic and LF-only. Generating twice gives byte-identical files, checked by a test and on the real results.
- **`python -m poly_actor.refresh [--workers N] [--dry-run]`** runs ingest, then align, then analysis run, then report. Each stage calls its existing `main(argv)`. The first failure (a non-zero exit, an exception or a SystemExit) stops the refresh. The error message names the failed stage, and the refresh exits non-zero.
  - `--dry-run` prints the 4 stages and imports and runs none of them.
- **`analysis run`** now writes `code_commit` into `summary.json`, with "-dirty" appended if `src/` or `config/` has uncommitted changes. Section 6 of the findings shows that commit and a sha256 fingerprint of the results files.
- **README** now has a status table and a "Findings" section that links to `docs/findings.md` and gives no numbers. The run instructions cover refresh, dry run, the four separate stages, report and the dashboard.

## The results were re-run (36 s), and no numbers changed
I re-ran `analysis run --workers 4` after committing the code, so that the JSON carries the new notes. A structural diff against the old files shows these differences only:
- In the BTC results: `note` was added to all 4 BTC `event_study` entries and to `xcorr/XLU/residualised`.
- In `summary.json`: `code_commit = e1f236b` and the note on `btc_overnight_IBIT_spot_control` were added.

The Fed, CPI and recession files are byte-identical. All verdicts are unchanged.

## Headline (generated)
"So far no pair shows Polymarket odds moving ahead of stocks; 3 of 4 are still undecided or descriptive only."

| Pair | Verdict | Primary result |
|---|---|---|
| Fed | No head start (Low) | 1.75 bp/bp, 90% CI −5.68 to 9.18, BH p 0.524; upper bound r 0.0415, below the MDE |
| BTC | Too early to tell, A29 (Low) | The biased primary is shown only with a label |
| CPI | Too early to tell (Low) | rho −0.294, CI −0.70 to 0.256, n 12 |
| Recession | Descriptive only | One episode, no significance test |

## Rules-as-examples → tests
Tests are in `tests/test_findings.py` and `tests/test_refresh.py`.

| Row | Test |
|---|---|
| 1 | `test_headline_is_the_dashboard_headline` |
| 2 | `test_every_number_traces_to_the_results`, plus a mutation check (`test_the_tracer_catches_an_invented_number`) and the same trace on the real results |
| 3 | `test_template_prose_has_no_digits`, plus its mutation check |
| 4 | `test_btc_literal_verdict_only_in_the_post_hoc_section` |
| 5 | `test_rejected_overnight_test_reads_moves_with_never_first_or_lead` |
| 6 | `test_dry_run_prints_four_stages_in_order_and_runs_nothing` |
| 7 | `test_failed_stage_stops_the_refresh_and_is_named` (plus the raise and SystemExit cases) |

Other tests: `test_no_timing_claim_without_a_lead_verdict` (checklist item 5), the missing-slot error, the CLI with no results, a missing pair, and a lead verdict that swaps the bullet.

The synthetic run is now a session fixture (`conftest.analysis_written`, about 40 s), shared by the analysis tests and the findings tests.

## Carried-over minors
- **BTC Chart 2 A29 note:** fixed. The producer adds `note` to each BTC event study. The contract parses `EventStudy.note`. In the dashboard, Chart 2 shows a warning, the title is "Not read as evidence", and the so-what is replaced by the note.
- **`_spot_gap`, overnight spot-control test, XLU residualised panel:** fixed.
  - `_spot_gap` now has a docstring that explains the misalignment.
  - `btc_overnight_IBIT_spot_control` was added to `A29_EXPLORATORY`.
  - Every residualised BTC panel gets the note. `A29_CHART1_TICKERS` was removed.
  - The prereg has a dated **A29 addendum (POST-HOC, labelling only)**.
- **CPI Chart 2, 0 of 20 signed:** not redefined. It is listed under limitations in section 3 (block `cpi_signing`). **Deferred:** splitting `n_unsigned` into "no reading" and "too small" (r2 m1). That needs new count fields threaded through the step-6 event code, so it is out of write-up scope.
- **Overnight rejections:** these read as "moves with (same night, not a timing result)", and a test covers this.
- **Fed so-what:** softened to "would probably have shown up, but a smaller one can't be ruled out".
- **Biased tests still sit in the exploratory BH family:** this is stated in section 5 of the findings and in the prereg addendum.
- **Tab label:** "Too early to tell" now shows as "undecided", and no results shows as "not run". The tally changed to match, and the design doc example was updated.
- **Browser render:** main checked it before this build. After my changes I could only run an AppTest on the real results (`data/clean`). All 4 pairs and every BTC ticker render with no exception. COIN, MSTR, IBIT and XLU each show 2 A29 warnings, and BTC-USD shows 0. **A real-browser recheck after restarting Streamlit is still needed** (checklist item 4).

## Self-check against lessons.md
- **No look-ahead and no method or statistics changes:** the re-run's numbers are identical.
- **The new guards fire on real data:** the diff shows the new notes, and the real report traces every number.
- **The tests are mutation-sensitive:**
  - the tracer and digit-rule mutation tests above;
  - a Chart 2 note test that would fail if the `es.note` guard were removed;
  - a refresh test that fails if the stop-on-failure check is removed.

## Open questions and decisions
1. **The BTC XLU placebo row ("Passed")** also uses the misaligned spot control. I left it as computed and noted it in the addendum. It does not affect the published verdict, but the row could be marked "Not valid". That would be a checklist-status change, so it needs a decision.
2. **The A29 addendum is a post-hoc prereg text change** (labelling only, dated). It needs user acknowledgement.
3. **The results fingerprint changed** from the pushed step-6 files (notes and code_commit only).
4. **There is no test that the tracked `docs/findings.md` equals a fresh render.** Such a test would fail whenever someone re-runs the analysis at a new HEAD. Byte-identity is tested by rendering twice instead.
5. **`core.autocrlf` may check `docs/findings.md` out as CRLF.** Consider adding `.gitattributes: docs/findings.md text eol=lf`.

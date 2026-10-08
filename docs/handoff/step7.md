# Step 7 hand-off (write-up)

Branch `step7-writeup`. Goal (milestone 1 "done when"): one command refreshes everything, the dashboard shows all pairs, and there is an honest per-pair conclusion. **No new statistics and no method changes.** The results in `data/clean/results/` (step 6, validated r2 PASS, pushed 62424c3) are final for milestone 1. Any change to a test or rule would be a post-hoc amendment; don't make one, stop and report instead.

## Decisions (main, 2026-10-08)
1. **Findings report is generated, not typed.** `python -m poly_actor.analysis report` renders `docs/findings.md` from `data/clean/results/*.json`. Every number in it comes from the JSON. Hand-written prose lives in a template and contains no digits except section numbers and amendment ids (A27, A28, A29).
2. **One-command refresh:** `python -m poly_actor.refresh --workers 4` runs ingest → align → analysis run → report, stops on the first failure with a non-zero exit, and has `--dry-run` that prints the stages without network or writes.
3. **CPI Chart 2 signing window is NOT re-defined** (that would be post-hoc). Keep the honest "0 of 20 signed" note and list it under limitations.
4. **README** status table and a short "Findings" section that links to `docs/findings.md`. It states verdicts only via the generated report (README may say "see findings"; no numbers in README).
5. `docs/findings.md` is tracked (public). It carries the disclaimer: not financial advice, paper only.

## Findings report: required sections
1. One-line answer (same generator as the dashboard headline, so they can't disagree).
2. Per pair: question, verdict, confidence + reason, the primary effect with its 90% CI, n, BH-adjusted p, and the checklist rows with status.
3. What this does NOT show (template prose): no pair shows a lead; "No head start" for Fed is bounded by the MDE, not zero; BTC is unanswered because of the A29 timing bias; CPI has 12 releases; recession is descriptive (one episode); hourly bars and ~10 min odds staleness mean a lead under ~10 min can't be seen.
4. Amendments made after seeing results: list A29 explicitly as post-hoc; A28 as pre-run.
5. Exploratory results (separate, labelled): overnight tests read as "moves with", never "first"; BTC exploratory tests that use the spot control are marked biased (A29).
6. How to reproduce: the refresh command and the commit hash of the results.

## Rules as examples (each becomes a test)

| Input | Expected |
|---|---|
| Results JSON with Fed verdict "No head start", BTC/CPI "Too early to tell", recession "Descriptive only" | findings headline == dashboard headline string ("So far no pair shows Polymarket odds moving ahead of stocks; 3 of 4 ...") |
| Every number token in generated `docs/findings.md` (outside the template) | appears in (or rounds from) a value in the results JSON; a test extracts numbers and checks each traces |
| Template prose files | contain no digits other than amendment ids and section numbers (test) |
| BTC results with `verdict_if_a27_rule3_read_literally` = "No head start" | findings show published "Too early to tell" + A29 reason; the literal verdict appears only in the post-hoc section, labelled |
| Exploratory `btc_overnight_IBIT` BH-rejected | listed under exploratory as "moves with", never with the word "first" or "lead" |
| `python -m poly_actor.refresh --dry-run` | prints 4 stages in order, exit 0, no network, no files written |
| Stage 2 (align) fails | refresh exits non-zero, stages 3–4 not run, message names the stage |

## Carried-over items

### From step 6 (docs/reviews/step6_r2.md, step6_r1.md m8)
- BTC Chart 2 is residualised on the same misaligned spot control and has no A29 note. Add the note (no suppressor bias, since there is no odds term, but the control is still misaligned).
- `_spot_gap`, the BTC overnight spot-control test (r1 m8) and the XLU residualised panel have no A29 note.
- CPI Chart 2: all 20 releases are unsigned (10 have a missing odds reading in the signing bar, 10 move < 0.005 pp; the signing bar is ~17 h before the release). Design flaw, not a code bug. Any re-definition of the signing window must be a dated amendment labelled post-hoc.
- BH-rejected overnight exploratory tests (fed_overnight_TLT, btc_overnight_IBIT) read as "moves with", never as timing claims, in the write-up.
- Fed so-what wording is slightly strong next to Low confidence; soften.
- Biased BTC exploratory p-values (COIN/MSTR/IBIT lag tests) still sit in the exploratory BH family; say so wherever the family is reported.
- No real-browser render was checked by the validator; check the dashboard in a browser on the real results.
- Pair-tab label "Bitcoin · needs data" is wrong for an A29 verdict (the reason is the timing bias, not data). Browser render on real results checked by main 2026-10-08: all cards and the BTC panel render with no errors (after a Streamlit restart; a hot-reloaded server held a stale `text.finding` signature).

## Checklist
1. `docs/findings.md` generated from results; tests above pass; regenerating is byte-identical.
2. Refresh command + dry-run test; README run instructions updated (refresh, report, dashboard).
3. All carried-over minors fixed or explicitly deferred with a reason.
4. Dashboard re-checked in a real browser on the real results (restart Streamlit first).
5. No overclaiming: every verdict sentence matches the computed verdict; "lead"/"first" only where the verdict says so (none currently).
6. `bash scripts/check.sh` PASS. Build report → `docs/reviews/step7_build.md`.

## Build status for validation (2026-10-08)
- Builder report: `docs/reviews/step7_build.md`. Commits e1f236b, ecf9408, 93f18c0, then main: 06eaf73 (BTC XLU placebo row "Not valid", A29 addendum 2, user decision; `.gitattributes` eol=lf for findings.md), ff2e23f (findings regenerated). 474 tests, check.sh PASS.
- User acknowledged both post-hoc A29 addenda (labelling only) on 2026-10-08.
- Main checked the dashboard in a real browser after a Streamlit restart: 0 errors on all 4 pair tabs; BTC shows 4 "Not valid" rows; tabs read "undecided".

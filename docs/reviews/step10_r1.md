# Step 10 review, round 1 (commit 03136d4)

Verdict: PASS WITH ISSUES. No blockers. Two majors, both text-only fixes.

## Checked (evidence)
- `scripts/check.sh`: PASS (586 passed, 1 skipped; ruff ok; pairs and ingest skipped, no raw data here).
- Headless run on the real bundle: HTTP 200. In Chromium I scrolled the whole page (height about 15,900 px): 14 Plotly charts, 0 `stException` boxes, no "Traceback" text, 0 page errors, clean server log.
- Bundle moved aside (`POLY_ACTOR_ELECTION_BUNDLE` pointed at an empty folder): the page shows one alert, "No results to show yet. Build them with: python -m poly_actor.election analyse && python -m poly_actor.election publish". No trace, 0 charts.
- `python -m poly_actor.election report` leaves `git status` clean, so the output is byte-identical. The template contains digits only in section numbers and ids.
- Numbers sampled against `results.json`, all match:
  - H1 b = -0.566, CI [-1.649, +0.517], p_perm 0.507, MDE 1.840.
  - H2 rho = -0.372, p_one 0.975, p_two 0.047 (0.0469), CI [-0.62, -0.06].
  - H2b p = 0.115 over 74 days.
  - H5 Wald W = 9.79, p = 0.020; semis b10 = -0.68.
  - Robustness: house signal -1.92 (HAC p 0.048, perm 0.096); drop-5-days n = 320.
  - E2 2026 implied 1.92 and realised +0.91 (ratio 0.47).
  - E5 -4.49 and +1.11.
  - Event means -5.37% and +0.89% (`mean_ar_pct`).
- Chart points: the H1 bar and marker values are -0.566 and +0.015. The H2 scatter point for NVDA is (0.118, -4.44), matching the per-stock row. The last AI-composite point of chart B is 26.887%, equal to 100*(exp(0.238124)-1) from `cum_log_returns.csv` at 2026-11-12.
- Overclaiming:
  - H3 carries "Descriptive only".
  - E blocks are tagged "Exploratory" and are absent from the headline.
  - The negative H2 rho appears once, in the box labelled "Exploratory, not a finding". It is never called significant.
  - The H2 title and so-what stay inside the "did not predict" verdict.
- No statistics are computed in `app.py`, `charts.py` or `report_text.py`. A grep for mean, std, corr, rank and spearman found nothing. The only transform is `_level_pct`.
- `git diff c7363ff 03136d4 -- reports/election/` touches `results.json` only: 10 insertions, 2 deletions. These are `label` keys, one H5 `plain` string and the preregistration string. The series diff is empty. No number changed.

## Issues

### Major
1. **`findings.md:158-160` says "Not in the results." for E1, but the bundle has it.** `results.json` `exploratory.e1` holds the window, the last-30-session shift of -5.56 points per 10 (CI -6.90 to -4.21) and the HAC p. The cause is `findings.py:88-94`. The E1 text needs the rolling series (`report_text.py:1048-1052` reads `rolling["b10_pct"]`), so `_guarded` returns the "missing" block when the report is built from `results.json` only. The shipped report therefore tells the reader a section's data is absent when it is not. It also hides the largest exploratory effect in the study, which the Streamlit page does show. Fix: split the E1 title off from the series-dependent part (build it from `e1` alone), or have `findings.py` read `e1_rolling.csv`. Alternatively drop the E1 heading from `findings.md` and say it is page-only.
2. **`report_text.py:1171` claims a method that was not used.** "Surprise-based event windows" appears under "What a specialist does". The pre-registration has no surprise construction. The window is a fixed calendar window, election-day close to next close, against each stock's own market and bond betas. Your check required that no method be claimed that was not used. Fix: rename it "A fixed event window (election-day close to next close) on abnormal returns, not a raw price change".

### Minor
- `findings.md:224` and the matching `report_text` source list the amendments as "(A1, A2)". A3 exists. The `A3` disclosures (opening-print day, permutation resolution of 0.491 against 0.507) are not on the page or in `findings.md`.
- E5 title, "the gap narrowed after the event day". The ex-event-day figure is +1.11 against -4.49, so the sign flipped. "Reversed" or "turned positive" is accurate.
- E2 so-what: "index-level volatility did not describe the move in the AI names" compares one index with one night's group mean and is slightly causal in tone. It is tagged exploratory.
- Section 2 bullet "That is not the same as no exposure": placing 1.84% per 10 points next to the 25.5-point move invites the reader to multiply them (about 4.7%). The text says it does not do the arithmetic, but it nudges the reader towards it. The opening paragraph's "If it is zero, an election hedge on AI names was wasted premium" is advice-flavoured, though conditional.
- The Section 2 bullet "The non-AI basket is the reference point" says "AI names are simply noisier against the odds". The bundle has no dispersion test, so this is an interpretation.
- E1 page text says "no stable sensitivity stands out", while the same block reports a late-sample shift with HAC p = 5e-11. It is labelled post hoc, but the title and the so-what pull in opposite directions.
- From the step-10 build report, deferred: the `panel.py` and `ingest.py` minors from the step-9 batch.

## Not checked
- Visual QA of every screenshot in `docs/images/election/`. I only looked at the live page, programmatically.
- Dark theme.
- The rest of the 586 tests beyond the PASS result, and mutation tests of the number tracer.
- The README text.
- `launch.json`.
- The crusader's scope.

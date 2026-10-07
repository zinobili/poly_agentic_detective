# Step 6 validation, round 2 (last)

Date: 2026-10-08. Branch `step6-analysis` at dd6998a. Scope: diff c6191cd..79e8c4c, r1 B1 and M1, prereg A29.

## Verdict

**PASS: 0 blockers, 0 majors, 5 minors.** B1 and M1 are fixed. `scripts/check.sh` passes (443 tests, ruff clean, pairs reproducible, dry-run 106 calls). A rebuild with `run --workers 4` takes 44 s and is byte-identical to `data/clean/results/` (all 5 JSONs).

## Checked

- **B1 / A29.** Real BTC JSON: verdict "Too early to tell", reason "...misaligned with the ETF's hourly bar by about 30 minutes, so the test is biased...", confidence Low. `verdict_if_a27_rule3_read_literally` = "No head start" is kept. Primary, "Beyond Bitcoin's own price" and Robustness rows read "Not valid". No "Failed (opposite sign)" and no "rule out" text for BTC. A29 note present on the residualised IBIT, COIN and MSTR Chart 1 panels and on the exploratory COIN, MSTR and IBIT-lag tests. The no-control test, raw Chart 1 and XLU carry no note. BH unchanged: Fed 0.5235, BTC 1.0, CPI 0.5235. The BTC robustness R3 is now "not applicable".
- **Bias test.** `test_stale_hourly_spot_control_biases_the_btc_primary_negative` uses a sub-hour simulation (zero-information odds, 10 min stale) and contrasts hourly closes (needs >= 19/20 with t < -3) against exact minute spot (needs >= 18/20 with |t| < 2.58). Mutation: I fed the minute (aligned) control into the "stale" arm. It gave 0/20 biased seeds, so the test fails as it should.
- **M1.** Card and verdict-panel headlines come from `verdict_sentence` for `primary_ticker`. Real texts: Fed "Fed odds give no head start on TLT", BTC "Too early to tell whether Bitcoin price odds move before IBIT", CPI "Too early to tell ... TLT", recession "A description of ...". Chart 1 titles are labelled "(exploratory)", and a panel with a caveat note is "Not read as evidence". The top headline and tally are verdict-driven and do not overclaim.
- **r1 minors.**
  - m1 fixed: the Fed and CPI placebo rows read "Not needed".
  - m2 fixed.
  - m3 fixed: the counts are written (`event_study_counts`) and the dashboard shows the reason.
  - m4 fixed (`is not None`).
  - m5 fixed.
  - m7 fixed.
  - m6: the synthetic sub-hour test was added.

## Open questions from the builder

1. **BTC Chart 2 has no A29 note: minor gap, not a blocker.** `btc_job` residualises Chart 2 on the same `controls` (`run.py:~136`). That regression uses only spot, not the odds, so there is no suppressor sign bias like the primary's. The stale control still leaves the spot move partly unremoved or over-removed, so the chart is not clean. Events are chosen on odds moves only. It is within A29's spirit ("same control"), though A29 item 3 does not name it. Add the same note to the BTC Chart 2 panels (or state the exception in the prereg).
2. **CPI Chart 2, all 20 unsigned: a design flaw, not a code bug, and not serious.** The code matches A27 rule 13 literally. I measured it: 10 of 20 releases have a NaN odds change in the previous session's last bar. The other 10 have |dPM| between 3e-5 and 2.3e-3, all below the 0.005 pp threshold. The signing bar is the previous day's 15:30 bar, about 17 h before the 08:30 release, so it is not "just before" the release. Impact: only an exploratory chart is empty, it carries the honest note ("0 of 20 could be used"), and the primary CPI test is unaffected. Fix next step: sign by the odds change over the pre-release window (as in the primary's release-60 min proxy) and/or re-scale the threshold. Record it as a post-hoc change.

## Issues (all minor)

- **m1.** `run.py:_spot_gap` and `btc_overnight_IBIT_spot_control` use the same stale control and carry no A29 note (r1 m8, still open). The XLU residualised panel also has no note. The CPI note text for "unsigned" cannot separate NaN from tiny moves, so split the counts.
- **m2.** `btc_overnight_IBIT` (no control, p about 1e-54) and `fed_overnight_TLT` are BH-rejected exploratory results (r1 m9). They are not shown now, but keep them out of timing claims.
- **m3.** The Fed so-what "A lead big enough to be useful would most likely have shown up" sits beside Low confidence. It is acceptable under A28, but the wording is a bit strong. Consider "would probably have shown up".
- **m4.** The exploratory note on `btc_IBIT_lag2`, `btc_IBIT_lag3` is also attached to tests that use the biased control, as A29 says. That is right. But `exploratory_family` BH still counts them, so adjusted p-values for the other exploratory tests depend on biased ones. This is exploratory only.
- **m5.** Not-checked caveat from r1 stands: no real-browser render.

## Not checked

Real-browser rendering. Plotly figure content. The FFT shift statistics (the rebuild is byte-identical). The CPI release levels against the price book.

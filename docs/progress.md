# Progress

## Resume here
- **2026-10-08: Step 7 VALIDATED + merged to master (local).** Crusader = SHIP WITH FIXES; both majors fixed (ad40399: atomic findings write, corrupt results file → exit 2 naming the file; results unchanged except commit stamp; findings regenerated 4098f37); minors → docs/handoff/milestone2_backlog.md. IN PROGRESS: check.sh. NEXT: ASK USER before push → milestone 1 DONE.
- **2026-10-06: Step 6 STARTED** on branch `step6-analysis`. Plan + DRAFT A27 (analysis settings) in docs/handoff/step6.md. A27 FROZEN (f4f0acb) after blind quant review (3 blockers/10 majors adopted) + user decisions (CPI min 10, pair 4 'Descriptive only', ΔP main). PAUSED by user 2026-10-06 before the build. NEXT ACTION: spawn quant-researcher with "Read docs/handoff/lessons.md and docs/handoff/step6.md, then build step 6 (order of work: synthetic tests → CPI usable count from flags → real panels → dashboard render)"; then check.sh → validator (opus) → merge → crusader → ask before push. Then: record A27 in prereg → quant-researcher build → check.sh → validator (opus).
- Updated 2026-10-05. On branch `wip/step4-alignment` (not pushed). Round-2 fix batch committed (fid-10 Fed+BTC, A25, 284 tests, check.sh PASS; Fed/BTC median age ~594s).
- 2026-10-05 user: YES extend fid-10 to CPI + recession (handoff step4.md 'Round 2b'). Batch 2b DONE (8200c8c): 1,049 calls, 0 failures; median age 592-595s all 4 pairs; check.sh PASS. Validator r2 = PASS (0 blockers/majors, 5 minors → docs/handoff/step5.md; docs/reviews/step4_r2.md). Merged to master; crusader SHIP WITH FIXES (major = ruff format on review md, fixed; minors → step5.md); check.sh PASS. 2026-10-05 user: push OK; A22 RETIRED (A26; CLAUDE.md updated; code removal = step 5 task). Step 5 STARTED on branch `step5-dashboard`: plan written (docs/handoff/step5.md). 5a DONE (77cbbb8: A22 code removed, panels equal old strict, 280 tests, check PASS; not mutation-tested → validator). 5b DONE (1adfbd1: dashboard, 331 tests, headless start ok). Validator r1 = PASS w/ 1 major (ticker-keyed contract) + 7 minors (docs/reviews/step5_r1.md). Round-2 fixes DONE (44ef7a9, 343 tests, check PASS). Validator r2 = PASS (0 majors; minors → docs/handoff/step6.md). Merged to master; crusader SHIP WITH FIXES (major = false positive; README + dead code fixed; minors → step6.md); check PASS. PUSHED 2026-10-06 (2893952) → check.sh → validator.
- Next: after 2b → check.sh → validator r2 (LAST round, opus) → merge to master → crusader → push (ask before push).
- Steps 0-3 DONE (validated, crusader SHIP, pushed).
- **Step 4 (alignment): built, validator round 1 = FAIL** (docs/reviews/step4_r1.md). On the wip branch:
  - `src/poly_actor/align/` (panel builder + CLI `python -m poly_actor.align run|report [--strict-asof]`), tests (267 pass, check.sh PASS), prereg amendments A22–A24, lessons line, CLAUDE.md A22 exception note, pyproject `-m "not live"`.
  - Panels in data/clean/ (git-ignored, rebuildable with `python -m poly_actor.align run`).
- User decisions so far: A22 = 53s sampling tolerance (recorded as an exception), A23 = CPI edge mass 0.25 primary + 0.10 robustness, A24 = BTC keep no-extrapolation.
- Validator r1 majors:
  - M1: the tolerance is applied to every fidelity and every instant. It must be fid-60 points ≤53s after :00 only (`align/prices.py:115`, `pipeline.py:126`).
  - M2: on `both_trading` rows, Polymarket is still ~1,790s stale (stock bars end at :30, fid-60 samples at :00). Biases toward "Polymarket lags". (Main earlier relayed a "-5s median" that was over all rows; corrected to the user.)
  - M3: 4 look-ahead guards survive mutation: the tolerance constant, `--strict-asof` silently tolerant, BTC-USD getting the tolerance, BTC-USD spot stamped at bar START (1h look-ahead in primary test 2's control).
  - 7 minors (main one: a row ending exactly at a roll time takes the new event without a roll_hour flag).
- **Waiting on user: M2 decision.** A (recommended) = download fid-10 for the full history of Fed + BTC tokens (~1,800 calls, ~20–30 min with --workers 4), so prices are ≤10 min stale at :30 without look-ahead. B = accept ~30 min staleness, documented, with step 6 treating a lag-1 result as unreliable.
- **Next action on resume:**
  1. `git checkout wip/step4-alignment`.
  2. Get the M2 decision.
  3. One data-engineer batch: M1 + M2 + M3 + minors, with a lean brief pointing to docs/reviews/step4_r1.md.
  4. `check.sh`, then validator round 2 (the LAST round under the cap, then ask the user).
  5. Merge to master → crusader → push.

| Step | Status | Validator | Notes |
|---|---|---|---|
| 0 Setup + harness | **done** | R1 + R2: PASS WITH ISSUES, all fixed | guard (case, Grep/Glob, glob tricks, git forms, line continuations), post-edit scope + F401, network+DNS block in tests; 66 tests pass. Known: guard blocks commit msgs quoting dangerous flags; UDP/subprocess network not blocked in tests |
| 1 Data check | **done** | R1 (9 issues), R2 (early-close leak), R3 PASS WITH ISSUES (doc minors fixed by main) | hourly feasible across full market life; API look-ahead + inconsistent boundaries → clip + de-dup; bar re-stamp via XNYS calendar | validator found: API appends live price after endTs (look-ahead), yfinance 730 = trading days, recommendation too pessimistic; data-engineer fixing doc; requirements copied to milestone1_plan.md |
| 2 Pairs | **done** — 37a7a9e, d432858, b7e53cd (all 4 pairs approved after A20/A21) | R3 PASS WITH ISSUES (dates all verified vs official calendars). Open: BTC re-listed rungs (major), two-sided date check, CPI companion-event rule | Recommendation: Fed approve; BTC hold until A15; CPI approve release-day test; recession secondary |
| 2 Pairs (history) | R1 **FAIL** (11 items) → R2 **FAIL**: 3 FOMC dates 1 day late, CPI release times wrong (Oct 2025 CPI never released, shutdown), false CPI Aug-2026 gap, bucket parser bug, DST bug in BTC roll | fresh data-engineer fixing; adding unit tests + date cross-check vs closedTime; prereg amendments logged | draft: fed_decision, us_recession, bitcoin_monthly_price, us_cpi_inflation (tariffs rejected). Needs user approval after validation |
| 3 Ingestion | **done** (user accepted 2026-10-03) | R1 PASS WITH ISSUES (no look-ahead in 1.32M rows; spot-checks exact) | majors: fid-60 holes, empty-200 marked covered |
| 4 Alignment | **done** (2026-10-05) | R1 FAIL (3 majors) → R2 PASS (5 minors → step5.md) | fid-10 all pairs (A25), PM median age ~593s; A22 tolerance never fires (decision pending) |
| 5 Dashboard | **done** (2026-10-05) | R1 PASS w/ 1 major (ticker-keyed contract) → R2 PASS | built against a results contract; analysis slots say "Not run yet" until step 6 |
| 6 Analysis | **done** (2026-10-08, pushed) | R1 FAIL (B1 BTC control, M1 headlines) → R2 PASS | A28 calibration fixes; A29 post-hoc BTC; all verdicts Low, no pair shows a lead |
| 7 Write-up | **done** (2026-10-08) | R1 PASS (4 minors: 1 fixed, 3 → milestone2_backlog.md) | generated docs/findings.md; `python -m poly_actor.refresh` |

## Decision log
- 2026-10-01: yfinance first; Claude proposes famous pairs; build first, explain after; check in after step 0; 4 agents (data-engineer, quant-researcher, validator, tutor); venv+pip since uv isn't installed.
- 2026-10-03: dashboard design agreed for a lay reader (answer first, scorecard, confidence meter, every chart states its takeaway, sticky pair tabs that keep scroll position). Reference for steps 5–7: `docs/design/dashboard_ux.md` + `docs/design/dashboard_mockup.html` (made-up data).

## Waiting on user (work continues on unblocked items meanwhile)
- [x] 2026-10-01: user approved commits. Step 0 committed (3771e65). Steps 1 and 2 get committed once their validators pass (approved). Ask before committing later steps if unclear; never push without asking.
- [x] 2026-10-01: repo may go public → `high_level_plan.md` kept private via `.git/info/exclude` (local-only ignore). `docs/` stays tracked.
- [x] 2026-10-01: keep Claude co-author line on commits. Treat all tracked files as public; data/ never committed.
- [x] 2026-10-01: user: "go with the validation". Pair calls: fed_decision keep+fix; us_recession secondary/event study; bitcoin keep with ladder-implied signal + BTC-USD baseline; CPI release-day event study. Validator verdicts settle disputes. Final reworked list still shown to user before step 3.

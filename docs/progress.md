# Progress

## Resume here
- Updated 2026-10-01. Commits: 3771e65 (step 0), 1a0fdba (step 1), 37a7a9e + d432858 (step 2).
- Step 2 is done for fed_decision, us_cpi_inflation and us_recession (approved). **bitcoin_monthly_ladder is ON HOLD**: amendment A20 needs a time-t rule for re-listed rungs without "-from-" slugs (validator issue: 15 kept rungs created after their strike was touched, e.g. 2026-02 dip 60k; dead duplicates in 2025-07/2025-11). Minor items: A18 wording, plateau tie-break doc, skip rungs with no CLOB quote at t.
- Next action: (1) BTC A20 fix + validate; (2) start Step 3 ingestion for the 3 approved pairs, following the "Requirements learned in step 1" in milestone1_plan.md.
- Waiting on user: nothing. 2026-10-01 user approved (1) the resume-note-at-boundaries usage guard in CLAUDE.md and (2) local commits after each validated step (never push).
- In flight: data-engineer on BTC A20 (writes build_pairs.py, pairs.py, tests, yaml, prereg, step2 doc).

| Step | Status | Validator | Notes |
|---|---|---|---|
| 0 Setup + harness | **done** | R1 + R2: PASS WITH ISSUES, all fixed | guard (case, Grep/Glob, glob tricks, git forms, line continuations), post-edit scope + F401, network+DNS block in tests; 66 tests pass. Known: guard blocks commit msgs quoting dangerous flags; UDP/subprocess network not blocked in tests |
| 1 Data check | **done** | R1 (9 issues), R2 (early-close leak), R3 PASS WITH ISSUES (doc minors fixed by main) | hourly feasible across full market life; API look-ahead + inconsistent boundaries → clip + de-dup; bar re-stamp via XNYS calendar | validator found: API appends live price after endTs (look-ahead), yfinance 730 = trading days, recommendation too pessimistic; data-engineer fixing doc; requirements copied to milestone1_plan.md |
| 2 Pairs | **done** (BTC on hold) — 37a7a9e, d432858 | R3 PASS WITH ISSUES (dates all verified vs official calendars). Open: BTC re-listed rungs (major), two-sided date check, CPI companion-event rule | Recommendation: Fed approve; BTC hold until A15; CPI approve release-day test; recession secondary |
| 2 Pairs (history) | R1 **FAIL** (11 items) → R2 **FAIL**: 3 FOMC dates 1 day late, CPI release times wrong (Oct 2025 CPI never released, shutdown), false CPI Aug-2026 gap, bucket parser bug, DST bug in BTC roll | fresh data-engineer fixing; adding unit tests + date cross-check vs closedTime; prereg amendments logged | draft: fed_decision, us_recession, bitcoin_monthly_price, us_cpi_inflation (tariffs rejected). Needs user approval after validation |
| 3 Ingestion | not started | | |
| 4 Alignment | not started | | |
| 5 Dashboard | not started | | |
| 6 Analysis | not started | | |
| 7 Write-up | not started | | |

## Decision log
- 2026-10-01: yfinance first; Claude proposes famous pairs; build first, explain after; check in after step 0; 4 agents (data-engineer, quant-researcher, validator, tutor); venv+pip since uv isn't installed.

## Waiting on user (work continues on unblocked items meanwhile)
- [x] 2026-10-01: user approved commits. Step 0 committed (3771e65). Steps 1 and 2 get committed once their validators pass (approved). Ask before committing later steps if unclear; never push without asking.
- [x] 2026-10-01: repo may go public → `high_level_plan.md` kept private via `.git/info/exclude` (local-only ignore). `docs/` stays tracked.
- [x] 2026-10-01: keep Claude co-author line on commits. Treat all tracked files as public; data/ never committed.
- [x] 2026-10-01: user: "go with the validation". Pair calls: fed_decision keep+fix; us_recession secondary/event study; bitcoin keep with ladder-implied signal + BTC-USD baseline; CPI release-day event study. Validator verdicts settle disputes. Final reworked list still shown to user before step 3.

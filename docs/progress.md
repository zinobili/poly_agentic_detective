# Progress

## Resume here
- **PAUSED 2026-10-01 ~15:40 UTC at the user's request (token limit). Do not continue until the user says so.**
- Commits (after the email rewrite): step 0-2 and harness … 03ad9eb (step 3), 8de9df1 (README/LICENSE/CI), 398986a (hook CI fix) = HEAD. Pushed to https://github.com/zinobili/poly_actor (private), CI green.
- Steps 0-2 DONE. All 4 pairs approved, pre-registration frozen (A1-A21).
- Step 3: committed and validated (PASS WITH ISSUES). **Fix round built but NOT validated or committed** (saved on disk):
  - modified: src/poly_actor/ingest/{cli,common,polymarket,stocks,targets}.py, tests/test_ingest.py
  - new: tests/test_ingest_fixes.py, docs/step3_ingestion.md; outputs in data/scratch/step3/ (gap_inventory.csv, stock_gaps.csv, run_log_fix.txt)
  - 162 tests pass, ruff clean (checked at pause).
  - Fixes: fid-10 backfill of fid-60 holes (1,893 gaps: 1,882 filled, 10 partial + 1 unfilled = one upstream outage 2025-10-29 09-14Z); empty-200 → status empty / empty_confirmed with fid-1 probe; legacy 0-row ok windows re-fetched; ingest lock; torn-manifest-line skip; window end floor(asof-10min); stock bar-count check (23 short days) + 1-day lag; 3 test gaps closed.
  - Raw rows now: fid60 576,638 (697 tokens), fid10 47,567 (109), fid1 743,602 (238). Re-run at fixed asof = 0 calls.
- 2026-10-02: applied workflow optimisations 1–7 (agent report cap + docs/reviews/, builder self-check vs checklist + docs/handoff/lessons.md, severity gate + 2-round cap, sonnet validator by default, hand-off files, scripts/check.sh, --workers for ingestion). The --workers change is part of the uncommitted step 3 fix round.
- **Next action on resume:** run a lean validator on the step 3 fix round (/validate-step 3: backfill correctness and no look-ahead in fid=10, empty/empty_confirmed logic, lock, bar-count check, 1-day lag, new tests) → fix → commit → push only if the user asks → Step 4 (alignment).
- Step 4 notes: resample across fid=60/10/1; clip/flag 209 rows with p>1; yfinance gap 2026-01-30 11:30 ET → 02-02 13:30 ET; BTC-USD short days in stock_gaps.csv; re-stamp bars to bar end (XNYS); BTC dropped-hour/PAV/CPI-clip metrics.
- Waiting on user: the go-ahead to resume.

| Step | Status | Validator | Notes |
|---|---|---|---|
| 0 Setup + harness | **done** | R1 + R2: PASS WITH ISSUES, all fixed | guard (case, Grep/Glob, glob tricks, git forms, line continuations), post-edit scope + F401, network+DNS block in tests; 66 tests pass. Known: guard blocks commit msgs quoting dangerous flags; UDP/subprocess network not blocked in tests |
| 1 Data check | **done** | R1 (9 issues), R2 (early-close leak), R3 PASS WITH ISSUES (doc minors fixed by main) | hourly feasible across full market life; API look-ahead + inconsistent boundaries → clip + de-dup; bar re-stamp via XNYS calendar | validator found: API appends live price after endTs (look-ahead), yfinance 730 = trading days, recommendation too pessimistic; data-engineer fixing doc; requirements copied to milestone1_plan.md |
| 2 Pairs | **done** — 37a7a9e, d432858, b7e53cd (all 4 pairs approved after A20/A21) | R3 PASS WITH ISSUES (dates all verified vs official calendars). Open: BTC re-listed rungs (major), two-sided date check, CPI companion-event rule | Recommendation: Fed approve; BTC hold until A15; CPI approve release-day test; recession secondary |
| 2 Pairs (history) | R1 **FAIL** (11 items) → R2 **FAIL**: 3 FOMC dates 1 day late, CPI release times wrong (Oct 2025 CPI never released, shutdown), false CPI Aug-2026 gap, bucket parser bug, DST bug in BTC roll | fresh data-engineer fixing; adding unit tests + date cross-check vs closedTime; prereg amendments logged | draft: fed_decision, us_recession, bitcoin_monthly_price, us_cpi_inflation (tariffs rejected). Needs user approval after validation |
| 3 Ingestion | committed 03ad9eb; fix round built, NOT yet validated/committed (paused) | R1 PASS WITH ISSUES (no look-ahead in 1.32M rows; spot-checks exact) | majors: fid-60 holes, empty-200 marked covered |
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

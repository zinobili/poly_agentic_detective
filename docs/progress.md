# Progress

## Resume here
- Updated 2026-10-01. Commits: 3771e65 (step 0), 1a0fdba (step 1), 37a7a9e, d432858, b7e53cd (step 2), d038f5b (harness).
- Steps 0-2 DONE. All 4 pairs approved: fed_decision, bitcoin_monthly_ladder, us_cpi_inflation (release-day event study), us_recession (secondary). Pre-registration frozen (A1-A21) before any price history was viewed.
- Current: Step 3 (ingestion), stage = VALIDATING. Built and run (uncommitted): src/poly_actor/ingest/*, store/raw_views.py, load_btc_rungs, tests/test_ingest.py; 144 tests pass. Data: 1.32M Polymarket rows (697 tokens), 48.7k stock bars, 2,665 calls, 0 failures; re-run 0 calls. pairs.yaml status → approved.
- Next action: wait for the step 3 validator → fix → commit. Then step 4 (alignment). Trends/GDELT = step 3b, later.
- Step 3 requirements: "Requirements learned in step 1" + "Step 3, BTC ladder" in docs/milestone1_plan.md.
- Waiting on user: nothing.
- Side task (2026-10-01, user request): public-repo readiness audit (fresh validator agent). Added README.md (with disclaimer), LICENSE (MIT), .github/workflows/ci.yml — uncommitted, not part of step 3; commit them separately. Commit-email rewrite to GitHub noreply is pending: the user will run it. Other findings (empty-window data gap, dependency pinning, minors) will be pasted into this session by the user for discussion.

| Step | Status | Validator | Notes |
|---|---|---|---|
| 0 Setup + harness | **done** | R1 + R2: PASS WITH ISSUES, all fixed | guard (case, Grep/Glob, glob tricks, git forms, line continuations), post-edit scope + F401, network+DNS block in tests; 66 tests pass. Known: guard blocks commit msgs quoting dangerous flags; UDP/subprocess network not blocked in tests |
| 1 Data check | **done** | R1 (9 issues), R2 (early-close leak), R3 PASS WITH ISSUES (doc minors fixed by main) | hourly feasible across full market life; API look-ahead + inconsistent boundaries → clip + de-dup; bar re-stamp via XNYS calendar | validator found: API appends live price after endTs (look-ahead), yfinance 730 = trading days, recommendation too pessimistic; data-engineer fixing doc; requirements copied to milestone1_plan.md |
| 2 Pairs | **done** — 37a7a9e, d432858, b7e53cd (all 4 pairs approved after A20/A21) | R3 PASS WITH ISSUES (dates all verified vs official calendars). Open: BTC re-listed rungs (major), two-sided date check, CPI companion-event rule | Recommendation: Fed approve; BTC hold until A15; CPI approve release-day test; recession secondary |
| 2 Pairs (history) | R1 **FAIL** (11 items) → R2 **FAIL**: 3 FOMC dates 1 day late, CPI release times wrong (Oct 2025 CPI never released, shutdown), false CPI Aug-2026 gap, bucket parser bug, DST bug in BTC roll | fresh data-engineer fixing; adding unit tests + date cross-check vs closedTime; prereg amendments logged | draft: fed_decision, us_recession, bitcoin_monthly_price, us_cpi_inflation (tariffs rejected). Needs user approval after validation |
| 3 Ingestion | in progress (build) | | price data first; Trends/GDELT = 3b |
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

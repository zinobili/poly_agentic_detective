# Step 6 hand-off (analysis)

Branch `step6-analysis`. Inputs: the panels in `data/clean/` (step 4). Output: `data/clean/results/<pair_id>.json` in the ticker-keyed contract (`src/poly_actor/dashboard/contract.py`), plus `data/clean/results/summary.json` (BH table). Methods are fixed by `docs/preregistration.md`. The settings below fill the gaps it leaves open, and are **frozen as amendment A27 before any return is examined**. So far no one has computed a correlation or a regression on these panels.

Data available (counts only, no returns looked at): Fed 3,469 both-trading rows, 16 decision hours. BTC 1,691 rows, 20 month-end rolls. CPI 1,764 rows, 20 releases. Recession 3,008 rows, 2 markets.

## Analysis settings: prereg A27 (FROZEN 2026-10-06, commit f4f0acb)
Read `docs/preregistration.md` § Round 6 (A27) and the replacement wording in `docs/reviews/step6_a27_review.md` (B1–B3, M1–M10, m1–m12). Those are the spec. Do not re-decide anything there. If something is ambiguous, stop and report it; do not choose after seeing results.

**Contract changes needed (dashboard, step 5 code):**
- Add verdicts "No head start" and "Descriptive only".
- Add an optional exploratory flag `stocks_first` (A27 rule 8).
- A Chart 1 slot can be `"not_in_plan"`, and the dashboard shows "Not part of the plan".
- BTC xcorr has `raw` and `residualised` panels.
- The xcorr band is a scalar simultaneous band.
- Chart 2 can mark an opening-gap step and show individual paths and a random-date band.
- Checklist status "Failed (opposite sign)".
- The glossary reads its parameters from the results.

**Module layout:** `analysis/` holds pure functions (`sample.py` for the lag grid and filter of rule 1, `models.py` for OLS/HAC/Spearman/BH, `placebo.py`, `events.py`, `verdict.py`), a `run.py` CLI (`python -m poly_actor.analysis run --workers N`), and results JSON written atomically.

## Build rules as examples (each becomes a test; replaces the draft table)

| Input | Expected |
|---|---|
| panel-shaped synthetic (7 bars/session, early closes, holes, excluded rows), PM leads by 2 bars, β = 0.1 SD | peak at +2 outside the simultaneous band in ≥ 90% of 100 seeds; Fed lead-sum p < 0.01; verdict "Polymarket moves first" |
| contemporaneous-only effect (b0 = 0.1 SD, b1 = b2 = 0), 200 seeds | "Polymarket moves first" in ≤ 8% of seeds |
| realistic null (ΔPM 70% zeros + t(3) jumps, GARCH-t returns), 1,000 fixed seeds | one-sided rejection rate at α = 0.05 within [3%, 8%]; band exceedance within [3%, 7%] |
| huge ΔPM only on decision bars + TLT drift on the 15:30 bar | those rows are absent from the design matrix; removing the lag-window check makes this test fail (mutation) |
| lag landing on a Yahoo hole | NaN, never the previous bar |
| BTC: IBIT = spot_t + 0.4·spot_{t−1} + e, ΔPM_{t−1} = spot_{t−1} + e′ | no-control p < 0.01, with-control p > 0.10 in ≥ 90% of 100 seeds → "No extra information" |
| BH p = (0.02, 0.06, 0.09), q = 0.10 | all three rejected (fails Holm/Bonferroni) |
| BH p = (0.01, 0.08, 0.5) | only the first rejected (fails uncorrected) |
| CPI: 11 usable, validation passes, null result | the test runs; "Too early to tell (underpowered)" |
| CPI validation fails | "Too early to tell"; charts titled as previews |
| pair 4 | "Descriptive only", confidence Low, no p-value anywhere |
| significant opposite sign | primary row "Failed (opposite sign)" |

**Order of work:** (1) build and test on synthetic data only; (2) the CPI usable count from validity flags only, written to the build report; (3) only then run on the real panels; (4) render the dashboard with the real results (AppTest for all 4 pairs).

## Carried-over items

### From step 4 (docs/reviews/step4_r2.md)
- **m3:** PM prices on lead-lag rows are ~10 min stale (median ~593 s). State it, and read lag 0 / lag 1 with that in mind.
- **m4:** quotes up to 3 h old still enter `both_trading` (97 BTC rows > 1500 s). Pre-register a max-age cut-off before looking at results.

### From step 5 (docs/reviews/step5_r1.md, step5_r2.md)
- The glossary hard-codes analysis parameters (lags ±12, 2 SD, "0.1 to 0.2 is notable"). Step 6 writes the real parameters into the contract, and the glossary reads them from there.
- `components.html` is deprecated in Streamlit. Replace it.
- The BTC-USD line in chart 3 breaks overnight although it trades 24/7. Use the gap rule per asset.
- `text.headline`: a mix of "Too early to tell" and "No extra information" verdicts still says "not moved ahead in any pair" (slight overclaim; untested).
- `test_ticker_without_results_shows_not_run` uses a loose `count >= 1`.
- The picker state resets when the ticker set changes (harmless).
- Design question: which tickers count as controls. Only `CONTROL_TICKERS` get the "(control)" label; SPY/XLF in the Fed pair do not.
- Not yet looked at in a real browser: the sticky pair tabs and the scroll-on-card-click.

### Crusader push review 2026-10-05 r2 minors (docs/reviews/push_2026-10-05_crusader_r2.md)
Fix where step 6 touches the code: streamlit pinned twice in pyproject; `load_panel` has no corrupt-parquet handling; `app.py` re-reads every results JSON on each rerun (cache it); `_summary_lock` sleep not injectable/tested; load.py helper docstrings/units; loose dict annotations in align/cli.py; text.py is 473 lines (split); module-level `main()` in app.py.

## Checklist
- [x] A27 is approved by the user and recorded in the prereg BEFORE any return is examined (f4f0acb)
- [ ] Every example row is a test; planted lag recovered; noise gives nothing
- [ ] Results JSON validates against the contract and the dashboard renders it for all 4 pairs
- [ ] Verdict, confidence and checklist are computed by code, never hand-written
- [ ] The step-5 dashboard minors listed above are fixed
- [ ] Build report ≤250 words; full report `docs/reviews/step6_build_r1.md`

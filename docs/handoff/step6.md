# Step 6 hand-off (analysis)

Branch `step6-analysis`. Inputs: the panels in `data/clean/` (step 4). Output: `data/clean/results/<pair_id>.json` in the ticker-keyed contract (`src/poly_actor/dashboard/contract.py`), plus `data/clean/results/summary.json` (BH table). Methods are fixed by `docs/preregistration.md`. The settings below fill the gaps it leaves open, and are **frozen as amendment A27 before any return is examined**. So far no one has computed a correlation or a regression on these panels.

Data available (counts only, no returns looked at): Fed 3,469 both-trading rows, 16 decision hours. BTC 1,691 rows, 20 month-end rolls. CPI 1,764 rows, 20 releases. Recession 3,008 rows, 2 markets.

## A27 (DRAFT, pending user approval): analysis settings fixed before results

**Sample (all hourly tests):** `both_trading` rows only. Drop `roll_hour`, `event_hour`, `outage_mask`, and rows with `pm_obs_age_s > 1800` (the cut-off for step-4 m4; robustness run at 900). Bars are session bars, so "lag k" means k bars. Lags never cross a session boundary (a lagged value from the previous day is NaN).

**Pair 1, Fed (primary test):** OLS of `ret_TLT_t` on Δdovishness at lags 0, 1, 2. Newey-West HAC SE with 6 lags. H1 (one-sided): the sum of the 3 coefficients is > 0. Secondary: SPY the same. Exploratory: XLF−SPY.

**Pair 2, BTC (primary test):** OLS of `ret_IBIT_t` on Δln(ladder)_{t−1}, controlling for `ret_BTC-USD` at lags 0 to 3. HAC(6). H1 (one-sided): coefficient > 0. Placebo: the same model on XLU, which passes if two-sided p > 0.10. The model without the spot control is also reported. Lags 2–3 on IBIT, and COIN and MSTR, are exploratory.

**Pair 3, CPI (primary test):** first the method validation exactly as pre-registered (a majority of resolved months within 0.1 pp), which must pass before any return is examined. Then the surprise proxy versus the TLT opening gap, using a one-sided Spearman rank correlation (< 0) as the p-value and the sign test as a reported companion. QQQ and the first hourly bar are secondary.

**Pair 4, recession (descriptive only, no p-value):** the 10 largest daily increases and the 10 largest daily decreases in P(Yes), on ET calendar days. Report the mean IWM−SPY close-to-close spread on day 0 and day +1 for each group, with a bootstrap 90% CI. Confidence is fixed at Low.

**Multiple testing:** Benjamini–Hochberg at q = 0.10 across the **3 inferential primaries** (Fed, BTC, CPI). The pre-registration says "4 primary tests", but pair 4 is pre-registered as making no significance claim, so it has no p-value to correct.

**Chart 1 (who moves first), per ticker, exploratory:** cross-correlation of the PM change with the ticker return at lags −6 to +6 bars, where a positive lag means PM moves first. The noise band is the 95% interval from a placebo that circularly shifts the PM series by whole sessions (≥ 5 sessions apart, 1,000 draws, fixed seed). A "clear link" needs the peak bar plus an adjacent bar both outside the band with the same sign (the dashboard rule).

**Chart 2 (event study), per ticker, exploratory:** for Fed and CPI, the cumulative ticker return from −3 to +6 bars around each event, signed by the direction of the PM move in the hour before. Mean, with a 90% bootstrap CI over events. For BTC, the largest 20 hourly |Δln ladder| moves.

**Verdict rules (computed, per pair):**

| Primary result | Verdict |
|---|---|
| fewer than 12 events (CPI/Fed) or the CPI method validation fails | Too early to tell |
| BTC: significant without the spot control, not with it | No extra information |
| BH-significant, correct sign, placebo passes (if any), and the lag-1 or lag-2 coefficient individually > 0 at p < 0.10 | Polymarket moves first |
| BH-significant, but only the lag-0 coefficient carries it | Moves at the same time |
| not BH-significant, with enough data | No head start (new label; the tally already uses "no head start") |

Note: PM prices are ~10 min older than the stock bar end (step-4 m3), so "moves at the same time" may hide a lead of under 10 minutes. The dashboard's "for experts" note says so.

**Confidence rules:**

| Condition | Level |
|---|---|
| below the event minimum | Not enough data |
| pair 4, or not BH-significant | Low |
| BH-significant, placebo passes, and the sign holds in the age-900 robustness run | Medium |
| as Medium, plus BH p < 0.01 and ≥ 30 events (or ≥ 20 for CPI) | High |

**Checklist rows (per pair):** primary test, multiple-testing correction, placebo/control, robustness (age 900), and enough events. Each is Passed, Failed, Weak, Not needed or Not run, by the rules above.

## Build rules as examples (each becomes a test)

| Input | Expected |
|---|---|
| synthetic: PM change leads the return by 2 bars, n = 3,000, noise sd = 1 | xcorr peak at +2 with +2 and +1/+3 outside the band; Fed-style regression p < 0.01 |
| synthetic: independent noise | no bar pair outside the band in ≥ 90% of 100 seeds; regression p is roughly uniform (KS p > 0.05 over 200 seeds) |
| a lag that would cross the overnight gap | NaN, dropped |
| BTC synthetic where the PM change = the spot return + noise, with no extra effect | significant without control, not with it → "No extra information" |
| BH with p = (0.004, 0.03, 0.2), q = 0.10 | the first two are rejected, the third is not |
| CPI with 12 releases where validation fails | verdict "Too early to tell", and chart titles marked as previews |

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
- [ ] A27 is approved by the user and recorded in the prereg BEFORE any return is examined (commit order shows it)
- [ ] Every example row is a test; planted lag recovered; noise gives nothing
- [ ] Results JSON validates against the contract and the dashboard renders it for all 4 pairs
- [ ] Verdict, confidence and checklist are computed by code, never hand-written
- [ ] The step-5 dashboard minors listed above are fixed
- [ ] Build report ≤250 words; full report `docs/reviews/step6_build_r1.md`

# Step 6 validation, round 1

Date: 2026-10-08. Validator: fresh context, did not write the code. Branch `step6-analysis` at c6191cd.
Scope: `docs/handoff/step6.md` (incl. "Build status for validation"), prereg A27 + A28, `docs/reviews/step6_a27_review.md`, `docs/reviews/step6_build.md`, the diff master..HEAD, the real results in `data/clean/results/`.

## Verdict

**FAIL: 1 blocker, 1 major, 9 minors.**

The code implements A27 as amended by A28 faithfully. I found no silent deviation and no look-ahead. The synthetic calibration claims hold, the key guards are mutation-tested, and the real results rebuild byte-identically. The problem is what gets published:

- **BTC.** The BTC primary coefficient (−39.9 bp per 1%, t = −7.4) is a mechanical artifact of the 30-min-stale hourly spot control, which the prereg itself specifies. A zero-information simulation reproduces it. So the BTC verdict "No head start" ("the data rule out a lead of the size we could detect") follows the rules but is not supported by the evidence.
- **Dashboard headlines.** The card and verdict-panel headlines come from the exploratory Chart 1 of the first-listed ticker, not from the pre-registered verdict.

## Checked (evidence)

| Item | How | Result |
|---|---|---|
| Standard checks | `bash scripts/check.sh` | 431 passed (5 min 38 s), ruff check and format clean, pairs.yaml reproducible, ingest dry-run planned 106 calls. **PASS** |
| Results reproducible | Copied the panels to a scratch dir and ran `python -m poly_actor.analysis run --workers 4 --clean-dir <scratch>` (38 s) | All 4 pair JSONs and summary.json **byte-identical** (`cmp`) to `data/clean/results/` |
| Mutation tests (monkeypatched, scratch scripts) | `design_mask` without the lag-row filter; `lag` crossing sessions (flat shift); BH replaced by Bonferroni; BH replaced by uncorrected testing; CPI margin 0.72; relative placebo gating nulls; opposite-sign disabled; Fed b1+b2 gate removed | **All 8 killed** by the intended tests. The contemporaneous test fires 167/200 without the gate (limit 16). |
| A27 rule 1 / B1 | Read `sample.py`: grid before filter, `design_mask` requires `row_ok` at the row and every PM lag cell. The B1 test and its mutation pass. | OK |
| Rule 2 | HAC lag ⌊4(2404/100)^{2/9}⌋ = 8 matches the JSON. Sum, lead and b0 tests with 90% CIs. | OK |
| Rule 3 | Spot controls in clock time, strict as-of. `spot_obs` restamps BTC-USD to the bar END (`pipeline.py:75-80`). n = 1,317 (4 rows lack spot). | Implemented as written (but see B1) |
| Rule 4 / CPI | Release − 60 min from the price book; 5 sessions back at the same ET clock (zoneinfo). Validation 10/12. I recomputed the Fisher interval: n = 12, ρ = −0.294 → [−0.700, 0.256], so the upper bound 0.70 > 0.5 gives underpowered. | OK |
| Rule 6 BH | Recomputed adjusted p from (0.349, ≈1, 0.177): 0.5235 / 1 / 0.5235. | Matches summary.json |
| Rule 7 + A28 verdict per pair | **Fed:** not BH-significant; placebo p = 0.349 fails but does not gate (A28.2); upper r = t_to_r(0.388 + 1.645, 2400) = 0.0415 < 0.051 → "No head start", Low. **BTC:** XLU two-sided p = 0.74 passes; no-control one-sided p = 0.846, so rule 4 does not apply; upper r < 0 < 0.068 → "No head start"; primary row "Failed (opposite sign)". **CPI:** "Too early to tell (underpowered)". **Recession:** "Descriptive only", Low. | All follow the rules literally |
| A28.1 calibration | Tests `test_realistic_null_rejection_rate`, `..._band_exceedance` (1,000 seeds), `test_realistic_null_fed_shift_placebo_rate` (200 seeds, HAC t) are in the passing suite | OK |
| Planted lag / noise | `test_planted_two_bar_lead_is_recovered`, `test_chart1_band_power_at_fed_size`, contemporaneous ≤ 16/200 | OK |
| Look-ahead | Lags are same-session and earlier only. Spot and PM as-of are `searchsorted(side="right") − 1` (at or before). CPI levels are at release − 60 min. Pair-4 days end at the close. BTC events are chosen on PM changes only. Residualising uses a full-sample beta (a regression adjustment, not a time leak). | None found |
| Dashboard on real results | AppTest on `data/clean`: every card button and every ticker of the picker. I also printed headline, tally, findings and checklists from `text.*`. | No exceptions. Text issues in M1 and m1–m3, m5. |
| Secrets / data in git | Grepped the diff for key/secret/token patterns; `data/` is git-ignored | Clean |

## Issues

### B1 (blocker). The BTC primary is mechanically biased negative by the stale spot control, so "No head start" is not supported

**Where:** `src/poly_actor/analysis/primary.py:167-185` (`spot_controls`), as specified by A27 rule 3 ("at :30 stamps the lag-0 control covers [t−90m, t−30m]"). Published as the BTC verdict and reason (`verdict.py:93-95`), the checklist rows "Failed (opposite sign)" and the residualised Chart 1 panel.

**Evidence on real data** (scratch `btc_diag.py`, HAC, n = 1,317):

```
IBIT_t = −39.9·ΔPM_{t−1} (t=−7.4) + 0.528·s0 (t=18.9) + 0.177·s1 (t=6.0) − 0.007·s2 − 0.020·s3
no control: ΔPM_{t−1} = −6.4 (t=−1.0)
corr(ΔPM_{t−1}, s1) = 0.587, corr(ΔPM_{t−1}, s0) = 0.164
```

IBIT_t spans [t−60, t]. ΔPM_{t−1} is about 10 min stale, so it spans about [t−130, t−70]. The hourly-close controls are s0 = [t−90, t−30] and s1 = [t−150, t−90]. Conditional on s0 and s1, a larger ΔPM_{t−1} means more of each block's move fell inside [t−130, t−70]. That leaves less of s0's move in the part that overlaps IBIT. The result is a negative "suppressor" coefficient even when the odds contain no information.

**Repro (zero-information simulation**, scratch `btc_sim.py`, 50 seeds): minute random-walk spot; IBIT = spot over [t−60, t] + noise; ΔPM_{t−1} = spot over [t−130, t−70] + noise; controls built exactly as in `spot_controls` (hourly closes, as-of at :30). Result:
- PM coefficient negative in **50/50** seeds, mean t = −18.8;
- control coefficients s0 ≈ 0.56 and s1 ≈ 0.11, matching the real 0.53 and 0.18;
- corr(ΔPM, s1) ≈ 0.54, against 0.59 on real data.

Adding a control spanning [t−30, t+30] (diagnostic only) does not remove it on real data (−42.2, t = −8.2).

**Consequences:**
1. The upper bound used for "No head start" (rule 5) is biased down by construction. Under this design, "No head start" is almost guaranteed whatever the true lead, so the reason "The data rule out a lead of the size we could detect" is unsupported.
2. "Failed (opposite sign)" reads to a lay reader as "the odds predict the opposite", which is an artifact.
3. The same bias drives the residualised Chart 1 for IBIT, COIN and MSTR. Lag +1 is outside the band and negative: IBIT t = −5.0, COIN t = −4.1. The exploratory BH rejections for `btc_COIN_lag1` and `btc_MSTR_lag1` (p ≈ 5e-10 and 1e-11) are very likely the same artifact.
4. The synthetic BTC test (`tests/test_analysis_synthetic.py`, `test_btc_odds_that_only_echo_spot...`) uses bar-aligned iid spot, so it could not catch this.

**Fix (user decision, dated amendment, explicitly labelled as made AFTER seeing results):**
- (a) Keep the frozen computation but publish BTC as "Too early to tell", reason "the pre-registered spot control is misaligned with the ETF bar, so the test is biased (see A29)". Keep the literal verdict in the JSON, as was done for `verdict_if_placebo_read_literally`.
- or (b) Re-specify the control with spot aligned to the bar: e.g. exchange minute klines for BTC-USD over exactly [t−60k−60, t−60k], or as-of at the :30 instants from a sub-hourly source. Add a test with sub-hour timing like `btc_sim.py`, then re-run. Any (b) result must be labelled post-hoc.

Either way, remove the "rule out a lead" wording for BTC until the test is valid.

### M1 (major). Card and verdict-panel headlines come from exploratory Chart 1 of `tickers[0]`, not from the pre-registered verdict

**Where:** `src/poly_actor/dashboard/text.py:303-311` (`finding` returns `xcorr_title` whenever an xcorr exists), `app.py:117` and `app.py:231` (`spec.tickers[0]`), `chart_text.py:89` and `chart_text.py:106-114`.

**Repro (real results):**
- **BTC card:** "Bitcoin price odds and COIN (Coinbase) move in the same hour, so neither gets a head start". COIN is listed first in pairs.yaml, but the primary ticker is IBIT (main's Q3: confirmed). It is also read from the residualised panel that B1 contaminates; that panel has lag +1 outside the band.
- **Fed card and verdict-panel title:** "Fed odds and TLT move in the same hour, so neither gets a head start", with so-what "The odds work like a mirror … they show what the market is already pricing in". The pre-registered sum test is null (p = 0.35, Low confidence). The lag-0 bar is only marginally outside the band (|t| 2.89 vs 2.77). b0 alone has one-sided p = 0.025, unadjusted and not in any family. Stating a contemporaneous link and a "mirror" interpretation as the headline finding overclaims an exploratory chart (main's Q2: yes, overclaim).
- **BTC-USD picker:** "Bitcoin price odds give no head start on BTC-USD", but spot was never a tested target.

**Fix:**
- Card and verdict-panel headline = the verdict sentence for the pair's **primary ticker**. Add a `primary_ticker` to the contract or derive it from `ticker_roles`.
- Chart 1 titles say "exploratory", e.g. "Strongest link is in the same hour (exploratory)", and drop "so neither gets a head start" unless the verdict says so.
- No verdict sentence for control or baseline tickers.

### Minors (carry to the next hand-off)

- **m1.** `results.py:151-152` and `results.py:292-293`: the Fed and CPI "Placebo" rows show "✗ Failed" ("Link vanishes when timing is scrambled") on null primaries, where A28.2 says the placebo is reported, not used. A lay reader sees a failed check. Use "Not needed" (or "Reported only") when `not bh_reject`, as the "Odds move first" row already does.
- **m2.** `primary.py:225`: BTC R3 is a placeholder `{"holds": True}`. The checklist prints "R3 holds", and the plain text says "without event days" for BTC. Use "Not applicable" and a per-pair plain text.
- **m3.** Fed and CPI Chart 2 are empty on real data. For Fed, 2 of 16 events are signed and 14 unsigned (scratch `ev_diag.py`; expected per m11). `results.event_json` returns None, so the unsigned and dropped counts that A27 rule 13 requires are **not written** anywhere. The dashboard shows only a generic "Not computed for this stock". Write the counts and give the reason.
- **m4.** `verdict.py:90`: `(f.nocontrol_p or 1.0)` turns p = 0.0 (underflow) into 1.0. Repro: `Facts(pair="btc", sufficient=True, placebo_pass=True, nocontrol_p=0.0, upper_r=0.01)` → "No head start"; with 1e-300 → "No extra information". Use `is None`.
- **m5.** `results.py:92`: "Enough cases to be sure" overclaims ("Enough data for the test").
- **m6.** The synthetic BTC test generator uses bar-aligned spot. Add a sub-hour timing case (lesson for `lessons.md`: "Controls must cover the same clock window as the outcome; a stale coarse control creates suppressor coefficients").
- **m7.** `verdict.confidence`: when `placebo_pass is None` (placebo not computable) and the primary is BH-significant, Medium is reachable with no placebo. Rule 10 needs "placebo passes".
- **m8.** `run.py:_spot_gap`: the BTC overnight spot control uses the as-of at 09:30, which is the 09:00 close, against an IBIT gap to 09:30. The same 30-min misalignment as B1, in an exploratory test.
- **m9.** Exploratory BH rejections `fed_overnight_TLT` and `btc_overnight_IBIT` (no control) are same-window "moves with" results. Make sure no dashboard text later presents them as timing evidence. They are not shown now.

## Answers to main's questions

1. **BTC lag-1 = −39.9 with control, ≈ 0 without: real or mechanical?** Mechanical. The stale and coarse spot control creates a suppressor effect, and a zero-information simulation reproduces the sign and the control coefficients (B1). Under rule 7 as written, "No head start" is the literal output: rule 4 does not fire (no-control p = 0.85), and rule 5's upper bound is negative. But that bound is invalid, so the verdict should not be published as a null. User decision needed.
2. **Fed "move in the same hour" on a null result: overclaim?** Yes (M1). It is an exploratory, marginal Chart 1 reading promoted to the headline, with an untested "mirror" interpretation.
3. **BTC card names COIN, not IBIT?** Confirmed: `app.py:117` uses `spec.tickers[0]`, and COIN is listed first in pairs.yaml (M1).

## Not checked

- A real-browser render (sticky tabs, scroll), as before.
- Plotly figure content beyond the absence of exceptions in AppTest.
- Independent recomputation of the FFT shift statistics. I relied on the oracle tests in the suite plus the byte-identical rebuild.
- The CPI release table levels against the price book (I took the validity counts from the build report and the rebuild).
- The pair-4 BCa numbers.
- Whether a sub-hour BTC spot source exists in `data/raw` (it would be needed for fix B1(b)).

# Step 8 + 9 validation, round 1 (election study: data + analysis)

Validator: independent, did not write the code. Commit under review: fd403bd. Commit c7363ff landed
while the review was running (it drops `meta.generated_at` and the `today` argument). The determinism
check below was run at c7363ff. Everything else was checked against fd403bd, and the analysis
code is otherwise identical in both commits (`git diff fd403bd c7363ff -- src` touches only those lines).

## Verdict
**PASS WITH ISSUES**: no blockers and no majors. 8 minors (below), carried to the step 10 hand-off.

The headline verdicts follow the pre-registration table mechanically and are reproduced
independently: H1 "Too noisy to tell" (Low) and H2 "Betas did not predict election night" (Low).

## Checked (evidence)

### Tests
- `tests/test_election_config_ingest.py`, `test_election_panel.py`, `test_election_resolved.py`,
  `test_election_stats.py` and `test_election_analysis.py` all pass. The two step 9 analysis files
  plus `test_election_resolved.py` give 51 passed in a clean copy of fd403bd. The whole suite and
  `scripts/check.sh` were not run, as instructed, because the dashboard build is concurrent.

### Step 8 data
- **Odds spot checks, from an independent CLOB re-fetch** (`prices-history`, last point at or
  before the close). Each matches the panel in both p and age_s:
  - 2025-11-03 21:00Z: 0.295 / 593 s. This is the first session after the DST end, so the close
    is at 21:00Z. 2025-10-31, before the switch, has its close at 20:00Z in the panel.
  - 2025-11-28 18:00Z (early close): 0.34 / 590 s.
  - 2026-03-06 21:00Z: 0.435 / 575 s, and 2026-03-09 20:00Z: 0.465 / 573 s. These are the two
    sides of the 2026 DST start.
  - 2026-11-03 21:00Z (fid 1): 0.745 / 40 s. This confirms A1's correction of the scouting number.
  - 2026-11-04 21:00Z: 0.9995 (last trade, A1).
  - 2025-07-18 20:00Z: 0.50 / 592 s.

  In every case the first point after the close is a different point that is not used.
- **Return spot checks, from an independent yfinance 1d auto_adjust re-fetch.** All are identical
  to 6 dp:
  - NVDA 2026-03-09: +0.026800
  - KO 2025-11-28 (early close): +0.003288
  - MSFT 2025-12-24 (early close): +0.002400
  - AMD 2026-11-04: +0.010034
- **Hourly bars are end-stamped.** NVDA on 2025-10-31: first bar ends 14:30Z and last bar ends
  20:00Z. 2025-11-03: 15:30Z to 21:00Z. 2026-03-06: last bar ends 21:00Z. 2026-03-09: 14:30Z to
  20:00Z. On the 2025-11-28 early close the last bar runs 16:30Z to 18:00Z (11:30 to 13:00 ET).
  Hourly `ret` is log(close/open) within a bar, so it never spans sessions.
- **A1 resolved rule.** `ResolvingBook` (`panel.py:67-94`) switches to the uncapped book only at
  instants ≥ `closed_s`, and only reads points ≤ the instant. On 2026-11-03 the reading is
  unresolved (age 40 s). 2026-11-04 is resolved (0.9995, age 36,341 s, dp +0.2545), and 5–12 Nov
  have dp 0. Mutation: applying A1 from one day before the close fails
  `test_session_after_close_takes_last_traded_price_and_is_flagged` (killed).
- **Missing odds are never filled with 0.** 2025-07-14..18 have no dp and drop out. My own dropna
  sample has n = 325 (2025-07-21..2026-11-02), the same as `results.json`. The first bar of every
  hourly session has dp NaN (366/366 sessions). RSP and NVDA hourly bars are all on the odds
  grid.

### Step 9: implementation against the pre-registration
- **H1.** Spec `r_AI ~ ΔP_sen + r_RSP + r_TLT`, NW-HAC with 5 lags, pre-sample 2025-07-14..2026-11-02.
  Circular shifts of x only, minimum 20, 1,000 draws, p = (1+hits)/1001. The placebo row and the
  difference regression are present. MDE80 = 2.80·se. All match the pre-registration.
- **H2.**
  - Estimation sample: `H2_EST_END = "2026-10-30"` (`analysis.py:39`), so b_i is estimated on
    324 sessions ending 2026-10-30.
  - `AR = r − c·r_RSP − d·r_TLT`, with no intercept and no b·ΔP term, as written in the
    pre-registration.
  - Inference: one-sided label-permutation p from 10,000 draws, with the two-sided p beside it
    (A1). There are three windows, and the primary one is close3→close4.
- **H2b.** b_i uses rows `[:t]` (`stats.py:245`). The decile is computed over `a[:t+1]` (to date),
  and selection starts at usable row 121.
- **Holm** is applied to {H1 p_perm, H2 p_one}, with a first threshold of 0.025. The verdict
  functions (`stats.py:293-319`) implement the table row by row.
- **H4.** Residuals use RSP and TLT log(close/open) from the same bar, so the control is on the
  same clock window as the outcome. Lags are formed with `lag_within` on a sessions × positions
  matrix (`intraday.py:37-47`), so no lag crosses a session. `lag_scan` uses it
  (`intraday.py:77`). The verdict function is equivalent to the pre-registered wording: a larger
  |t| has a smaller BH p.
- **Labels.** H3 is labelled "descriptive only", H4 and H5 "secondary", and E1–E5 "exploratory".

### Independent recomputation (own numpy/scipy script; no project estimator)
| Quantity | Mine | results.json |
|---|---|---|
| H1 AI b per +10 pts | **−0.5660%** (se 0.6568, t −0.862) | −0.5660% |
| H1 90% CI | [−1.646, +0.514] (normal) | [−1.649, +0.517] (t dist) |
| H1 MDE80 | 1.840% | 1.840% |
| H1 placebo b | +0.0147% | +0.015% |
| H1 perm p, exact over all 286 admissible shifts | 0.491 | 0.507 (1,000 draws with replacement) |
| H2 ρ (AI, close3→close4) | **−0.3719** | −0.3719 |
| H2 p_one / p_two (200k perms) | 0.976 / 0.048 | 0.975 / 0.047 |
| H2 placebo ρ | +0.0015 | +0.002 |
| Event ΔP_sen | 0.745 → 0.9995 = +0.2545 | +0.2545 |
| H2b (≥ rule) | n 74 of 205, mean 0.0485, t 1.21, p 0.115 | identical |

### Mutation tests (clean copy of fd403bd, bytecode disabled, restored after each)
| Mutation | Result |
|---|---|
| `H2_EST_END` → 2026-11-02 / 2026-11-03 | killed (`test_h2_estimation_ends_2026_10_30...`) |
| H2b estimates on `[:t+1]` (includes day t) | killed (`test_walk_forward_day_t_is_not_in_its_own_estimation`) |
| H2b decile over the full sample | killed |
| Holm threshold = α | killed |
| `h2_passes` ignores the sign of ρ | killed |
| A1 applied one day before the close | killed |
| `circular_perm_p` minimum shift 20 → 1 | **survived** (minor m1) |
| `lag_scan` uses a flattened `np.roll` (lags cross sessions) | **survived** (minor m2) |

### Synthetic recovery
The planted H1 beta, cross-section, H4 odds-first/stocks-first/moves-with and the Wald test are
all recovered. Noise gives 0–14/100 rejections, a uniform label-permutation p, and no H4
ordering. All of these pass.

### Determinism
`analyse()` was run twice at c7363ff into separate scratch directories. The sha256 of all 10
files is identical between the two runs and identical to `reports/election/`.

### Builder deviations
- **H2b tie rule (≥ selects 74/205 = 36% of days).** I recomputed with a strict `>` rule: 32 days,
  mean +0.013, p = 0.41. Under either rule p ≥ 0.10. H2b only feeds confidence when H1 or H2
  passes, and neither does. The rule was disclosed in A2 and fixed before the real run, so it is
  honest and harmless to the verdicts. It is still not "top decile" in spirit, and a future
  study should break ties.
- **H1 power-test noise 0.004 → 0.003.** The hand-off did not fix the noise level, and the change
  only affects a synthetic test, not real-data code. Harmless. The builder's power arithmetic
  (t ≈ 2.7 → about 77% power) is right.

### Overclaiming
The headline sentence quotes only the verdict-table outcomes and numbers. The negative ρ is
described as the wrong tail and "not a finding" in A2, the build report and the checklist. The
two-sided p appears only as `p_two`. E1 is called post-hoc.

## Issues

### Blockers
None.

### Majors
None.

### Minors
- **m1. Permutation min-shift guard is untested.** `stats.py:123` (`circular_perm_p`): changing
  the minimum shift to 1 inside the permutation passes all tests.
  `test_circular_shifts_respect_the_minimum` only tests `admissible_shifts`.
  **Fix:** a test that a series with n < 40 gives NaN from `circular_perm_p`, or that the draws are
  a subset of the admissible set.
- **m2. H4 session-crossing guard is tested only at the helper level.** `intraday.py:77`: replacing
  `lag_within` in `lag_scan` with a flattened `np.roll` (lags that cross sessions) passes all tests.
  The step 9 report's "hourly lag crossing sessions … killed" holds only for a mutation inside
  `lag_within`. **Fix:** an `h4()`-level test where the only dependence is the previous session's
  last bar → next session's first bar, asserting the n per lag and no detection.
- **m3. A launch-price artefact enters H1.** `odds_daily` on 2025-07-21: dP_sen = −0.21
  (0.50 → 0.29). This is opening price discovery: the 0.50 runs from 18:24Z on 07-18 and drops
  to 0.29 overnight on 19 Jul. It is the largest |ΔP| in the sample, 2.6× the next. It is in-rule
  and covered by the "drop 5 largest" row. Dropping that single day moves b from −0.57% to
  −1.10% (t −0.94), so the verdict is unchanged. **Fix:** disclose it in the findings text next
  to the drop-5 row.
- **m4. H2's two-sided p is a Monte Carlo value at the 0.05 line.** It is 0.047 at 10k draws and
  ≈ 0.048 at 200k draws, so its MC error straddles 0.05. Since it is exploratory, the dashboard
  should not render it as "p < 0.05" or "significant".
- **m5. E4 rows have no exploratory label of their own.** In `results.json → robustness`, the E4
  rows carry no `label` field. Only the name prefix "E4" and `exploratory.e4.see` mark them. The
  contract says every exploratory block carries `"label": "exploratory"`. **Fix:** add a `label`
  per robustness row (`robustness` / `exploratory`).
- **m6. `meta.preregistration` omits A2.** `analysis.py:314` says "amendment A1"; A2 exists.
- **m7. Stale comment about `closed`.** `config/election.yaml:4` says `closed` is "never [used]
  to select data at t". Since A1 it does select data, legitimately: an instant ≥ closedTime is
  known to be after the close. Update the comment.
- **m8. Thin noise and wording checks.**
  - `test_h4_noise_no_ordering` uses a single seed.
  - The H1 noise test uses 400 shifts, not 1,000.
  - The build report's "Wald p = 0.020 … says the sub-baskets' betas differ" should carry
    "secondary, single uncorrected test, composite b is null" wherever the dashboard shows it.

### Disclosed and accepted (no action)
- Odds sit about 10 minutes stale at every close and bar end (median age_s 590). This is the
  fid-60/fid-10 grid with strict as-of, measured and reported in step 8 (lesson 10), and it
  slightly biases H4 toward "odds lag". H4's verdict is "no detectable ordering", so it is
  unaffected.
- The H1 permutation draws with replacement from 286 shifts (A2). Exact enumeration gives 0.491
  against 0.507: same conclusion.

## Not checked
- The whole test suite and `scripts/check.sh`: skipped by instruction (concurrent dashboard build).
- Ingest idempotency (zero calls on a second run): not re-run.
- Gamma token-id matching beyond the p_sen token used in the re-fetch.
- Moratorium tokens, the vol-index pulls, and the H3 night numbers (I did not recompute H3 or E1–E5).
- H5 Wald statistic and H4 per-lag coefficients: implementation read, values not recomputed.
- The dashboard files (`app.py`, `charts.py`, `report_text.py`): out of scope.

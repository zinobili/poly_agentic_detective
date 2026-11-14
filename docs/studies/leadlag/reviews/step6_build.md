# Step 6 build report (analysis), round 1

Date: 2026-10-07. Branch `step6-analysis`. Builder: quant-researcher.

## Status in one paragraph

The analysis code, the results contract v2 and the dashboard changes are complete and tested
on synthetic data (hand-off order step 1). The CPI usable count was computed from validity
flags only (step 2). **The real panels were NOT analysed (step 3 not run), so no return-based
result exists yet.** One frozen A27 method fails its own pre-registered acceptance test. If the
real run happened first, any fix would be chosen after seeing results. Three decisions (D1-D3
below) are needed first. Once they are made, the run is a single command:
`python -m poly_actor.analysis run --workers 4`.

`bash scripts/check.sh`: **PASS** (419 passed, 1 xfailed; ruff clean; pairs.yaml reproducible).
The xfail is strict and is the open D1 item.

## Decisions needed (before any real return is examined)

### D1 (blocks the real run): the Chart 1 band and the Fed shift placebo are miscalibrated under realistic data

Hand-off row 3 ("realistic null ... band exceedance within [3%, 7%]") fails for the A27 rule 12
band as frozen:

| Null (500 sessions, fixed seeds) | Band exceedance (target 3-7%) | Fed shift-placebo rejections at 5% | HAC primary rejections at 5% |
|---|---|---|---|
| Realistic: 70% zero ΔPM + t(3) jumps, GARCH(1,1)-t(4), **shared** volatility (1,000 seeds) | **15.8%** | **9.7%** (300 seeds) | 6.0% (passes [3%, 8%]) |
| Gaussian iid (300 seeds) | 4.0% | 6.3% | 7.7% |
| Realistic, but PM and returns with **independent** volatility (300 seeds) | 4.3% | n/a | n/a |

Cause: a circular session shift breaks the co-movement of volatility between the odds and the
stock. At the true alignment, Var(Σ x·y) carries E[σ⁴]. Across shifted sessions it carries only
E[σ_s²]·E[σ_s'²]. The shifted r's are therefore too narrow, and the band is too tight. The HAC
primary regression is unaffected. Real Fed/CPI days very likely have shared volatility (both
markets move on the same news), so this matters for real data.

Effect if left as is: the Chart 1 "clear link" title and the exploratory `stocks_first` label
fire about 3x too often under no relationship. The Fed placebo (rule 11) passes too easily,
which weakens a check that guards a "moves first" verdict. The verdict itself rests on the HAC
primary, which is calibrated.

Options (none is implemented; A27 is unchanged):
- **(a)** Keep A27 as frozen and print the measured miscalibration next to Chart 1 and the Fed
  placebo. The xfail stays.
- **(b) Studentize (tested in a scratch experiment, not in the repo).** At each lag, use the
  heteroskedasticity-robust t = Σ(x−x̄)(y−ȳ) / sqrt(Σ(x−x̄)²(y−ȳ)²), and make the band the 95th
  percentile of max|t| over the same shifts. Measured exceedance: **3.7%** under the realistic
  null and 4.3% under the Gaussian null (300 seeds each). Chart 1 could still draw r and colour
  the bars by |t|. For the Fed placebo, use the HAC t of b0+b1+b2 as the shifted statistic
  instead of the raw sum (same logic, not yet measured).
- **(c)** Drop the shift band and the Fed shift placebo from the verdict path. Chart 1 becomes
  purely descriptive.

Whichever option is chosen should be a dated amendment (A28) made before the real run.

### D2: the relative placebos (Fed shift, CPI random dates) as a verdict gate

Under A27 rules 7.3 + 11 read literally, a placebo "passes" only when the real statistic beats
the 90th percentile of the placebo distribution. Any non-significant primary therefore "fails"
its placebo, and lands on "Too early to tell, placebo failed". "No head start" becomes
unreachable for Fed and CPI. Hand-off row 9 ("CPI null → Too early to tell (underpowered)") can
only pass if this gate is not applied to nulls.

**Implemented (decided blind, needs your confirmation):** the Fed and CPI placebos gate the
verdict only when the primary is BH-significant. For a null they are reported, not used. BTC's
XLU control (an absolute negative control) always gates, as written. The literal-reading verdict
is also computed and written to each results file (`verdict_if_placebo_read_literally`), so
either reading can be adopted later without re-running anything
(`verdict.RELATIVE_PLACEBO`, `verdict.placebo_gates`).

### D3: CPI "No head start" margin, 0.72 (rule 5 MDE) vs 0.5 (B3 wording)

Rule 5 says a non-significant primary is "No head start" when its one-sided 95% upper bound is
below the MDE (CPI 0.72). The adopted B3 wording says CPI is "underpowered unless the 90% CI
excludes ρ ≤ −0.5". These are the same bound with different thresholds. With n = 11 and ρ = 0,
the rule-5 reading gives "No head start" and the B3 reading gives "underpowered". The hand-off
row 9 example requires the latter. **Implemented: 0.5 (B3)** as `verdict.NULL_MARGIN["cpi"]`.
It is the stricter of the two, so it never claims a null that rule 5 would not. The test pins
the disagreement (`0.5 < upper bound < 0.72` for the row-9 case).

## Other interpretations made blind (no decision needed unless you disagree)

1. **Effect bounds in correlation units (rule 5, 10):** the HAC t of the tested combination is
   mapped to a partial r, r = t / sqrt(t² + df). This is the unit in which the MDEs were derived
   (0.051 ≈ 2.487/√2404). Upper bound = r at t + t₀.₉₅; lower bound = r at t − t₀.₉₅.
2. **Fed placebo statistic** = OLS b0+b1+b2 (the "primary sum statistic" of M6), not its t
   (this is D1-relevant).
3. **R2 robustness** drops ceil(1%) of rows, ranked by the largest |ΔPM| among a row's PM
   regressors. For CPI it drops 1 of 12 releases. CPI has no R1/R3 (one row per release), so
   they count as holding.
4. **BH-significant but robustness fails** → confidence Low (rule 10 does not list this case).
5. **Checklist "Weak"** (display only): primary not BH-significant but one-sided p < 0.10.
6. **BTC no-control model** uses the same rows as the control model (1,317 rows), so the two
   coefficients are comparable.
7. **Exploratory family** (second BH, separately labelled): Fed SPY sum, Fed XLF−SPY sum, Fed
   overnight TLT, CPI QQQ Spearman, BTC COIN, MSTR, IBIT lag 2, IBIT lag 3, IBIT no-control,
   BTC overnight with and without the spot control. All use **two-sided** p. The overnight test
   is run on the primary ticker only (TLT, IBIT).
8. **Chart 2 details A27 leaves open:** the BTC window is −3..+6 bars (Fed's), and the BTC gaps
   are folded into the first bar of the new session and marked per path. CPI signing uses the
   "bar before bar 0" literally, i.e. the previous session's 15:30-16:00 bar. The random-date
   band is 1,000 random sets of non-event paths, matched to each event's bar position, and the
   mean is taken per set (comparable to the plotted mean). Charts need ≥ 5 signed events.
9. **Pair 4 day:** the ΔP between consecutive session closes (16:00 ET, or 13:00 on early
   closes). It is the sum of the spliced hourly changes in between, and NaN if any hour is
   missing. The Δlogit sensitivity sums per-row logit changes of the same event, so it never
   differences across the roll.
10. **CPI placebo sessions** are evaluated at 07:30 ET (release − 60 min clock) and 5 sessions
    earlier, with the same active event, through the same price-book evaluator.

## Step 2: CPI usable count (validity flags only, exact instants from the price book)

Pre-release level at exactly release − 60 min (07:30 ET). 5-day level at the same ET clock 5
XNYS sessions earlier (DST-safe), same `event_id`. Quote ages at release − 60 min are 18-58 s
(fid-1 points), and about 590 s five sessions earlier.

| Event | Release (ET date) | release − 60 min | 5 sessions earlier | Usable |
|---|---|---|---|---|
| 2024-11 | 2024-12-11 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2024-12 | 2025-01-15 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2025-01 | 2025-02-12 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2025-02 | 2025-03-12 | ok | ok | yes |
| 2025-03 | 2025-04-10 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2025-04 | 2025-05-13 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2025-05 | 2025-06-11 | ok | ok | yes |
| 2025-06 | 2025-07-15 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2025-07 | 2025-08-12 | ok | ok | yes |
| 2025-08 | 2025-09-11 | ok | ok | yes |
| 2025-09 | 2025-10-24 | ok | ok | yes (the review's borderline case is valid at the exact instant) |
| 2025-11 | 2025-12-18 | ok | ok | yes |
| 2025-12 | 2026-01-13 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2026-01 | 2026-02-13 | ok | ok | yes |
| 2026-03 | 2026-04-10 | edge_mass_gt_max | edge_mass_gt_max | no |
| 2026-04 to 2026-08 (5 releases) | | ok | ok | yes |

**12 of 20 usable** (≥ 10, so the test runs). The 2026-09 event (release 2026-10-14) is after
the data end.

**Validation (prereg Pair 3, A27 denominator): PASS.** 12 valid months, 10 within 0.1 pp of the
winning bucket centre (> 6, and ≥ 8 valid). The two misses are 2025-11 (implied 3.00 vs 2.7) and
2026-06 (3.81 vs 3.5). This uses PM levels only.

TLT opening-gap availability on these 12 sessions is a return-side read and was not checked.
The run drops a release whose gap is NaN and reports the count (`usable_without_gap`).

## Sample counts (flags and presence only)

- Fed primary (lags 0-2): **2,404 rows in 497 sessions**, as A27 counted. Age-900 run: 2,359
  (45 rows, 1.9%). Rule 1 reconstructs `both_trading` exactly on all four panels.
- The lag-window guard **fires on real data**: it removes 30 Fed rows whose own filter passes,
  28 of them because a lag row is a PM-excluded (decision, roll or stale) row. 18 are 15:30
  bars, which includes the 16 FOMC-day bars of review B1. No kept row has an excluded bar in its
  lags.
- BTC primary: **1,321 rows** with the session rule on the PM lag only (A27). 1,317 once all
  four clock-time spot lags must be present (4 rows lack a spot quote within 3 h); 254 sessions.

## Hand-off rows → tests (all on fixed seeds)

| Row | Test | Result |
|---|---|---|
| Planted 2-bar lead, β = 0.1 SD | `test_planted_two_bar_lead_is_recovered` (1,000 sessions) | peak at +2 outside the band, lead p < 0.01 and "moves first" each in ≥ 90/100 |
| (power note) same at Fed size | `test_chart1_band_power_at_fed_size_is_limited` (500 sessions) | Chart 1 flags it in 41/100; the primary verdict "moves first" in 83/100. The row does not fix n. At the real Fed size Chart 1 has low power for a 0.1-SD single-lag lead |
| Contemporaneous only | `test_contemporaneous_effect_is_not_called_a_lead` | "moves first" ≤ 16/200 |
| Realistic null | `test_realistic_null_rejection_rate` / `..._band_exceedance` | 6.0% PASS / **15.8% strict xfail (D1)** |
| Decision bars + 15:30 drift (B1) | `test_rows_lagging_onto_decision_bars_are_excluded` + mutation test | 0 rows in; removing the lag-window check lets them in |
| Lag on a Yahoo hole | `test_lag_on_a_yahoo_hole_is_nan_not_the_previous_bar`, `test_rows_whose_lag_is_a_hole_leave_the_design` | NaN, rows dropped |
| BTC echoes spot | `test_btc_odds_that_only_echo_spot_give_no_extra_information` | no-control p < 0.01: 100/100; with-control p > 0.10: ≥ 90/100; "No extra information" ≥ 90/100 |
| BH (0.02, 0.06, 0.09) / (0.01, 0.08, 0.5) | `test_bh_*` | all three / first only |
| CPI 11 usable, null | `test_cpi_eleven_usable_null_runs_and_is_underpowered` | exact p, "Too early to tell", reason "Underpowered" (needs D2 + D3) |
| CPI validation fails | `test_cpi_validation_failure_is_too_early_and_previews` | "Too early to tell", confidence "Not enough data" (charts titled Preview) |
| Pair 4 | `test_pair4_is_descriptive_low_and_has_no_p_value_anywhere` | "Descriptive only", Low; no p-like key or "p =" text in the JSON |
| Significant opposite sign | `test_significant_opposite_sign_marks_the_primary_row` | "Failed (opposite sign)" |

Note on the BTC row: the XLU placebo passes when its two-sided p > 0.10, so an unrelated XLU
fails about 10% of the time by design (measured 90/100). The BTC row therefore runs without
XLU, and a separate test pins the XLU false-failure rate. Under a true null, any substantive BTC
verdict is reached at most ~90% of the time.

Oracle tests: the FFT cross-correlation and the FFT OLS over all shifts equal the direct loop
(1e-16). Exact Spearman equals brute force with ties. HAC(0) equals HC0. BCa coverage is
80-97/100 at nominal 90%. The DST clock shift, the clock-time spot controls crossing the open,
and the validation denominator and minimum of 8 are all checked.

## What was built

- `analysis/sample.py`: expected session-bar grid, rule-1 filter split into a stock side and a
  PM side, lags on the grid before filtering, session shifts that move the PM side only.
- `analysis/models.py`: OLS with HAC (Newey-West lag rule), session-cluster and HC1
  covariances, partial r, BH, exact Spearman (subset DP, n ≤ 12), Fisher-z and BCa intervals,
  sign test.
- `analysis/placebo.py`: Chart 1 r per lag, FFT r and OLS for every circular session shift,
  the simultaneous band, the shift placebo.
- `analysis/primary.py`: Fed and BTC regressions, R1-R3, age-900, clock-time spot controls,
  residualising, the overnight test.
- `analysis/cpi.py`: release table from the price book, validation, Spearman test, R2, the
  random-date placebo.
- `analysis/events.py`, `studies.py`: Chart 2 paths, gap steps and folding, random-date bands,
  the pair-4 study.
- `analysis/runners.py`, `verdict.py`, `results.py`, `run.py`, `inputs.py`: cores → `Facts` →
  verdict, confidence, checklist → strict JSON written atomically. CLI: `run --workers N` and
  `counts` (flags only).
- Contract v2 (`dashboard/contract.py`): "No head start" and "Descriptive only",
  `stocks_first`, `verdict_reason`, `params`, `xcorr: "not_in_plan"`, BTC `residualised` panel,
  scalar simultaneous band, `steps` with a "gap" step, `paths`, `gap_marks`,
  `band_low/high`, `compare`, and the "Failed (opposite sign)" status.
- Dashboard: "Not part of the plan" for CPI and recession, "Not computed for this stock", BTC
  shows the spot-adjusted and raw panels with the title read from the adjusted one, the Chart 2
  figure (paths, ordinary-day band, gap marker, comparison line), and the verdict reason.

## Carried-over minors

| Item | Status |
|---|---|
| step 4 m3: PM ~10 min stale | stated in Chart 1 (stocks-first note) and A27 rule 15 |
| step 4 m4: max PM age | 1800 s filter (A27 rule 1) implemented; age-900 reported |
| Glossary hard-codes parameters | `text.glossary(params)` reads lags, band, CI level, q and draws from the results; with no results it shows no numbers (tested) |
| `components.html` deprecated | replaced by `st.html(..., unsafe_allow_javascript=True)` |
| BTC-USD line breaks overnight | 24/7 tickers use every row (tested) |
| Headline overclaim with mixed verdicts | fixed: "So far no pair shows ...; k of n are still undecided or descriptive only" (tested) |
| Loose `count >= 1` test | now `== 1` on the "not computed" note in Chart 1 |
| Picker state reset | not changed (harmless, as noted) |
| Which tickers are controls | unchanged: only XLU is labelled; design question still open |
| Browser check of sticky tabs / scroll | not possible here; still open |
| streamlit pinned twice | `dev` now pulls `poly_actor[dashboard]`; `scipy>=1.13` added as a dependency |
| `load_panel` corrupt parquet | returns None and logs the path (tested) |
| `app.py` re-reads JSON | cached on (file name, mtime) |
| `_summary_lock` sleep | injectable, with a test |
| `load.py` docstrings and units | added |
| Loose dict annotations in align/cli.py | `PairSummary` alias |
| `text.py` 473 lines | split: `wording.py` (static), `chart_text.py` (chart sentences), `text.py` 353 lines |
| Module-level `main()` in app.py | documented in the module docstring |

## Self-check (step 6 checklist and lessons.md)

- Planted lag recovered; noise gives nothing: yes for the primary. Chart 1 is miscalibrated
  under shared volatility (D1).
- The results JSON validates against the contract and the dashboard renders all 4 pairs: yes,
  on synthetic results (`test_dashboard_renders_all_four_pairs`). **Not yet on real results.**
- Verdict, confidence and checklist are computed by code: yes (`Facts` → `verdict.py`;
  `results.py` has no per-pair typed labels).
- Step-5 dashboard minors fixed: yes, except the three noted above.
- No look-ahead: lags use only earlier bars of the same session. CPI and spot levels are strict
  as-of. Pair-4 days end at the close.
- Closed-market hours: lags never cross a session. Overnight moves are tested separately
  against the opening gap.
- Mutation-tested guards: the lag-window (B1) and the shift moving only the PM side. The guard
  fires on real data (30 rows).
- Raw data untouched. Only `data/clean/results/` would be written, and only by `run`.

## What this does NOT show

There is no real-data effect, sign or p-value: no return was used in any statistic. The power
numbers come from synthetic designs. The CPI validation pass says the odds track the eventual
print on 10 of 12 months. It says nothing about stocks.

## Next action

1. User decides D1 (a/b/c), D2 and D3. Main records an A28 amendment before the real run.
2. If D1 = (b): implement the studentized band and placebo statistic, then flip the xfail to a
   normal test (expect ~3.7%).
3. `python -m poly_actor.analysis run --workers 4`, then the AppTest on the real results and
   validation round 1.

## Round 1 fixes (2026-10-08, after `docs/reviews/step6_r1.md`)

No method change. BH family, A27/A28 computations and every number in the results are unchanged
(BH adjusted p: Fed 0.5235, BTC 1.0, CPI 0.5235, as before).

### B1: prereg A29 implemented
- `verdict.Facts.control_misaligned` (set by `runners.btc_facts`, default True for the
  pre-registered `spot_controls`; synthetic bar-aligned tests pass False). With it, the
  published BTC verdict is "Too early to tell", reason `A29_REASON`, confidence Low
  (`A29_CONFIDENCE`). The literal A27 verdict is kept as
  `verdict_if_a27_rule3_read_literally` (real data: "No head start").
- `primary_status` returns the new status "Not valid" (icon ⚠) instead of "Failed (opposite
  sign)" for BTC. The "Beyond Bitcoin's own price" and "Robustness" rows also read "Not valid"
  (both use the with-control model). No "rule out a lead" text for BTC.
- A29 item 3: the residualised Chart 1 panels of IBIT, COIN and MSTR carry `note` (A29_NOTE).
  The dashboard shows it as a warning above the panel, and the chart title reads "Not read as
  evidence: ..." instead of a timing reading. XLU's residualised panel is not named by A29 and
  has no note. The summary.json exploratory rows `btc_COIN_lag1`, `btc_MSTR_lag1`,
  `btc_IBIT_lag2`, `btc_IBIT_lag3` and `details.exploratory` carry the same note.
- Tests: `test_stale_hourly_spot_control_biases_the_btc_primary_negative` (minute random walk,
  zero-information odds 10 min stale, controls from `spot_controls` on hourly closes: PM t < -3
  in ≥ 19/20 seeds; minute-exact clock-hour controls: |t| < 2.58 in ≥ 18/20).
  `test_a29_publishes_the_biased_btc_primary_as_too_early_to_tell`, `test_a29_btc_publication`
  (written JSON), and verdict unit tests.
- Finding for any re-specified control (option b): with the real 30-min last bar, even
  minute-exact clock-hour lags are misaligned on that bar and the bias comes back (t ≈ -4 in a
  scratch run). A bar-aligned control must use the bar's own start and end.

### M1: headlines from the verdict
- Results carry `primary_ticker` (Fed TLT, BTC IBIT, CPI TLT, recession IWM-SPY).
- `text.finding(pair_id, results)` = the verdict sentence for the primary ticker (no ticker
  argument; no chart 1 input). `text.so_what(results)` reads `VERDICT_SO_WHAT` by verdict.
  Untested tickers (BTC-USD) never get a verdict sentence.
- Chart 1 titles with a timing reading end "(exploratory)"; the same-hour title is "The strongest
  link between ... is in the same hour (exploratory)"; "so neither gets a head start" and the
  "mirror" so-what are gone. Note: `docs/design/dashboard_ux.md` still shows the old same-hour
  title as an example; it is superseded by this fix.

### Minors
- m1 fixed: Fed/CPI placebo rows read "Not needed" when the primary is not BH-significant; the
  technical text states pass yes/no.
- m2 fixed: BTC R3 is `holds: null` ("not applicable"); per-pair robustness wording.
- m3 fixed: `studies.bar_study`/`cpi_study` return `TooFewEvents` counts. Results write
  `event_study_notes` (shown in chart 2) and `details.event_study_counts`. Real data: Fed 2 of
  16 usable (14 unsigned); CPI 0 of 20 (20 unsigned).
- m4 fixed: `nocontrol_p is not None` (p = 0.0 fires rule 7.4).
- m5 fixed: "Enough data for the test".
- m6 fixed: sub-hour test above; lesson added to `lessons.md`.
- m7 fixed: Medium needs `placebo_pass is True`.
- m8 deferred: the BTC overnight spot-gap control has the same 30-min misalignment, but A29 does
  not name it; needs a user decision (note or amendment).
- m9: verified, no dashboard text uses the overnight exploratory rejections.

### Needs a decision
- BTC Chart 2 is residualised on the same spot control; A29 does not name it, so it has no note.
- CPI chart 2: all 20 releases unsigned (|Δ| < 0.005 pp, or NaN, in the bar before the open; `sign_of` counts a missing change as unsigned, so the counts do not separate the two). The signing
  rule never fires on real data; worth checking whether the CPI signal ever moves overnight
  in that bar (lesson: check a rule fires on real data).

### Real run (after the fixes)
fed_decision No head start (Low); bitcoin_monthly_ladder Too early to tell (Low; literal "No
head start"); us_cpi_inflation Too early to tell (Low); us_recession Descriptive only (Low).
Headline: "So far no pair shows Polymarket odds moving ahead of stocks; 3 of 4 are still
undecided or descriptive only". Cards: "Fed odds give no head start on TLT (long-term bonds)";
"Too early to tell whether Bitcoin price odds move before IBIT (Bitcoin ETF)"; "Too early to tell
whether inflation odds move before TLT (long-term bonds)"; "A description of how IWM-SPY (small
vs large companies) moved on the biggest days for recession odds".

Checks: `bash scripts/check.sh` PASS (443 passed, ruff clean, pairs.yaml reproducible, ingest dry run OK). AppTest on the real results: every card and every ticker of each picker render with no exception.

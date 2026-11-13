# Step 9 build report: election-study analysis (milestone 2)

Builder: quant-researcher. Date 2026-11-13. Pre-registration (`docs/election/preregistration.md`,
incl. A1) implemented as written, not edited. Milestone-1 modules and tests untouched. No commit.
Order of work: A1 panel rule, then synthetic tests, then estimators, then ONE real `analyse`, then
`publish`. Nothing was changed after the real run apart from the report. A second `analyse` was
run only to check that the output is byte-identical (sha256 of all 10 files matched).

## Headline (verdict table applied mechanically)
| | Verdict | Confidence |
|---|---|---|
| H1 | **Too noisy to tell** | Low |
| H2 | **Betas did not predict election night** | Low |

Holm over {H1 permutation p = 0.507, H2 one-sided permutation p = 0.975} at α = 0.05: neither
rejected (the first threshold is 0.025).

### H1: pre-election partisan beta, daily (n = 325 sessions, 2025-07-21 .. 2026-11-02)
`r_AI = a + b·ΔP_sen + c·r_RSP + d·r_TLT`, NW-HAC with 5 lags; 1,000 circular shifts, min shift 20.

| Basket | b per +10 pts | 90% CI | HAC se | HAC p | perm p | R² | partial R² of ΔP | MDE80 per 10 pts |
|---|---|---|---|---|---|---|---|---|
| AI composite (29) | **−0.566%** | [−1.649, +0.517] | 0.657 | 0.390 | **0.507** | 0.199 | 0.003 | **1.840%** |
| Placebo (29) | +0.015% | [−0.198, +0.227] | 0.129 | 0.909 | 0.936 | 0.429 | 0.000 | 0.361% |
| AI − placebo | −0.581% | [−1.838, +0.676] | 0.762 | 0.447 | 0.529 | 0.042 | 0.002 | 2.135% |

Not significant, and the MDE (1.84% per 10 pts) is above the 0.5% bound, so the table gives
"Too noisy to tell", not "no beta". The placebo basket is tightly bounded around zero (MDE 0.36%);
the AI composite is about 5 times noisier relative to ΔP. Dropped sessions: 2025-07-14 .. 07-18
(no odds, the thin start disclosed in A1; 07-18 has no prior-close reading so no ΔP).

Robustness (AI composite; no row is significant after any correction; E4 rows are exploratory):
| Row | b per +10 pts | 90% CI | HAC p | perm p | n |
|---|---|---|---|---|---|
| SPY instead of RSP | −0.189% | [−0.843, +0.466] | 0.635 | 0.677 | 325 |
| No controls | −0.384% | [−1.500, +0.731] | 0.570 | 0.673 | 325 |
| Logit change (per +1 logit) | −1.544% | [−4.274, +1.185] | 0.351 | 0.396 | 325 |
| Drop 5 largest abs(ΔP) days | −0.743% | [−2.458, +0.972] | 0.475 | 0.492 | 320 |
| E4 p_house | −1.921% | [−3.520, −0.322] | 0.048 | 0.096 | 325 |
| E4 p_sweep | −1.117% | [−2.632, +0.399] | 0.225 | 0.249 | 325 |
| E4 p_rr | +0.189% | [−0.526, +0.904] | 0.663 | 0.690 | 325 |
(The logit row is stored as b×10 in `b10_pct`. The JSON flags its unit.)

### H2: do pre-election betas predict the election-night cross-section?
b_i from the H1 regression per stock on 2025-07-21 .. **2026-10-30** (324 sessions). Event ΔP_sen
(close 3 Nov → close 4 Nov) = **+0.2545** (0.745 → 0.9995, resolved price under A1). 10,000
label permutations; Fisher 90% CI.

| Group | Window | ρ | 90% CI | p one-sided (ρ>0) | p two-sided | mean AR |
|---|---|---|---|---|---|---|
| **AI (primary)** | close3→close4 | **−0.372** | [−0.619, −0.058] | **0.975** | 0.047 | −5.37% |
| AI | close3→open4 | −0.375 | [−0.621, −0.062] | 0.978 | 0.043 | −3.41% |
| AI | close3→close6 | −0.266 | [−0.540, +0.060] | 0.924 | 0.155 | −6.95% |
| Placebo | close3→close4 | +0.002 | [−0.319, +0.322] | 0.502 | 0.995 | +0.89% |
| Pooled 58 | close3→close4 | −0.150 | [−0.362, +0.078] | 0.863 | 0.268 | −2.24% |

The sign went against the pre-registered direction. AI names with *higher* pre-election betas did
*worse* on election night (two-sided p = 0.047, one night, not the pre-registered test, not
Holm-corrected, so it is not a finding). The AI basket as a whole had a large negative abnormal
return on 4 Nov: the equal-weight composite fell 3.5% while RSP rose 1.8% and NDX rose 0.9%.

**H2b** (walk-forward, fully out-of-sample): AI mean signed ρ = **+0.048**, t = 1.21, one-sided
**p = 0.115**, n = 74 days. Placebo: mean −0.033, t = −1.30, p = 0.901, n = 74.

## Secondary and exploratory
- **H3 (descriptive only, capped)**: 185 window bars, 174 used per instrument (one missing futures
  bar at 05:05 UTC removes 11 bars through the ±3 lags). 76.2% of bars have a fresh fid-1 reading
  and 23.8% are after p_sen resolved (A1, ΔP = 0). NQ: lag +2 (odds 10 min earlier) b = +0.366% per
  10 pts [0.197, 0.536]; lag −1 b = −0.396% [−0.702, −0.089]. ES and RTY show the same +2/−1
  pattern, NQ−ES is weaker, RTY−ES shows nothing. This is one night and the NQ path was seen
  before the freeze, so it is not evidence of an ordering.
- **H4 (hourly, n = 330 sessions, 1,275–1,918 bars per lag): "no detectable ordering"**. No lag
  survives BH (smallest BH p = 0.163, lag +1, b = −0.506% per 10 pts, raw HAC p = 0.023). The
  session-shift band for max abs(t) is 2.96 and no lag exceeds it. 2026-01-30 and 02-02 have no hourly bars,
  as expected.
- **H5 (BH over 4 sub-baskets on permutation p)**: none significant. Hyperscalers −0.901%
  [−1.821, +0.019] (perm p 0.174), software −1.102% [−2.437, +0.233] (0.226), semis −0.678%
  [−2.254, +0.898] (0.616), power/infra +0.267% [−0.625, +1.159] (0.692). The Wald test of equal b:
  W = 9.79, df 3, **p = 0.020**. This single secondary test says the sub-baskets' betas differ
  (power/infra has the opposite sign), but none of them is individually different from 0.
- **E1 (exploratory)**: the rolling 60-session b swings widely (e.g. +4.1% on 2026-03-09, −2.2% on
  2026-11-02). Last 30 sessions (from 2026-09-22) minus before: −5.56% per 10 pts [−6.90, −4.21],
  HAC p < 0.001. This is a post-hoc slice of one regime; treat it as a hypothesis for the next
  election, not a result.
- **E2 (exploratory)**: VXN-implied one-day move on election day vs the realised NDX move on the
  next session. 2018: 1.65% vs +3.02%. 2022: 1.99% vs −2.40%. 2024: 1.42% vs +2.70%. **2026: 1.92%
  vs +0.91%** (ratio 0.47, the only election where the move came in below the implied).
- **E3 (exploratory)**: moratorium mean ΔP vs power/DC − XLU, n = 32. ρ = +0.258, 90% CI
  [−0.05, +0.52], two-sided p = 0.156.
- **E4**: see the robustness rows. p_house has HAC p 0.048 and perm p 0.096. It is uncorrected,
  exploratory and the opposite sign to an intuitive "D good for AI".
- **E5 (exploratory)**: top − bottom beta-tercile CAR from 4 to 12 Nov = −4.49% (−5.60% on 4 Nov
  alone; +1.11% drift after the event day). Ten names in each tercile.

## What this does NOT show
- It does not show that AI has no partisan beta. The estimate is too imprecise: an effect up to
  ~1.8% per 10 points could be missed with 20% probability.
- The negative H2 ρ is not a pre-registered finding (it is the wrong tail of a one-sided test). It
  comes from one night, on a day when AI fell broadly for reasons the design cannot separate.
- Nothing here is causal, and nothing is a trading recommendation.

## Files
- `src/poly_actor/election/stats.py` (estimators, Holm, verdict rules), `intraday.py` (H3, H4),
  `explore.py` (E1–E3, E5), `analysis.py` (assembly, H1/H2/H2b/H5, `analyse`), `bundle.py`
  (headline, checklist, series, write, `publish`), `cli.py` (+ `analyse`, `publish`), `panel.py` (A1).
- Tests: `tests/test_election_resolved.py` (A1, 7), `tests/test_election_stats.py` (estimators,
  32), `tests/test_election_analysis.py` (end to end on synthetic panels, 12),
  `tests/election_synth.py` (generator with the real sessions, bar ends and schema).
- Outputs: `data/clean/election/results/{results.json, series/*.csv}` → `reports/election/`
  (10 files, 272 KB; derived aggregates only: basket series, statistics, per-stock b_i and AR_i,
  odds, futures as % change from 18:00 ET, vol ratios. No per-ticker price history).

## Panel change (carried over A1) and rebuild
- `build_book(..., closes=)` returns a `ResolvingBook`. At instants ≥ the token's close time
  (Gamma `closedTime` from `config/election.yaml`, a fact known at that instant) p = the last CLOB
  point at or before the instant with no age cap, and `resolved = True`. Before the close the
  6 h / 30 min / 10 min caps are unchanged. Columns added: `resolved` (odds_daily, odds_hourly),
  `res_<signal>` (night_5m). `age_s` stays honest (e.g. 36,341 s on 4 Nov).
- `build_daily` gains `adj_open` (from the same auto_adjust 1d frame). It is needed for the
  pre-registered close3→open4 window.
- The panel was rebuilt. coverage.json changes: in-life numbers are unchanged; odds_daily "all"
  missing share went from 10.5% to 8.7%; night p_sen missing went from 22.7% to 0% (p_house 8.1% to 0%).
- On real data the rule fires as expected. p_sen on 4 Nov = 0.9995 (resolved), dp = +0.2545, and
  5–12 Nov dp = 0.

## Implementation choices where the pre-registration is silent (fixed before the real run)
1. H1 permutation: the statistic is abs(HAC t) of b; p = (1 + hits)/(1 + 1,000). The 1,000 shifts are
   drawn with replacement from the **286** distinct admissible shifts (n = 325, min 20). The text
   asks for 1,000, but only 286 distinct shifts exist.
2. "b_AI − b_placebo significant at 0.10" is judged on the difference regression's permutation p.
   Its HAC p is 0.447, so the choice does not matter here.
3. H2 and Holm use the primary window (close3→close4) and the one-sided p. The two-sided p is
   reported beside it (A1).
4. H2b: "after the first 120" means usable rows 121 and later. "Top decile to date" means
   abs(ΔP_t) ≥ the 90% quantile of abs(ΔP_s) over s ≤ t, and ΔP_t = 0 is never selected.
   **See decision 1.**
5. H3: one joint distributed-lag regression with 7 lag terms, NW rule-of-thumb lag.
6. H4: one regression per lag (the milestone-1 method), HAC rule-of-thumb lag, BH on HAC p.
   The band uses circular whole-session shifts with min 5 sessions (milestone-1 `MIN_SHIFT`), 321
   shifts. Verdict: the lag with the largest abs(t) must be BH-significant, and its sign gives
   the wording. The residualisation uses the same-bar RSP and TLT log(close/open), on the same
   clock window as the outcome (lesson B1).
7. H5: BH on the permutation p of the 4 sub-baskets. The Wald test uses a joint NW(5) covariance
   of the stacked scores, χ²(3).
8. Baskets need all members present (only 1 AI hourly bar in the whole sample is lost to this).
   E5 terciles come from `qcut` on ranks (10/9/10). E3 uses every moratorium session (n = 32).
9. `meta.generated_at` = the run date (byte-identical on the same day).

## Needs a decision (main)
1. **H2b selected 74 of 205 eligible days (36%), not ~10%.** Daily ΔP sits on a 0.005 tick and
   the 90% quantile of abs(ΔP) is usually 0.01, so the "≥" rule takes every tied day. I fixed this
   rule before the real run and did not change it after. **It cannot change either verdict**: H2
   fails on ρ < 0, so H2b only matters for H2's confidence when H2 passes, and H1 is not rejected.
   A stricter reading (">" or a random tie-break) would have to be a dated amendment by main. I did
   not compute it.
2. Synthetic-test note (not a real-data change): in the H1 power test the noise was lowered from
   0.004 to 0.003. At 0.004 the expected HAC t is about 2.7, so theoretical power is about 77%,
   below the 80% the test asks for. At 0.003 the expected t is about 3.6. The method is unchanged.
3. `docs/handoff/step10.md` shows as modified in `git status`. I did not touch it.

## Self-check (step 9 checklist and lessons)
1. Synthetic tests pass. Planted effects are recovered: H1 b within 2 se in ≥ 45/50 seeds and perm
   p < 0.05 in ≥ 40/50. The planted end-to-end run gives "AI carried a partisan beta" and "Betas
   predicted…", H4 "odds first" and H3 lag 0. Noise gives 0–14/100 rejections, the null end-to-end
   run gives no beta or ordering, and shuffled b gives uniform p.
2. Real run done once. `results.json` + 9 series written, and `publish` → `reports/election/`
   (tracked, not git-ignored).
3. The verdict table is mapped row by row in a parametrised test (7 H1 rows, 5 H2 rows), plus
   Holm (0.03, 0.04) → none rejected and p = 0.30, MDE 0.8 → "Too noisy", Low.
4. No look-ahead in H2/H2b. Tests: the H2 estimation ends 2026-10-30 and poisoned rows ≥ 11-02
   leave b_i bit-identical; H2b `last_est < date`; a planted day-t outlier does not leak; the decile
   uses data to date only.
   Mutation tests (each applied, tests run, restored), all killed:
   - H2b including day t
   - `H2_EST_END` moved to 11-03
   - A1 rule disabled
   - A1 with the age cap kept
   - hourly lag crossing sessions
   - Holm threshold set to α
   - missing ΔP filled with 0
   - abnormal return also removing b·ΔP
   - the decile taken over the full sample. This one first SURVIVED; a test was added and it is
     now killed.
5. Numbers reported above, nulls included.
6. `bash scripts/check.sh`: **PASS** (558 passed, 1 skipped; ruff check and format ok).

Lessons:
- No look-ahead: A1 uses only the close time and points ≤ t.
- Controls are on the same clock window (same-bar hourly, close-to-close daily).
- Closed-market hours are excluded from H4 (regular session only, lags within the session).
- The headline comes only from the H1/H2 verdict rules for the composite.
- A1 fires on real data.
- The synthetic panels use the real XNYS sessions and bar ends.

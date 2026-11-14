# Step 6: critique of DRAFT amendment A27 (analysis settings)

Date: 2026-10-06. Reviewer: quant-researcher (fresh context).
Scope: `docs/handoff/step6.md` § A27 against `docs/preregistration.md` (pairs + A1–A26), the panel schemas and the align code.
**Blindness kept.** No return column, opening-gap column or PM-change value was read. I used only flags, positions, row counts, `signal_reason` / `signal_level` validity (non-NaN) and the code. All numbers below are counts.

## Verdict

**3 blockers, 10 majors, 12 minors.** A27 should not be frozen as written. Two of the blockers bias the headline toward "Polymarket moves first". The third (CPI) leaves the primary's verdict class to a convention nobody has fixed yet, at a count that sits exactly on A27's own threshold.

| # | Sev | One line |
|---|---|---|
| B1 | blocker | Lagged PM regressors are taken from excluded rows. On every FOMC day the kept 15:30–16:00 bar regresses TLT on the decision-bar resolution jump (lag 2) and the roll bar (lag 1). 16 rows, the largest Δdovishness in the sample. |
| B2 | blocker | "Moves first" = sum BH-significant + lag-1 OR lag-2 at unadjusted p < 0.10. If the truth is contemporaneous only, this gives a false "moves first" about 19% of the time. The rows "only lag 0 carries it" and others are undefined or not computable for BTC, CPI and pair 4. |
| B3 | blocker | CPI has 11 usable releases, not 20, against a minimum of 12. The 12th (2025-10-24) depends on an unstated as-of convention. The validation denominator is undefined. Power: MDE \|ρ\| ≈ 0.72. |
| M1 | major | There is no "Polymarket lags / stocks move first" outcome, though it is one of the three answers to the project question. |
| M2 | major | Chart 1 band: pointwise band with no lag multiplicity control. The adjacency rule misses a clean single-lag lead. The contract needs a scalar band. The shift placebo is under-specified. |
| M3 | major | Chart 1 for CPI and recession contradicts the prereg ("No hourly lead-lag", "no lead-lag inference"). BTC xcorr is not spot-adjusted. |
| M4 | major | The prereg's global overnight/weekend test against the opening gap is silently dropped. |
| M5 | major | The session rule is applied to the 24/7 BTC-USD control lags. The prereg says "1 to 3 hours". The BTC primary n drops from 1,321 to 822. |
| M6 | major | No placebo for the Fed or CPI primaries, or for the event studies. "Placebo passes" in Confidence cannot be computed for them. |
| M7 | major | The age-900 robustness changes at most 1.3% of rows, so "sign holds" is automatic and Medium confidence is inflated. |
| M8 | major | Event minimum and confidence cannot be computed: BTC "events" are undefined, the Fed event count is irrelevant to an hourly test, High is unreachable for every pair, and no CI is specified for the primaries. |
| M9 | major | Event-study windows (−3..+6 bars) cross the close for Fed and CPI. Gap handling, the zero-move tie rule and overlap rules are missing. |
| M10 | major | Several synthetic rows cannot fail for the bug they target (BTC control, BH, noise/HAC, planted lag). |

---

## Blockers

### B1. Lagged regressors drawn from excluded rows (bias toward "Polymarket moves first")

**Evidence (code + counts).** `splice.py` sets `event_hour` on the window containing the decision time and `roll_hour` on the window containing the roll (decision + 1h). For a 14:00 ET FOMC decision, the event bar is the 13:30–14:30 bar (position 4) and the roll bar is the 14:30–15:30 bar (position 5). A27 drops those rows but keeps the 15:30–16:00 bar (position 6). "Lags never cross a session boundary" does not stop that bar's lag 1 from being the roll bar or its lag 2 from being the decision bar. The decision-bar ΔPM is the old market snapping to the realised decision, i.e. the FOMC surprise. The roll bar is the next meeting's reaction to the press conference.

So on 16 rows (counted: 16 kept Fed rows have an event or roll bar inside lags 1–3, all at position 6), the regression asks whether the FOMC surprise predicts TLT's 15:30–16:00 post-announcement drift. If it does, that is post-event drift, not Polymarket information. It loads on b2 and b1, which are exactly the coefficients B2's "moves first" rule reads. When a decision is not fully priced, these are likely among the largest |Δdovishness| values in the sample (not checked, to stay blind), so OLS leverage can be high. The prereg excludes "roll hours and decision hours", and using them as regressors brings them back in.

A related bug class: if lags are computed after filtering (e.g. `shift` on the filtered frame), a dropped row's neighbour slides into the lag slot. The same happens across Yahoo holes (`short_day`).

**Replacement wording:**
> **Lag construction.** Lags are computed on the full expected session-bar grid of each session (every `is_session_bar` row, including missing or excluded bars), BEFORE any row filtering. A row enters a regression only if the row itself AND every row that supplies one of its PM regressors (lags 0..L) pass the sample filter (`both_trading`, not `roll_hour`, not `event_hour`, not `outage_mask`, `pm_obs_age_s` ≤ 1800) and belong to the same session. Examples: (i) Fed 15:30–16:00 bar on an FOMC day (lag 1 = roll bar, lag 2 = decision bar) → dropped (16 rows). (ii) Bar at position 3 when position 2 is a Yahoo hole → lag 1 is NaN, not position 1's value. (iii) First bar of a session → lags 1 and 2 are NaN. The same rule applies to the stock-side leads in Chart 1. Resulting Fed primary sample (lags 0–2): 2,404 rows (counted 2026-10-06).

### B2. Verdict rule biases toward "moves first"; several cells cannot be computed

**Problems.**
1. **False "moves first".** Take a pure contemporaneous effect (b0 > 0, b1 = b2 = 0). The sum test is BH-significant with high probability. Each of b1 and b2 then has a 10% chance of one-sided p < 0.10, so P(either) ≈ 1 − 0.9² ≈ 19%. Roughly one in five pure "moves with" truths would be published as "Polymarket moves first". That is the project's headline claim, and it gets a looser, unadjusted bar than the primary.
2. **"Only the lag-0 coefficient carries it"** has no operational definition.
3. **Precedence is unstated.** Lag 0 and lag 1 can both be individually significant.
4. **Uncovered cells.** BH-significant with no individually significant coefficient; placebo fails; BTC with control significant but XLU fails.
5. **Pairs that don't fit.** BTC has no lag-0 PM term, so "moves at the same time" is impossible there. CPI has no lags, so no row applies when it is BH-significant. The pair-4 verdict is never stated.
6. **CPI overlap.** CPI's proxy window (5 sessions before to release − 1h) overlaps the TLT gap window (prior 16:00 close to 09:30 open) over the night before the release. A negative ρ can come from overnight news that moves both, i.e. "moves with", not "first".
7. **BH family.** It must not depend on sufficiency. If CPI turns out "Too early", its p must still enter BH (A12 fixes the family).

**Replacement wording (fixed-sequence gatekeeping, first matching row wins):**
> **Verdict (computed per pair; first matching row wins).** All three primary p-values enter BH (q = 0.10) regardless of the rows below.
> 1. Pair 4 → "Too early to tell", reason "descriptive only, one episode (prereg)". [Decision for user: or add a "Descriptive only" label to the contract.]
> 2. Data below the sufficiency minimum (M8), or CPI validation fails → "Too early to tell".
> 3. A placebo fails (BTC: XLU two-sided p ≤ 0.10; Fed/CPI: M6) → "Too early to tell", reason "placebo failed".
> 4. BTC only: the primary (with spot control) is not BH-significant AND the no-control lag-1 coefficient has one-sided p < 0.05 → "No extra information".
> 5. Primary not BH-significant → "No head start" if the one-sided 95% upper confidence bound of the effect is below the pre-declared MDE (M8). Otherwise "Too early to tell", reason "underpowered".
> 6. Primary BH-significant:
>    - **Fed:** test the lead sum b1+b2 (one-sided HAC, α = 0.05; tested only because the primary rejected, so FWER stays at α). If it rejects → "Polymarket moves first". Otherwise → "Moves at the same time" (reason states whether b0 alone has one-sided p < 0.05 or the timing is unresolved).
>    - **BTC:** the primary is already a lag-1 test with the spot control → "Polymarket moves first".
>    - **CPI:** → "Polymarket moves first" only if the sensitivity proxy that ends at the prior 16:00 ET close (same 5-session start) also has ρ < 0 with one-sided p < 0.10. Otherwise → "Moves at the same time" (the overnight overlap cannot be ruled out).
>
> Synthetic acceptance: contemporaneous-only planted effect (b0 = 0.1 SD, b1 = b2 = 0), 200 seeds → "Polymarket moves first" in ≤ 8% of seeds.

### B3. CPI: 11 usable releases, at the threshold, convention unstated

**Evidence (validity counts only).** A release is usable if the level is valid at release − 1h and 5 XNYS sessions earlier at the same clock time, within the same `event_id`. On the hourly-grid as-of, only **11 of 20** releases qualify. The 9 failures are `edge_mass_gt_max` (A23's 0.25 cap): 2024-12, 2025-01, 2025-02, 2025-04, 2025-05, 2025-07, 2025-10-24, 2026-01-13, 2026-04. For 7 of them the cap binds for the entire 30h before release. 2025-10-24 is borderline: the 06:00 ET row is ok, the 07:00 ET row is edge, and the 08:00 ET row is `start_unavailable`. Release − 1h is 07:30 ET, which is **not a grid instant** (rows outside a session are whole UTC hours). So "row ending at or before" and "exact as-of instant" can give 11 or 12. A27's minimum is 12. The verdict class of a primary therefore depends on a convention that is not written down. Only 6 releases also pass the strict 0.10 edge flag at both ends.

**Further problems.**
- **Validation denominator.** The prereg asks for a majority of resolved months. Is the denominator all 19–20, or only those with a valid level? With 11 valid of 20, "majority of all" needs every valid month to pass.
- **Power.** For a one-sided Spearman at n = 11 (Fisher z, SE ≈ √(1.06/(n−3)) = 0.364), 80% power at α = 0.05 needs |ρ| ≈ 0.72. Power at ρ = −0.5 is ≈ 0.45, and at ρ = −0.3 it is ≈ 0.23. A non-significant CPI result is uninformative. Labelling it "No head start" would overclaim a null.
- **Step text.** "20 releases" in step6.md misstates the usable count.

**Replacement wording:**
> **CPI usable releases.** The pre-release level is the PM as-of value at exactly release − 60 min, evaluated from the price book (not from the hourly grid row), under the A23 edge-mass rule. The 5-day level is the as-of value at the same clock instant 5 XNYS sessions earlier, with the same `event_id`. If either is invalid, the release is dropped (no search for a nearby valid hour). The usable count under this convention is computed from validity flags only and written into this amendment before any gap is read. On the grid convention it is 11 of 20, with 2025-10-24 borderline. **Validation:** denominator = resolved months with a valid release − 1h level; pass = strictly more than half within tolerance AND at least 8 valid months. **Sufficiency:** the test runs if ≥ 10 releases are usable [decision for user: 10, or keep 12 and accept "Too early to tell" now]. The p-value enters BH either way. Effect size: ρ with a 90% CI. With n ≈ 11 the MDE is |ρ| ≈ 0.72, so a non-significant result is "Too early to tell (underpowered)" unless the 90% CI excludes ρ ≤ −0.5. High confidence is unattainable for CPI and is stated as such.

---

## Majors

### M1. No "stocks move first" outcome
The milestone question is lead, lag or move with. The primary regressions contain only PM lags ≥ 0, and the verdict table and `contract.VERDICTS` have no lag label. If TLT leads dovishness, the pair reads "No head start". That is true but hides the answer.

There is also a mechanical bias toward the lag reading. PM is about 593 s stale, so ΔPM at bar t spans [t−70m, t−10m]. A joint reaction in the last 10 minutes of bar t therefore lands in ΔPM_{t+1} and shows up as "stock leads by 1 bar". Only the opposite caveat is in A27's note.

> **Replacement:** "Add the exploratory label 'Stocks move first (exploratory)'. It is assigned, in addition to the primary verdict, when the Chart 1 peak lies at a negative lag outside the simultaneous band (M2) and no positive lag is outside it. It never overrides the primary verdict. The note states that PM staleness shifts up to 10 minutes of joint reaction into lag −1 (toward 'stocks first') and up to 10 minutes of PM lead into lag 0."

### M2. Chart 1 band and "clear link" rule
- **Multiplicity.** A pointwise 95% band over 13 lags × several tickers per pair is not corrected (team standard: pairs × lags).
- **Adjacency rule misses sharp leads.** With serially uncorrelated PM changes, a lead at exactly lag 2 puts only lag 2 outside the band. Lags 1 and 3 have expectation 0, so the "peak plus adjacent bar" rule fails on a clean single-lag lead. If hourly PM changes are negatively autocorrelated (bid–ask bounce), the adjacent bar even has the opposite sign. Synthetic row 1 expects "+2 and +1/+3 outside the band", which will not happen with an iid regressor. Either the test fails or the generator gets fudged.
- **Contract.** It takes a single scalar `band`, so a per-lag (possibly asymmetric) 95% interval does not fit.
- **Placebo details missing.** Fed has 500 sessions and BTC has 262, so there are only about 490 and 252 distinct shifts of ≥ 5 sessions. 1,000 random draws resample the same shifts about 2–4 times and give false precision. How to align sessions with different bar counts (early closes have 3 bars) is unstated. So is whether lags are recomputed after shifting.

> **Replacement:** "Noise band (per ticker, scalar): the 95th percentile over all admissible circular session shifts (|k| ≥ 5 sessions, every k enumerated, no random draws) of max over lags −6..+6 of |r_k|. This is a simultaneous band: under the null, P(any lag outside) ≈ 5%. Shifting permutes whole sessions of the PM series; bars are matched by expected bar position within the session; unmatched positions are dropped; lags and sample filters (B1) are recomputed after each shift. 'Clear link' = peak |r| outside the simultaneous band. Adjacency is reported but not required. Exploratory; no correction across tickers beyond the band."

### M3. Chart 1 for CPI and recession contradicts the prereg; BTC xcorr not spot-adjusted
The prereg says CPI: "No hourly lead-lag" and recession: "no lead-lag inference is claimed". A27 applies Chart 1 "per ticker" with a "clear link" label, which is an unflagged departure. For BTC, the raw ladder–IBIT xcorr mostly shows spot co-movement. That contradicts the prereg's "every regression … with and without BTC-USD spot".

> **Replacement:** "Chart 1 is computed for Fed and BTC only. For CPI and recession it is not computed (contract slot null, dashboard shows 'Not part of the plan'). For BTC two panels are shown: raw, and with IBIT/COIN/MSTR/XLU returns residualised on BTC-USD lags 0–3 (clock time, M5). The 'clear link' label is read from the residualised panel."

### M4. Overnight/weekend test dropped
Prereg global rule: "Overnight and weekend moves are tested separately against the opening gap." A27 has no such test for Fed, BTC or recession. The panel already carries `pm_overnight_change` and `overnight_gap_*`. Valid overnight rows: Fed 499, BTC 211, recession 431. The team standard also requires overnight/weekend moves to be handled explicitly.

> **Replacement:** "Exploratory overnight test (Fed, BTC): OLS of `overnight_gap_<T>` on `pm_overnight_change` (rows with `pm_overnight_n_missing` = 0), with a weekend/holiday indicator and its interaction (gaps spanning more than one calendar night). HC1 SE (one row per session). BTC adds the BTC-USD spot return over the same close-to-open window as a control and is run with and without it. Report the coefficient with a 90% CI. Not in the BH family. The PM change and the gap cover the same closed-market window, so a non-zero coefficient means 'moves with', never 'first'."

### M5. Session rule applied to the 24/7 spot control (BTC)
The prereg says "contemporaneous and lagged (1 to 3 hours) BTC-USD spot returns". A27 turns these into bars and NaNs any lag that crosses the session boundary. That is an unflagged departure, and it requires position ≥ 3, cutting the BTC primary to **822** rows (counted). BTC-USD trades around the clock, so clock-time spot returns exist before the open. A control taken from pre-open hours creates no fake lead, because it is a control and not the tested PM regressor. Keeping the session rule only on the PM lag-1 regressor gives **1,321** rows (+61%), and the MDE (partial r, 80% power, one-sided 5%) falls from ≈ 0.087 to ≈ 0.068. Also, `ret_BTC-USD` at a :30 stamp spans [t−90m, t−30m] (the panel docstring: hourly closes), so the "contemporaneous" control is 30 minutes stale. State that.

> **Replacement:** "BTC-USD control lag k (k = 0..3) = log S(t − 60k min) − log S(t − 60(k+1) min) from the spot as-of, in clock time, regardless of session boundaries. Only the PM regressor follows the session and lag-window rule (B1). Note: at :30 stamps the spot as-of is the previous whole-hour close, so the lag-0 control covers [t−90m, t−30m]. Expected sample about 1,321 rows."

### M6. Placebos missing for Fed, CPI and the event studies
The team standard requires placebo checks (random event dates, shuffled series). The prereg lists only XLU for BTC. A27's Confidence rule requires "placebo passes" with no "(if any)", so Medium cannot be computed for Fed or CPI. The verdict says "(if any)", which makes the two inconsistent.

> **Replacement:** "Placebos. **Fed:** shuffled-series placebo. Recompute the primary sum statistic under every admissible circular session shift of the PM series (M2). The placebo passes if the observed statistic exceeds the 90th percentile of the shifted distribution (equivalently, permutation p < 0.10); the permutation p is also reported. **CPI:** random-date placebo. Recompute the proxy-vs-TLT-gap Spearman on sets of n_usable non-release sessions (valid levels, same 5-session window, excluding ±2 sessions around CPI releases and FOMC days), 1,000 sets, fixed seed. The placebo passes if the release ρ is below the 10th percentile of the placebo ρs. This also tests the generic overnight co-movement noted in B2. **BTC:** XLU as pre-registered, plus the shift placebo reported. **Event studies:** a 90% random-date band from 1,000 non-event sessions at the same bar position is drawn on each chart."

### M7. Robustness at age 900 barely fires
Extra rows dropped at 900 s compared with 1800 s, on `both_trading`: Fed 31 (0.9%), BTC 19 (1.1%), CPI 15 (0.9%), recession 23 (0.8%). On a sample that is ~99% identical, "the sign holds" is close to automatic, so Medium confidence becomes "BH-significant + placebo". This is the lessons.md item "check that a rule actually fires".

> **Replacement:** "Robustness runs (pre-specified). Each 'holds' if the sign is unchanged AND one-sided p < 0.10. R1: session-clustered SE instead of HAC. R2: drop the top 1% of |ΔPM| rows in the sample (influence). R3 (Fed only): drop all CPI-release and FOMC-decision sessions. Medium requires R1–R3 to hold. Age-900 is reported only, with its fire rate (≈ 1% of rows)."

### M8. Event minimum and confidence cannot be computed; CIs missing
- "Fewer than 12 events (CPI/Fed)": the Fed primary is an hourly test on about 2,400 rows, so the 16 FOMC events are irrelevant to its sufficiency.
- BTC "events" are undefined, yet High requires "≥ 30 events".
- High is unreachable for every pair: Fed 16 < 30, CPI 11 < 20, BTC undefined.
- "BH p < 0.01" could mean the raw or the adjusted p.
- No CI is specified for any primary (team standard).

> **Replacement:** "**Sufficiency.** Fed/BTC: ≥ 500 usable rows and ≥ 60 sessions (Fed ≈ 2,404/≈ 490, BTC ≈ 1,321/262). CPI: B3. **MDE** (80% power, one-sided α = 0.05, correlation units), recorded now: Fed ≈ 0.051, BTC ≈ 0.068, CPI ≈ 0.72. **Effect sizes:** Fed: b0+b1+b2 and b1+b2 in TLT bp per 1 bp Δdovishness, with two-sided 90% HAC CIs. BTC: lag-1 coefficient in IBIT bp per 1% ladder change, with a 90% CI, with and without the control. CPI: ρ with a 90% CI (Fisher z) plus a 90% bootstrap CI. **Confidence:** Not enough data = below sufficiency. Low = pair 4, or not BH-significant, or a placebo fails. Medium = BH-significant, placebo passes, R1–R3 hold. High = Medium AND BH-adjusted q < 0.01 AND (Fed/BTC) the lead or primary effect's 90% CI lower bound exceeds half the MDE. High is unattainable for CPI (n < 20) and pair 4; state it."

### M9. Event studies (Chart 2) cannot be computed as written
- **Fed.** The decision is in bar 4 (13:30–14:30), so only 2 session bars follow it. A window of −3..+6 bars spans the close and 4 bars of the next session.
- **CPI.** The release is at 08:30 ET, before the open, so "bar 0" is undefined and −3 falls in the previous session.
- **Overnight gap.** Whether a cumulative return across a close includes the gap is unstated.
- **Zero moves.** "Signed by the PM move in the hour before": no rule for ΔPM = 0, which is likely in near-certain Fed markets, where the sign is then noise.
- **BTC overlap.** The "largest 20 hourly moves" can cluster in the same session, giving overlapping windows and double counting.
- **Small n.** A percentile bootstrap over n = 16 events undercovers.

> **Replacement:** "Event time is counted in session bars. Bar 0 = the first session bar whose window ends after the event (Fed: the decision bar; CPI: the 09:30 bar). Windows crossing a close include that session's opening gap as a separate step, shown as a marked point. Fed window −3..+6 (spans the next session); CPI window: the gap (step) then bars 0..+5. Signing: by sign(ΔPM) in the bar before bar 0. Events with |ΔPM| below 0.5 bp (Fed) or below 0.005 pp (CPI) are unsigned and excluded, with their count reported. BTC events: greedy selection of the largest |Δln ladder| on usable rows with ≥ 1 session separation, up to 20; returns residualised on spot (M5). CI: 90% BCa bootstrap over events, plus each event's path; random-date band per M6."

### M10. Synthetic test rows that would not catch their target

| Row | Why it can't catch the failure | Replacement |
|---|---|---|
| BTC "PM = spot + noise, no extra effect" | With iid spot, ΔPM_{t−1} = spot_{t−1} + e is uncorrelated with IBIT_t = spot_t, so the result is non-significant even without the control. The "No extra information" branch is never exercised. | IBIT_t = spot_t + 0.4·spot_{t−1} + e; ΔPM_{t−1} = spot_{t−1} + e′. Expect: no-control p < 0.01, with-control p > 0.10 (in ≥ 90% of 100 seeds) → "No extra information". |
| BH p = (0.004, 0.03, 0.2) | Uncorrected testing at 0.10 and Holm give the same answer, so the row cannot detect a missing correction or step-down vs step-up. | (0.02, 0.06, 0.09) → all three rejected (fails Holm or Bonferroni). (0.01, 0.08, 0.5) → only the first (fails uncorrected). |
| Noise: KS p > 0.05 over 200 seeds | Gaussian iid data does not stress HAC. The real risk is oversizing with sparse, heavy-tailed regressors (most ΔPM ≈ 0, rare jumps) and volatility clustering. A KS test on 200 p-values is weak in the tail and flaky. | Realistic null: ΔPM 70% zeros + t(3) jumps, returns GARCH(1,1)-t(4) with shared volatility, the panel's session structure. Expect one-sided rejection at α = 0.05 in [3%, 8%] over 1,000 seeds (fixed). Same for the shift-placebo band: per-ticker null exceedance in [3%, 7%]. |
| Planted lag +2, n = 3,000, sd = 1 | No effect size, so the result is either trivial or flaky. A continuous series does not exercise the session/lag-window rules. It expects +1/+3 outside the band, which an iid regressor won't produce (M2). | Panel-shaped synthetic (7 bars per session, early closes, holes, excluded rows), β₂ = 0.1 SD. Expect: peak at +2 outside the simultaneous band in ≥ 90% of 100 seeds; Fed lead-sum p < 0.01; verdict "Polymarket moves first". |
| (missing) B1 | — | Planted huge ΔPM only on decision bars plus TLT drift on the 15:30 bar → those 16 rows are absent from the regression design matrix. Mutation test: removing the lag-window check makes this test fail. |
| (missing) B2 | — | Contemporaneous-only planted effect → "moves first" in ≤ 8% of 200 seeds. |
| (missing) B3 | — | 11 usable CPI releases with validation passing → the test runs, and a null result gives "Too early to tell (underpowered)" (or under the user's choice of 12: "Too early to tell"). |

---

## Minors (carry to the build; no re-check needed)

- **m1. BH rationale.** A27 argues against the prereg's "4 primary tests", but A12 already fixed the family at 3. Cite A12. Run a second, separately labelled BH over the exploratory family (SPY, XLF−SPY, QQQ, COIN, MSTR, IBIT lags 2–3, BTC no-control, overnight tests).
- **m2. HAC lag.** 6 is below the Newey–West rule of thumb ⌊4(T/100)^{2/9}⌋ (8 for T ≈ 2,400, 7 for T ≈ 1,300). Use the formula. The rows are concatenated across nights and gaps, so state that HAC treats them as adjacent. Session-cluster SE is the R1 robustness (M7). One-sided p from the t(df) distribution.
- **m3. One-sided tests.** Also report the two-sided 90% CI. A significant opposite sign (two-sided p < 0.05) sets the primary checklist row to "Failed (opposite sign)" instead of quietly reading as "No head start".
- **m4. BTC placebo.** XLU two-sided p > 0.10 is absence of evidence. Report XLU's CI, and say in the checklist that a pass is weak evidence at this power.
- **m5. Contract.** "No head start" and the M1 label are not in `contract.VERDICTS`, so the contract and its tests must change. "Weak" status needs a rule, e.g. the primary has one-sided p in [0.05, 0.10) or a robustness run fails on p but keeps the sign.
- **m6. Recession, change measure.** The prereg uses ΔP(Yes), but the team standard is Δlog-odds (clip [0.01, 0.99]). They select different days near p = 0.05. Pick one in A27 explicitly (suggest Δlogit as the main measure and ΔP as a sensitivity) and record it as part of the amendment.
- **m7. Recession, day alignment.** An ET calendar-day PM change (midnight to midnight) does not line up with a close-to-close stock return: PM moves after 16:00 count as day 0 but cannot affect day 0's close. Use PM changes from 16:00 ET to 16:00 ET on trading days, with weekends rolled into the next trading day. Require ≥ 2 trading days between selected days so day-0/day+1 windows don't overlap. The top days likely cluster in one 2025 episode, so list the dates. A percentile bootstrap at n = 10 undercovers; use BCa and show the individual days.
- **m8. CPI test details.** Use an exact permutation p for Spearman at n ≈ 11. Define the sign test: count of releases with sign(Δimplied)·sign(gap) < 0, one-sided binomial, zeros dropped.
- **m9. Unhandled flags.** The one Fed `clipped_p_gt1` row and the `short_day` sessions (4–5 per pair) need an explicit rule (suggest drop the row; for short days the lag-grid rule in B1 handles it).
- **m10. Prereg record.** A27 must be appended to `docs/preregistration.md` as a dated Round 6 amendment, with the counts above (Fed 2,404, BTC ≈ 1,321, CPI 11, the age-900 fire rates). The commit must precede any analysis commit (step-6 checklist row 1).
- **m11. Fed event study.** With 16 events, show each event's path. Signing by the pre-decision move in near-certain markets yields mostly unsigned events (M9), so expect a near-empty chart and say so.
- **m12. Staleness note.** Extend the step-4 m3 note: the 10-minute staleness also pushes simultaneous reactions into lag −1 (M1). The BTC spot control is 30 minutes stale (M5).

## What this review does NOT show
It does not say anything about the size or direction of any effect: no return, gap or PM change was examined. The MDEs are design calculations from counts. The CPI usable count under the exact-instant convention was not computed, because that needs a price-book evaluation. It is left to the builder as a validity-only count.

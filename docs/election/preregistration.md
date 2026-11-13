# Pre-registration: the partisan beta of AI (milestone 2, 2026 US midterm)

Date frozen: 2026-11-13 (10 days AFTER the election). This is a retrospective study, so the
freeze cannot be blind to the outcome. What it can be is blind to the *relationship*. Any change
after this point is a dated amendment at the bottom, never an edit in place.

## What had been seen before the freeze (disclosure)
- Gamma metadata and resolved outcomes: Democrats won House and Senate; Republicans hold < 190
  House seats.
- A handful of Polymarket price points from scouting: P(D Senate) ≈ 0.29 (Jul 2025), ≈ 0.50
  (Mar 2026), 0.675 (28 Oct), 0.755 (3 Nov), → 1. P(D House) ≈ 0.70 → 0.915 → 0.945 → 1.
- Hourly NQ=F futures prints for the night of 3–4 Nov (fell ~2.4% between 19:00 and 22:00 ET, back
  to the prior level by ~05:00 ET), and last prices of a few tickers.
- NOT seen: any return series of the AI names against odds, any regression, correlation, basket
  return, election-day stock return, or vol-index path.
Because the NQ=F overnight path was seen, H3 below is capped at "Descriptive" confidence.

## Core question
Did AI-theme equities carry a measurable **partisan beta**, a sensitivity to the probability
that Democrats take Congress, over and above the broad market? Which part of the AI trade carried
it, did odds move before, with, or after the stocks, and did betas measured *before* the election
predict who repriced on election night?

Why a practitioner cares: if the beta is real and stable, election risk in an AI book can be sized
and hedged ex ante (with index futures, sector pairs or the prediction market itself). If it is
zero, the "election trade" in AI was noise and event hedges were wasted premium.

## Signal
- Primary: `p_sen` = Polymarket Yes price of "Will the Democratic Party control the Senate after
  the 2026 Midterm elections?" (event 32224). Chosen because it was the chamber in doubt
  (most variance), with $17M volume.
- Secondary: `p_house` (event 32225, Democratic), `p_sweep` ("D Senate, D House", event 32228),
  `p_rr` ("R Senate, R House").
- Changes are in probability points (ΔP), the repo's milestone-1 convention. Logit changes are a
  robustness check, with P clipped to [0.01, 0.99].
- Odds are sampled as-of: the last CLOB point at or before the timestamp, never after. A reading
  older than 30 minutes at an hourly bar end, or older than 6 hours at a daily close, is missing.

## Universe (fixed now; rationale per name in `config/election.yaml`)
- Semis (8): NVDA, AMD, AVGO, TSM, MU, MRVL, ASML, AMAT.
- Hyperscalers / AI cloud (6): MSFT, GOOGL, AMZN, META, ORCL, CRWV.
- AI power and data-centre infrastructure (8): VST, CEG, TLN, GEV, VRT, ETN, EQIX, DLR.
- AI software (7): PLTR, NOW, SNOW, DDOG, CRM, ADBE, MDB.
- AI composite = equal-weight mean of the 29 names' log returns. Sub-basket = equal-weight within.
- Placebo basket (29 large caps with no AI-capex thesis, picked before any returns were seen):
  JNJ, PG, KO, PEP, WMT, COST, MCD, HD, UNH, LLY, MRK, ABBV, JPM, BAC, GS, BRK-B, V, XOM, CVX,
  CAT, HON, UPS, LMT, RTX, DIS, T, VZ, NEE, LIN.
- Controls: RSP (equal-weight S&P 500; used instead of SPY because AI names are > 30% of SPY and
  would absorb the effect), TLT (rates). Robustness: SPY in place of RSP.
- Futures (election night): NQ=F, ES=F, RTY=F. Vol indices: ^VIX, ^VIX9D, ^VIX3M, ^VXN, ^VVIX.

## Sample
- Pre-election estimation sample: sessions from 2025-07-14 (first full session after the markets
  were created on 2025-07-11) to 2026-11-02 inclusive. 2026-11-03 (election day) and later are
  never used to estimate anything that is then tested on the event.
- Event window: close of 2026-11-03 (16:00 ET) → close of 2026-11-04 (16:00 ET). Secondary windows:
  close 3 Nov → open 4 Nov; close 3 Nov → close 6 Nov.

## Hypotheses

### H1 (primary): pre-election partisan beta of the AI composite, daily
`r_AI,t = a + b·ΔP_sen,t + c·r_RSP,t + d·r_TLT,t + e_t` on the pre-election sample; returns are
close-to-close log returns, ΔP is the as-of change over the same close-to-close window.
- Test: b ≠ 0, two-sided (no directional prior is claimed), Newey-West HAC with 5 lags.
- Inference check: circular-shift permutation of the ΔP series (1,000 shifts, minimum shift 20
  days); the permutation p-value is the reported p-value. HAC is shown beside it.
- AI-specific check: the same b for the placebo basket, and the difference b_AI − b_placebo
  (regression of the return difference). A beta that the placebo basket shares is not an AI beta.
- Reported effect: b per +10 probability points, with a 90% CI.
- Minimum detectable effect at 80% power is reported, so "no beta" is bounded, not asserted.

### H2 (primary): do pre-election betas predict the election-night cross-section?
Per-stock b_i from the H1 regression on sessions ≤ 2026-10-30 (so nothing from election week).
Event abnormal return `AR_i = r_i − c_i·r_RSP − d_i·r_TLT` over the event window.
- Test: Spearman rank correlation ρ(b_i, AR_i) across the 29 AI names > 0, one-sided (ΔP_sen on
  the event was positive, so a positive-beta stock should outperform). p-value by permuting stock
  labels (10,000 draws).
- H2b (usefulness beyond one night): walk-forward. For every pre-election session t after the
  first 120 with |ΔP_sen,t| in the top decile of the sample *to date*, estimate b_i on sessions
  < t and compute sign(ΔP_t)·ρ(b_i, AR_i,t). Test mean > 0 with a t-test across those days.
  This is fully out-of-sample and has n > 1.
- Placebo: the same two tests on the 29 placebo names.

Multiple testing: H1 and H2 form the primary family (Holm, α = 0.05). Everything below is
secondary or exploratory and is labelled so; secondary families get Benjamini-Hochberg.

### H3 (secondary, descriptive): election night at 5-minute resolution
Window 2026-11-03 18:00 ET → 2026-11-04 09:30 ET. 5-minute log returns of NQ=F, ES=F, RTY=F and the
spreads NQ−ES (tech-relative) and RTY−ES, regressed on 5-minute ΔP_sen at lags −3…+3 bars, HAC.
One night, and the NQ path was seen before the freeze: verdict is capped at "Descriptive only".

### H4 (secondary): who moves first, hourly
The milestone-1 method. Hours when both trade (US regular session), pre-election sample. AI
composite hourly return residualised on RSP and TLT, against hourly ΔP_sen at lags −3…+3 (positive
lag = odds move first). BH across the 7 lags. Verdict wording: "odds first" only if a positive lag
is BH-significant and lag 0 and negative lags are not larger; "moves with" for lag 0 only;
"stocks first" for negative lags; otherwise "no detectable ordering".

### H5 (secondary): which part of the AI trade carries the beta
H1 regression per sub-basket (4 tests, BH), and a Wald test that the four b are equal.

### Exploratory (labelled as such in every output)
- E1 Stability: rolling 60-session b for the composite; b in the last 30 sessions vs before.
- E2 Volatility: ^VIX9D/^VIX, ^VIX/^VIX3M and ^VXN−^VIX from 20 sessions before to 7 after the
  election, next to the same window for the 2018, 2022 midterms and the 2024 election. The implied
  one-day move (VXN/√252) on 3 Nov against the realised Nasdaq-100 move on 4 Nov.
- E3 State data-centre moratorium markets (Indiana, Ohio, Texas, Oklahoma, Missouri, Louisiana,
  North Carolina; created 29 Sep–5 Oct 2026): daily change in the mean "by 31 Dec 2027" price
  against the power/data-centre sub-basket minus XLU. About 30 sessions: descriptive only.
- E4 Secondary signals (p_house, p_sweep, p_rr) and logit changes in H1.
- E5 Post-election drift: cumulative abnormal return of the top vs bottom beta tercile from
  4 Nov to 13 Nov.

## Verdict rules (decided now)
| Outcome | Verdict | Confidence |
|---|---|---|
| H1 permutation p < Holm threshold AND b_AI − b_placebo significant at 0.10 | "AI carried a partisan beta" | Medium; High only if H2 and H2b also pass |
| H1 significant but placebo basket shares it | "Election beta, not AI-specific" | Medium |
| H1 not significant and MDE ≤ 0.5% per 10 points | "No partisan beta (bounded)" | Medium |
| H1 not significant and MDE > 0.5% per 10 points | "Too noisy to tell" | Low |
| H2: ρ > 0 with permutation p < Holm threshold | "Betas predicted the election-night winners" | Medium if H2b also p < 0.10, else Low (one night) |
| H2 otherwise | "Betas did not predict election night" | Low |

A null is a valid result. Headlines come only from these rules for H1 and H2.

## Not claimed
No causal claim about policy. No trading recommendation. Paper only. One midterm is one
observation of the event itself; only the pre-election daily and hourly samples have n > 1.

## Amendments
(none yet)

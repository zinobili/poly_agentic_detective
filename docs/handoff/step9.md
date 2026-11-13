# Step 9 hand-off (milestone 2: election study, analysis)

Branch `claude/fervent-mayer-k4klat`. The hypotheses, samples, tests and verdict rules are frozen
in `docs/election/preregistration.md`. Implement them exactly. If something cannot be done as
written, stop and report; do not improvise a variant (that would be a post-hoc amendment, which
only main may record). Inputs: the step 8 panels in `data/clean/election/` (see
`docs/handoff/step8.md` and `docs/reviews/step8_build.md`).

Environment: Linux, `.venv/bin/python`. No network in this step.

## Decisions (main, 2026-11-13)
1. Code in `src/poly_actor/election/analysis.py` (+ small modules if it grows past ~400 lines),
   CLI `python -m poly_actor.election analyse` → `data/clean/election/results/results.json` plus
   chart series; `python -m poly_actor.election publish` copies the dashboard bundle to
   `reports/election/` (tracked in git, so the dashboard runs after a fresh clone).
2. Reuse `poly_actor.analysis.models` (`ols` with HAC, `bh`, `spearman`, `spearman_perm_p`,
   `fisher_ci`) and the circular-shift idea from `poly_actor.analysis.placebo`. Don't modify them.
3. **Order of work: synthetic tests first, real data last.** Write the estimators against
   synthetic panels with a planted effect and against pure noise; only then run on real data,
   once. Do not tune anything after seeing real results.
4. The bundle holds derived aggregates only: basket-level series, statistics, per-stock betas and
   event abnormal returns, odds series, futures as % change from the window start, vol-index
   ratios. No raw per-ticker price history.
5. Seeds fixed (`numpy.random.default_rng(20261113)`); a second `analyse` run is byte-identical.

## What to compute (ids match the pre-registration)
- **H1** composite, placebo basket, and the difference; controls RSP + TLT. Report b per +10
  points, HAC se, 90% CI, HAC p, circular-shift permutation p (1,000 shifts, min shift 20), n,
  R², partial R² of ΔP, and the MDE at 80% power (two-sided α = 0.05, from the HAC se).
  Robustness rows: SPY instead of RSP; no controls; logit change; drop the 5 largest |ΔP| days;
  each secondary signal (E4).
- **H2** per-stock b_i on sessions ≤ 2026-10-30, event AR_i for the three windows, Spearman ρ with
  label-permutation p (10,000), Fisher 90% CI; same for the placebo names. Also the pooled 58.
- **H2b** walk-forward signed rank correlations: list of dates, ΔP, signed ρ; mean, t-stat,
  one-sided p, n days; same for the placebo names.
- **Holm** over {H1 permutation p, H2 permutation p} at α = 0.05; then apply the verdict table.
- **H3** per instrument (NQ, ES, RTY, NQ−ES, RTY−ES): coefficients at lags −3…+3 with HAC CIs, n
  bars, share of bars with a fresh odds reading. Series for the chart: P(D Senate), P(D House)
  and each future as % change from 18:00 ET.
- **H4** hourly: residualise the composite hourly return on RSP and TLT hourly returns (same-bar,
  within-session; build the control exactly on the same clock window as the outcome, lesson B1),
  then regress on ΔP at each lag −3…+3 within session (no lag crosses a session boundary); HAC,
  BH over 7, circular-shift band (shift whole sessions). Verdict wording per the pre-registration.
- **H5** per sub-basket b (BH over 4) and the Wald equality test.
- **E1** rolling 60-session b with a ±1.645·se band; last-30 vs before.
- **E2** vol ratios, event-relative day −20…+7, for 2018-11-06, 2022-11-08, 2024-11-05 and
  2026-11-03; implied vs realised one-day move.
- **E3** moratorium mean ΔP vs (power/DC basket − XLU) daily: n, Spearman ρ, scatter series.
- **E5** top vs bottom beta-tercile cumulative abnormal return, 4–13 Nov.
- Context series for charts: daily P for all 4 signals; cumulative log return of the composite,
  each sub-basket, the placebo basket and RSP since 2025-07-14.

## Rules as examples (each becomes a test)
| Input | Expected |
|---|---|
| Synthetic: r_AI = 0.03·ΔP + 1.1·r_RSP + noise, 330 days | b recovered within 2 se; permutation p < 0.05 in ≥ 80% of 50 seeds |
| Synthetic: ΔP independent of returns | permutation p < 0.05 in roughly 5% of seeds (accept 0–14% over 100 seeds) |
| Synthetic: placebo basket has the same b as AI | difference b ≈ 0; verdict "Election beta, not AI-specific" |
| Synthetic cross-section: AR_i = b_i·0.245 + noise | ρ > 0, permutation p small; with shuffled b_i, p roughly uniform |
| H2 estimation sample | the last session used is 2026-10-30; a test fails if any row dated ≥ 2026-11-02 enters b_i |
| H2b day t | b_i use sessions < t only (mutation test: including day t must fail a test) |
| Hourly lag +1 at the first bar of a session | not formed (never pairs with the previous session's last bar) |
| ΔP missing on a day | that day is dropped from H1; never filled with 0 |
| Holm with p = (0.03, 0.04) | neither rejected at 0.05 (0.03 > 0.025) |
| H1 p = 0.30, MDE = 0.8% per 10 pts | verdict "Too noisy to tell", confidence Low |
| `analyse` run twice | identical `results.json` bytes |

## `results.json` contract (the dashboard and findings read only this)
Top level: `meta` (commit-independent: sample dates, n sessions, signal ids, seed, generated_at
date only), `headline` {`h1_verdict`, `h2_verdict`, `sentence`}, `h1`, `h2`, `h2b`, `h3`, `h4`,
`h5`, `exploratory` {`e1`…`e5`}, `robustness` (list of rows), `coverage` (from step 8),
`checklist` (per hypothesis: rows of {name, status ✓/✗/n.a., plain, technical}).
Chart series go in `series/*.parquet` (or `.csv`), each referenced by name from the JSON.
Every exploratory block carries `"label": "exploratory"`.

## Checklist
1. Synthetic tests above pass; planted effects recovered, noise returns nothing.
2. Real run done once; `results.json` + series written; `publish` creates `reports/election/`.
3. Verdicts in `headline` follow the pre-registration table mechanically (a test maps each table
   row to its verdict).
4. No look-ahead in H2/H2b (tests + mutation tests).
5. Report the real numbers plainly, including nulls, in `docs/reviews/step9_build.md`.
6. `bash scripts/check.sh` PASS. Reply ≤ 250 words with the H1/H2 verdicts and key numbers.

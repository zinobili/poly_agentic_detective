# Step 4 hand-off: alignment

**Status:** not started. Build an hourly UTC panel per pair from the raw views (`src/poly_actor/store/raw_views.py`).

## Requirements
These come from `docs/milestone1_plan.md` ("Requirements learned in step 1") and `docs/handoff/lessons.md`.

### Polymarket side
- **Resample** across `fid=60`, `fid=10` and `fid=1`, taking the last observation at or before each hour end. Never use a later observation.
- **Prices above 1:** clip the 209 rows with p > 1 (max 1.0055) to [0, 1] and flag them.
- **BTC ladder:** for each hour, run `load_btc_rungs(month)` and then `select_ladder`, then compute the monotone crossing.
  - Log the dropped hours, including each whole-month rung's first 24h.
  - Log the PAV pooling rate.
- **CPI:** log how often the derived-bucket `max(0, …)` clip binds.

### Stock side
- **Re-stamp** each bar to its end time using XNYS, including the early-close rule.
- **Drop or flag** short days, per `data/scratch/step3/stock_gaps.csv`.
- **Known Yahoo gap:** 2026-01-30 11:30 ET to 2026-02-02 13:30 ET, for all equities.

### Joining the two
- **Roll and splice** per `config/pairs.yaml`: roll 1h after each official event time, splice on changes, and set the `roll_hour` flag.
- **Trading hours only:** the lead-lag panel keeps only hours when both sides trade. Overnight and weekend Polymarket moves go in a separate column, set against the opening gap.

## Minors carried over from step 3 (round 2, docs/reviews/step3_r2.md)
- A stale `data/raw/.ingest.lock` after a hard crash must be deleted by hand. Document it, or add `--break-lock` later.
- There is no true concurrent-write race test; only sequential-vs-parallel parity is tested.
- Fidelity-1 probe records are `status=ok` with `n_rows=0`. When resampling, treat them as "no data", not as a price.
- The "partial" gap label only means the worst remaining gap is over 3h. The 11 remaining gaps are all in the 2025-10-29 09:00–14:00Z upstream outage. Mask those hours.
- The `empty_confirmed` policy rests on a single fidelity-1 probe.
- The `--workers 4` rate (~10–16 req/s) hasn't been tested live. Watch the first real run for 429s; backoff handles them.

## Minors carried over from the engineering review (docs/reviews/push_2026-10-03_crusader_r1.md and r2)
There are 18 round-1 minors, deliberately not fixed. The main ones:
- three duplicated time parsers; consolidate on the `poly_actor.ingest.common` helpers
- magic numbers in the ingest CLI
- missing docstrings and type hints in places
- `ladder` typed `str` instead of `Literal["up", "dip"]`
- the pytest `live` marker says "deselected by default", but nothing deselects it (add `-m "not live"` to addopts or fix the text)
- a malformed `--asof` gives a traceback instead of a clean error
- `run_stocks` is 63 lines
- some tests check several concepts at once

Fix any of these that the step 4 code touches. New step 4 code must meet the crusader standard from the start (`.claude/agents/clean-code-crusader.md`).

## Round 2 fix batch (2026-10-03, after validator r1 FAIL: docs/reviews/step4_r1.md)

**User decision M2 = A:** download fidelity-10 Polymarket history for the full life of every **fed_decision** and **bitcoin_monthly_ladder** token. That's about 1,800 calls; use `--workers 4` and run it in the background. The as-of uses the freshest available observation across fid 1/10/60, strict, so prices at the :30 session-bar ends are ≤10 min stale with no look-ahead. Record it as amendment A25 (data change, decided on staleness, not results).

**Rules as examples** (each becomes a test):

| Situation | Expected |
|---|---|
| fid-60 point at 14:00:40Z, query instant 14:00:00Z | used (A22 tolerance, ≤53s after :00, fid-60 only); `pm_used_tolerance=True` |
| fid-10 or fid-1 point at 14:30:05Z, query 14:30:00Z | **NOT** used; take the latest point ≤14:30:00Z |
| fid-60 point at 14:30:20Z, query 14:30:00Z | **NOT** used (the tolerance only applies at the top of the hour) |
| fid-60 point at 14:00:54Z, query 14:00:00Z | NOT used (54 > 53) |
| `--strict-asof` | no point after the instant is ever used, at any fidelity |
| BTC-USD spot bar starting 14:00Z | stamped at its END, 15:00Z; never gets the Polymarket tolerance |
| row ending exactly at a roll time | belongs to the OLD event; the next row is `roll_hour=True` (fix the r1 minor) |

**Fix list:** M1 (tolerance scope), M2 (fid-10 download plus the freshest-observation as-of), M3 (add tests that fail if any of the 4 surviving mutations comes back: the tolerance constant, strict mode, the BTC-USD tolerance, the BTC-USD stamping), plus r1 minors where cheap.

**Report** the median and p90 `pm_obs_age_s` on `both_trading` rows, per pair, strict and tolerant. **Target for Fed and BTC: median ≤ 600s.**

## Round 2b: fid-10 for CPI + recession (user decision 2026-10-05)

**User decision: yes.** Download fidelity-10 full-life history for every `us_cpi_inflation` and `us_recession` token, the same way as A25 (`--workers 4`, background). Extend A25 in `docs/preregistration.md` (do not add a new letter): "(1b) 2026-10-05, user decision: extended to CPI and recession tokens", with call count and failures. No code change to the as-of is expected; it already takes the freshest observation.

| Situation | Expected |
|---|---|
| CPI/recession `both_trading` row ending 14:30Z, fid-10 point at 14:20Z | used; `pm_obs_age_s` = 600 |
| fid-10 point at 14:30:05Z, query 14:30Z | NOT used (strict) |
| a token whose fid-10 call returns an empty 200 | logged, not marked covered (step 3 rule), counted in the report |

**Report** median and p90 `pm_obs_age_s` on `both_trading` rows for all 4 pairs, strict and tolerant. **Target for CPI and recession: median ≤ 600s.** Rebuild the panels, run `bash scripts/check.sh`, update `docs/reviews/step4_build_r2.md` (append a 2b section), commit on `wip/step4-alignment`.

# Step 4 (alignment) validation, round 2

Validator: fresh independent agent, 2026-10-05. Scope: `git diff 2aab227..HEAD` (rounds 2 and 2b), the r1 majors M1-M3, the Round 2 / 2b example tables, and the step 4 checklist (UTC/DST, market-hours mask, no long forward-fill, no look-ahead).

## Verdict

**PASS: 0 blockers, 0 majors, 5 minors.**

All three r1 majors are fixed. M1: the tolerance is scoped to fid-60 at whole hours. M2: on `both_trading` rows the median age is 592-595 s for all four pairs, which I recomputed from the data. M3: all four r1 mutants are now killed. The panels contain no look-ahead at all: tolerant and strict panels are byte-identical, and no `pm_obs_age_s` is negative.

The main finding (m1) is that the A22 tolerance is **dead in production**. Real data never takes the path that example row 1 tests. This is safe (it is stricter than approved), but the docs and the step 6 "strict robustness check" are now vacuous. The user should decide whether to retire A22.

## Checked (evidence)

- **`bash scripts/check.sh`:** 284 passed, ruff check/format ok, pairs.yaml reproducible, ingest dry-run ok (80 calls of newly elapsed hours), CHECK: PASS.
- **Reproducibility.** I rebuilt all 4 pairs, tolerant and `--strict-asof`, into a temp `--clean-dir`. All 8 md5 match `data/clean/`. Tolerant and strict md5 are also **identical to each other** for every pair (e.g. fed `6aaaca1a...` for both).
- **M2 recomputed** from `data/clean/panel_*.parquet`, on `both_trading` rows:

| pair | n | median | p90 | min | max | rows > 1500 s | `pm_used_tolerance` |
|---|---|---|---|---|---|---|---|
| fed_decision | 3469 | 594 | 597 | 0 | 6587 | 13 | 0 |
| bitcoin_monthly_ladder | 1691 | 595 | 598 | 554 | 10795 | 97 | 0 |
| us_cpi_inflation | 1764 | 593 | 597 | 0 | 6588 | 10 | 0 |
| us_recession | 3008 | 592 | 596 | 0 | 5941 | 8 | 0 |

  - Strict panels give the same numbers, and they match `align_summary.json` and the builder report.
  - `pm_used_tolerance` is 0 on **all** rows of all 8 panels, not only on `both_trading` rows.

- **M1.** The code (`prices.py:84-93`) applies the tolerance only through the fid-60-only series and only when `instants % HOUR_S == 0`. Tests cover each example row. In production the panels have no negative ages.
- **M3: mutation testing**, on a temp copy of the repo (full offline suite minus `test_hooks.py`, which depends on the repo path; baseline green). 19 mutants:
  - **Killed (15):**
    - the four r1 mutants: `PM_STAMP_TOLERANCE_S` = 54 and = 300, `run_pair` ignoring `strict`, BTC-USD stamped at bar start;
    - tolerance at :30 instants;
    - tolerance for all fidelities;
    - `TOLERANCE_FIDELITY` = 10;
    - strict-side off-by-one (main and tolerance `searchsorted`);
    - "always prefer the fid-60 series";
    - age cap removed;
    - `active_index` side, both the left and the `<=` mutant;
    - outage term removed from `both_trading`;
    - fid-10 plan dropped for BTC.
  - **Equivalent survivors (3):**
    - spot book given the tolerance: spot has no fid-60 rows;
    - spot book given fidelity 60 plus the tolerance: hourly spot stamps sit exactly on whole hours, so x+1..x+53 never holds a point;
    - `better = tol_stamp >= stamp`: equal stamps are the same point.
  - **Real survivor (1):** the CLI ignoring `--strict-asof` (see m2).
- **Example tables.** Round 2 rows 1-5 are unit-tested in `tests/test_align_asof_rules.py`.
  - Row 6 (BTC-USD end stamp, no tolerance) is covered by `test_spot_bar_starting_at_10...` and `test_spot_book_ignores...`.
  - Row 7 (roll boundary) is covered by `test_align_splice.py` and `test_align_stocks_events.py`, and confirmed on real data: recession row ending 2025-10-01 00:00Z has event 2025, not flagged; row 01:00Z has event 2026, `roll_hour=True`, and its change is the new token's own 00:00 to 01:00 change. Every switch row in all 4 panels is flagged (16/18/20/1, 0 unflagged).
  - Round 2b row 1 (fid-10 at -600 s used, age 600) is tested, and holds in real CPI/recession rows (ages 585-596 s from fid-10).
  - Row 2 (fid-10 at +5 s not used) is tested, and holds in real data: the next raw point after each spot-checked row end was at +5 to +30 s and was not used.
  - Row 3 (empty fid-10 response): see m5. **Example row 1 of Round 2 holds only on synthetic data; see m1.**
- **Spot checks against `data/raw` (independent DuckDB as-of, my own formulas).** All values matched exactly:
  - 6 recession rows: level, change, `pm_obs_age_s` and `ret_SPY = log(close/open)`. These were 3 random `both_trading` rows, 1 close-bar whole-hour row (2026-08-11 20:00Z), and the two roll-boundary rows. Every one was served by fid-10.
  - 3 CPI `both_trading` rows (2025-02-24 19:30Z, 2025-04-07 15:30Z, 2025-06-06 16:30Z): implied CPI level Σp·c/Σp, edge mass (0.17-0.19), 1h change and max-token age (594-596 s). All of them came from fid-10 and none used the tolerance.
- **Grid and masks** (all 4 panels):
  - tz is UTC;
  - session-bar starts lie in 09:30-15:30 ET, with none on weekends;
  - rows tile with no gap;
  - 0 `both_trading` rows outside session bars;
  - 0 `both_trading` rows inside the outage;
  - 4-5 `both_trading` rows per pair carry `short_day` (real bars around the 2026-01-30..02-02 Yahoo hole; flagged, which the hand-off allows).
- **Empty fid-10 responses.** The manifest has 15 `empty_confirmed` fid-10 entries: 14 from the 2b run and 1 from 2026-10-01 (a 3.4 h window). Every one has 0 fid-60, 0 fid-10 and 0 fid-1 rows in raw over the same window, so these windows really are dataless.
- **Raw fidelity overlap.** All 579,033 of 579,033 fid-60 points have an identical `(token, t)` at fid-1 or fid-10. The fid-10 stamp offsets within each 10-minute slot sit at 3-10 s.
- No secrets and no data files in the diff.

## Issues

### m1 (minor): the A22 tolerance never fires on real data; tolerant equals strict

- **Where:** `src/poly_actor/align/prices.py:55-62`.
  - `drop_duplicates(["key", "t"])` keeps the finest fidelity, and `_tol_series` is built from the de-duplicated frame.
  - Since A25, every fid-60 point has a fid-10 (or fid-1) twin with the same stamp. So `_tol_series` is empty for every production token.
- **Repro:**

  ```python
  o = DataFrame(
      {"key": "a", "fidelity": [10, 10, 60], "t": [H - 595, H + 5, H + 5], "p": [0.2, 0.7, 0.7]}
  )
  PriceBook(o, 10800, tolerance_s=53).asof("a", [H])
  # -> p 0.2, age 595, used_tolerance False
  ```

  Example row 1 expects 0.7 with the flag set.
- **Consequences:**
  - Whole-hour rows use the fid-10 point about 595 s old instead of the fid-60/fid-10 point stamped 5 s later. That includes the ~500 close-bar `both_trading` rows per pair and all overnight hours.
  - `pm_used_tolerance` is 0 everywhere.
  - The step 6 "strict robustness check" required by CLAUDE.md is identical to the primary run.
  - The A25 text ("53 s tolerance applies ONLY to fid-60 points") describes a code path that real data never takes.
- **Not look-ahead**: this is safer than the approved behaviour.
- **Fix (user decision):**
  - Option (a), recommended: retire A22 by a dated amendment and remove the CLAUDE.md exception, because strict is now at most about 10 min stale everywhere.
  - Option (b): build `_tol_series` from the raw frame before de-duplication, and add a test with duplicate stamps.
  - Either way, state in the A25 text that the tolerant and strict panels are identical.

### m2 (minor): CLI `--strict-asof` wiring is untested

- **Where:** `src/poly_actor/align/cli.py:41`.
- **What happens:** the mutant `pipeline.run_pair(..., False)`, which ignores `args.strict_asof`, passes all tests. Under it, `run --strict-asof` would overwrite the tolerant panel and write no `_strict` file.
- **Fix:** add a CLI test on the synthetic raw dir. Run `run --strict-asof`, then assert that `panel_<pair>_strict.parquet` exists, that the summary key is `<pair>__strict`, and that `pm_stamp_tolerance_s == 0`. Today the risk is nil, because tolerant equals strict (m1).

### m3 (minor, step 6 note): lead-lag rows remain about 10 min stale

- **What happens:** the median age on `both_trading` rows is 592-595 s. At lag 0, the PM level is sampled about 10 min before the bar end, so a small "Polymarket lags" bias remains.
- **Fix:** document this in the step 6 hand-off. Consider fid-1 around session bars if step 6 finds lag-0/lag-1 effects near the margin.

### m4 (minor): the 3 h age cap still admits old quotes into `both_trading`

- **What happens:** the maximum age is 10,795 s (BTC) and 6,588 s (CPI). There are 97 BTC rows (5.7%) and 8-13 rows on the other pairs older than 1500 s. These are capped forward-fills, which give zero or stale changes on session bars.
- **Fix:** have step 6 add an age filter (e.g. `pm_obs_age_s <= 1200`) as a robustness check, or document it.

### m5 (minor): doc wording on empty fid-10 responses

- **What happens:** step4.md 2b row 3 says "logged, not marked covered". The implementation marks the window `empty_confirmed`, i.e. covered after a fid-1 probe; the dry-run then plans 0 calls. That is the step 3 rule, and it is verified dataless here. Separately, the builder counts 14 such responses, and the manifest has 15 fid-10 `empty_confirmed` entries.
- **Fix:** align the hand-off wording and the count.
- **Carried r1 minors still open (docs only):** m4 ("11 of 20 in window") and m5 (`pm_obs_ts` is the oldest quote; now documented in the splice docstring).

## Not checked

- The BTC ladder recomputation from raw for a spot row: r1 verified this, and the ladder code is unchanged in this diff. I did not recompute a Fed level independently; the Fed ages and masks were checked through the panel statistics.
- No live re-fetch of raw data, and no check of the ingest log beyond the summary line.
- The engineering-standard (crusader) minors.

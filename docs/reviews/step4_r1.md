# Step 4 (alignment) validation, round 1

Validator: fresh independent agent, 2026-10-03. Scope: uncommitted `src/poly_actor/align/`, its tests, `data/clean/` panels, A22-A24.

## Verdict

**FAIL: 3 majors, 0 blockers, 7 minors.**

The core machinery is sound. 20 of 20 random panel rows recompute exactly from raw. Bars are end-stamped correctly, including early closes and DST. Splicing never differences across events. The strict panels really are strict. Both variants rebuild byte-identically. Three things still need fixing before step 6:
- the A22 tolerance is wider in scope than approved;
- A22 does not fix staleness on the lead-lag rows (the decision was made on a misleading statistic);
- four look-ahead guards in the pipeline wiring have no test.

## Checked (evidence)

- **`bash scripts/check.sh`:** 267 passed, ruff check and format ok, pairs.yaml reproducible, ingest dry-run ok, CHECK: PASS.
- **Reproducibility.** I rebuilt all 4 pairs, tolerant and `--strict-asof`, into a temp `--clean-dir`. All 8 parquet sha256 match `data/clean/`, and `align_summary.json` is identical (dict equality).
- **Strict mode is strict.** The `_strict` panels have 0 `pm_used_tolerance` rows. Min `pm_obs_age_s` is 20 / 13 / 596 / 0 s (fed / cpi / btc / recession), never negative. Tolerant panels: min age is -50 / -43 / -44 / -53 s, so the 53 s bound holds.
- **Spot checks (independent code).** I wrote my own as-of over DuckDB raw views, my own Fed/CPI/recession formulas from pairs.yaml (derived CPI bucket, edge mass > 0.25, first_usable gate) and my own bar-return and BTC-USD spot lookups. Seed 7 picked 5 rows per pair (3 both_trading plus 2 random). Level, 1h change, every `ret_*` and `both_trading` match within 1e-9 on all 20 rows (0 mismatches). This includes BTC ln(ladder_level) via `select_ladder` and `monotone_ladder_crossing_diag`, run at t with my own quotes, and BTC-USD returns from end-stamped closes.
- **Grid and masks** (fed panel, the same grid for all pairs):
  - Rows tile with no gap or overlap.
  - Session bars start only at 09:30-15:30 ET, with 0 on weekends and 0 `both_trading` outside sessions.
  - Window lengths: 60 min ×2986, 30 min ×496 (last bar), 90 min ×5 (the 5 early closes, e.g. 2025-07-03 15:30-17:00Z and 2025-11-28 16:30-18:00Z).
  - DST: 2025-03-07 (EST) closes at 21:00Z and 2025-03-10 (EDT) opens at 13:30Z with a 13:00-13:30 stub; 2025-11-03 opens at 14:30Z.
  - 501 sessions, 501 open rows. `overnight_gap_*` is non-null only on open rows.
  - 2026-01-30..02-02 Yahoo hole: `ret` is NaN, `short_day` is set, `both_trading` is False.
- **Splice.** Fed switch rows are all flagged (16/16; roll 15:00 ET falls inside a bar). No row differences two events (the `reuse_cross_event` mutant is killed).
- **CPI.** 12 of 21 releases have a valid level at release minus 1h (reproduced; see minor m4). The edge-mass values on dropped releases are 0.278 to 0.91.
- **Summary rates reproduce.** BTC: 6072 / 15100 = 0.402 dropped, all `not_bracketed`. CPI: `edge_mass_gt_max` 6456, valid rate 0.587.
- **Mutation testing.** 27 mutants were run on a temp copy of the repo against `tests/test_align_*.py`. 19 were killed: as-of side, age cap, `active_index` boundary, roll/event interval sides, cross-event reuse, BTC `t + 1h`, BTC and generic first-usable gates, early-close stub, bar end-stamp, return keyed on start, gap previous session, overnight prior segment, fed other-mass, clip, outage, fidelity tie-break. The 8 survivors are listed under M3 and m6. One survivor is equivalent and is not counted as an issue: dropping `is_session_bar` from `both_trading` changes nothing, because equity returns are already NaN outside bars.

## Issues

### M1 (major): the A22 tolerance applies to every fidelity and every instant, not only fid-60 points after the hour

- **Where:** `src/poly_actor/align/prices.py:115`, `src/poly_actor/align/pipeline.py:126`.
- **What happens:** `PriceBook.asof` adds `tolerance_s` for all observations. That includes fid-1 and fid-10 points and the :30 session-bar ends.
- **Raw data:** 11,913 fid-1 and 2,101 fid-10 points sit 1-53 s after a :30 instant, and 11,886 fid-1 points sit 1-53 s after a whole hour.
- **Repro:** fed panel row `ts_end 2024-11-06 19:30Z`, a session bar (the bar ending 14:30 ET). It uses the fid-1 points at 19:30:02 (`pm_obs_age_s = -2`), although strict fid-1 points 58 s old exist.
- **Extent:** 706 Fed `pm_used_tolerance` session-bar rows, 206 of them at :30 ends (cpi 236, btc 50, recession 17 non-whole-hour rows in total).
- **Why it matters:** A22's justification (fid-60 stamp offset p99 53 s) does not apply here. At :30 ends the strict value is never stale, so the tolerance is pure look-ahead in exactly the rows the lead-lag tests use.
- **Fix:** allow `t > x` only for fid-60 observations, e.g. a separate fid-60 series, or require `fidelity == 60` and `t - floor_hour(t) <= 53`. Add tests: a fid-1 point at +2 s must not be used, and a fid-60 point at +2 s at a :30 instant must not be used.

### M2 (major): the lead-lag sample is still ~30 min stale; the A22 decision rested on an all-rows statistic

- **Where:** builder report, Update §1 ("median observation age falls from about 3,590 s to -4..-7 s"), and `report.py:46`.
- **What happens:** session bars end at :30 UTC (or at the close). Most tokens have only fid-60 points stamped at hh:00:xx, so on `both_trading` rows the PM level is about half an hour old.

| pair | median age on `both_trading` rows (tolerant) | strict | rows older than 1500 s |
|---|---|---|---|
| fed | 1793 s | 1794 s | 81% |
| recession | 1786 s | 1792 s | 84% |
| bitcoin | 1794 s | 1796 s | 87% |
| cpi | 1791 s | 1794 s | 81% |

- **Consequence:** A22 barely changes the primary hourly tests (Fed/TLT, BTC/IBIT). A ~30 min "Polymarket lags" bias remains, and the user approved A22 believing the age fell to seconds.
- **Fix:**
  - Report `pm_obs_age_s` on `both_trading` rows in `align_summary.json`.
  - Put this to the user. Options: pull finer fidelity around session bars; accept the bias and document it for step 6 (lag 0 = PM sampled ~30 min before the bar end); or sample PM at the bar-start-plus-1h whole hour and drop the :30 alignment.

### M3 (major): look-ahead guards in the pipeline wiring survive mutation

Each of these mutants passes all align tests:

| mutant | where | effect |
|---|---|---|
| `PM_STAMP_TOLERANCE_S = 54` and `= 300` | `consts.py:17` | Tests hard-code `TOL = 53` (`tests/test_align_prices.py:67`, `test_align_panel.py:164`), so nothing pins the production constant. |
| `run_pair`: `tolerance_s = PM_STAMP_TOLERANCE_S` even when `strict` | `pipeline.py:165` | `--strict-asof` would silently be tolerant. |
| spot book gets the PM tolerance | `pipeline.py:127` | BTC-USD spot is no longer strict. |
| `spot_obs` stamps BTC-USD at bar START (drop `+ HOUR_S`) | `pipeline.py:89` | 1 h look-ahead in `ret_BTC-USD` (the REQUIRED control of primary test 2) and in `skew`. |

- **Fix:**
  - Assert `PM_STAMP_TOLERANCE_S == 53` and use the constant in the boundary tests.
  - Add a pipeline test on the synthetic raw dir: the strict build has `pm_obs_age_s >= 0`, and the tolerant build uses the constant.
  - Add a unit test of `spot_obs` (a bar starting 10:00Z is usable at 11:00Z, not at 10:59:59Z).
  - Add a test that the spot book ignores a close stamped after the instant.

### Minors

- **m1. A row ending exactly at a roll takes the new event and is not flagged** (`events.py:353-361`, `splice.py:247`).
  - `active_index(end)` puts a row (r-1h, r] on the new event. `roll_hour` (start <= r < end) then flags the next row (r, r+1h], which is a clean same-event row.
  - This affects every CPI, BTC and recession switch: 20, 18 and 1 unflagged switch rows. The old event also loses its final hour, which the +1h roll was meant to keep.
  - Finite changes on switch rows: BTC 2025-06-01 05:00Z, BTC 2026-02-01 06:00Z, recession 2025-10-01 00:00Z. None of these are session bars, but they enter `pm_overnight_change`.
  - Fix: pick the event active over the window interior (`use_from < end <= use_until`), or flag `start < r <= end`. Test with a roll on a row boundary.
- **m2. `outage_mask` rows can be `both_trading`.** Example: fed, recession and btc on 2025-10-29 14:30Z. Inside the outage the 3 h age cap forward-fills levels (ages up to 8,395 s), which gives artificial zero changes. The hand-off said "mask those hours". Fold `~outage_mask` into `both_trading`, or make step 6 exclude it explicitly.
- **m3. pairs.yaml `us_cpi_inflation.signal.drop_rule` still says "edge_mass > 0.1".** A23 says it supersedes the yaml. Update `scripts/build_pairs.py`, or annotate the yaml.
- **m4. "12 of 21 usable releases" includes 2026-09.** Its release (2026-10-14) is after the panel end; the level used is the 2026-09-30 20:00Z row. The in-window figure is 11 of 20.
- **m5. `pm_obs_ts` is `ts_end - max(age)`, the oldest quote used** (`splice.py:249`). On multi-token pairs it does not identify the observation that used the tolerance. Document this or rename the column.
- **m6. Non-look-ahead boundaries survive mutation:**
  - CPI edge threshold `> 0.25` mutated to `>= 0.26` (no test between 0.25 and 0.26);
  - `both_trading` without the `signal_change.notna()` term;
  - `used_tolerance` mutated to `< -1` (no -1 s case).
- **m7. `align_summary.json` is written with `write_text`** (`cli.py:46`), not with the temp-file-and-rename used for panels.

## Not checked

- The BTC `select_ladder` and A20/A21 rung logic itself; this round only checked that the panel feeds it time-t inputs correctly.
- Per-month BTC drop shares and the CPI clip-binding rate beyond equality with the code's summary.
- Live re-fetch of raw data.
- The crusader minors carried from step 3, beyond the two the builder fixed.

# Step 4 build report, round 1 (alignment)

Status: built, `bash scripts/check.sh` prints CHECK: PASS (260 tests, ruff clean, pairs.yaml reproducible). Nothing committed.

## How to run
- Build all panels: `.venv/Scripts/python.exe -m poly_actor.align run` (about 35 s; `--pairs a,b` for a subset, `--clean-dir` to redirect).
- Print sizes and flag rates from existing panels: `.venv/Scripts/python.exe -m poly_actor.align report`.
- Outputs (derived, git-ignored, rebuildable): `data/clean/panel_<pair>.parquet` and `data/clean/align_summary.json`. Re-running gives byte-identical files (sha256 checked on us_recession; a test checks it for all outputs and also checks raw is untouched).

## Files
New in `src/poly_actor/align/`: `consts.py`, `prices.py` (as-of lookup, age cap, clip), `grid.py` (XNYS sessions, bar re-stamp, tiled row grid), `events.py` (events from pairs.yaml, active window), `signals.py` (pure formulas), `evaluate.py` (Fed, CPI, BTC, recession level at instants), `splice.py` (change splicing, roll and event flags), `stocks.py` (bar returns, opening gaps, short days), `panel.py`, `report.py`, `pipeline.py` (I/O), `cli.py`, `__main__.py`.
Tests: `tests/test_align_{prices,grid,signals,splice,panel,evaluate,stocks_events,report,pipeline}.py` and the helper `tests/align_synth.py`. 61 new tests.
Carried-over minors fixed (code step 4 touches): `ladder: str` is now `Ladder = Literal["up", "dip"]` in `pairs.py`; `pyproject.toml` pytest `addopts` now has `-m "not live"` (marker text updated).

## Design decisions (each is a choice the validator should check)
1. **Row = window.** A row is the half-open window (start, end], stamped by `ts_end` (UTC). Inside XNYS sessions rows are exactly the stock bars (09:30 start bar ends 10:30 ET, ..., last bar 15:30 to 16:00; early close 11:30 bar ends 13:00, from `cal.early_closes`). Outside sessions rows are whole UTC hours, plus a 30-minute stub row ending at each session open. Rows tile the timeline with no overlap (tested). This is the only way to get "bar-end-stamped" stock returns and an hourly 24/7 grid in one table.
2. **Resampling rule.** Every Polymarket and BTC-USD value at an instant is the last observation stamped at or before it, never later (`PriceBook.asof`). fid=60/10/1 are merged, finest fidelity wins on equal timestamps. Fid-1 probe records with zero rows contribute nothing (no data, not a price).
3. **No forward fill.** An observation older than 3h is treated as missing (`MAX_PM_AGE_S`, `MAX_SPOT_AGE_S`).
4. **Splice.** The event for a row is the one active at `end`. Change = that event's level at `end` minus the same event's level at `start`; no cross-event differencing. `roll_hour` = a roll time r with start <= r < end (covers the "bar starting at the roll time" and rolls inside a window). `event_hour` = official event time in (start, end]. Fed and recession events may be evaluated before their `use_from` (Fed from `gamma_start`, recession from the market's own start) so the roll row has a start level; CPI and BTC are gated by `first_usable_utc`.
5. **Stock return** = log(close/open) of the end-stamped bar (the bar's own window). Opening gap = log(first-bar open / previous session's last-bar close), placed on the session-open row; NaN if either bar is missing (Yahoo hole 2026-01-30..02-02, NaN bars). `pm_overnight_change` = sum of spliced PM changes over the non-session rows between the previous close and the open (NaN if any is missing).
6. **BTC.** `signal_level` is ln(ladder_level); `signal_change` is therefore the pre-registered hourly change in ln(ladder_level). Also `k_up`, `k_dn`, `half_width`, `skew`, `btc_spot`, `n_up`, `n_dip`, `n_partial`, `pav_pooled`. Selection uses `select_ladder` (A20/A21) and `monotone_ladder_crossing_diag` unchanged. `ret_BTC-USD` is the as-of spot return over the same window (at a :30 stamp the latest closed hourly bar is up to 30 minutes old; no look-ahead).
7. **Fed** drops hours with any bucket unquoted (strict, never filled) and other_mass > 0.25. **CPI** drops edge_mass > 0.10 and unquoted components; clip binding = sum(plus) < sum(minus).
8. `both_trading` = session bar row, every equity of the pair has a finite bar return, signal level and signal change finite. `outage_mask` = window overlaps 2025-10-29 09:00-14:00Z. `short_day` = session date with fewer bars than expected for any pair equity (recomputed from raw with `ingest.stocks.stock_gap_table`, matches stock_gaps.csv logic).

## Columns
`ts_end, ts_start, window_minutes, is_session_bar, is_session_open, session (ET date), event_id, signal_level, signal_reason, signal_change, roll_hour, event_hour, pm_age_s (largest age of any quote used), clipped_p_gt1, [pair extras: other_mass | edge_mass, cpi_has_derived, cpi_clip_binding | k_up, k_dn, half_width, skew, btc_spot, n_up, n_dip, n_partial, pav_pooled], outage_mask, short_day, ret_<TICKER>, overnight_gap_<TICKER>, pm_overnight_change, pm_overnight_n_missing, both_trading`.
`signal_reason` is one of ok, no_active_event, before_first_usable, missing_quote, zero_mass, other_mass_gt_max, edge_mass_gt_max, no_rungs, not_bracketed, start_unavailable (level valid, change not).

## Real-data results (all four panels: 18,012 rows, 2024-10-01T01:00Z to 2026-09-30T20:00Z; 3,487 session-bar rows; 501 session-open rows)
| pair | both_trading rows (share of session rows) | level valid (of in-scope rows) | roll_hour rows | event_hour rows |
|---|---|---|---|---|
| fed_decision | 3,470 (99.5%) | 99.99% | 16 | 16 |
| us_recession | 3,009 (86.3%; market starts 2025-01-08) | 99.99% | 1 | 0 |
| bitcoin_monthly_ladder | 1,695 (48.6%) | 59.9% | 20 | 20 |
| us_cpi_inflation | 1,015 (29.1%) | 35.5% | 20 | 20 |

Common to all: `outage_mask` 6 rows; `short_day` 14 rows (2 sessions); `unmatched_bars` 0; NaN bars 0; stock return missing on 0.46-0.49% of session rows (the Yahoo hole); median `pm_age_s` about 3,590 s.
- Prices clipped (p > 1) rows: Fed 1, others 0 (209 raw rows have p > 1; only 1 panel row consumed one as the as-of observation, the rest are not the latest observation at any panel instant or sit outside the active events; not broken down further).
- **BTC** (in-scope = active event past first usable, 15,100 rows): dropped 6,059 = 40.1% (all `not_bracketed`; 0 `no_rungs`); month-start gap rows (before_first_usable) 612; no-event rows 2,300 (2025-03, 2025-12 gaps and before 2024-11-02); PAV pooled on 22.9% of evaluated hours; hours with at least one partial-window strike 12.1%. Per-month not-bracketed share ranges 0% to 98% (2024-12, 2025-02, 2025-07 about 93-98%; 2025-04, 2025-08, 2025-11, 2026-07..09 0%).
- **CPI**: `edge_mass_gt_max` drops 10,089 of 15,642 in-scope rows (64.5%). Months 2024-11 to 2025-08 (4 to 5 buckets) are 81-100% dropped. Only 10 of 21 releases have a valid level on the row at or just before release minus 1h. Derived-bucket clip binds on 11.8% of 731 hours with a complete derived bucket (A19 metric).
- Fed: 1 `missing_quote` row (2025-10-29 outage), 2 `start_unavailable`.

## Self-check against lessons.md and the checklist
- CLOB live point / window boundaries: n/a to alignment; as-of rule and `t <= instant` tested.
- yfinance start-stamped bars: re-stamped via XNYS calendar and `early_closes`; tests cover EST, EDT, the DST switch week (2025-03-07 vs 03-10) and 2025-11-28 early close.
- Snapshot fields: BTC selection uses only `created`, `closed_time <= t`, quotes at or before t; `inactive` is the documented structural exception (A21).
- Splice on changes; `roll_hour`; ladders one rung per strike; both-trading only mask: done. Overnight kept in a separate column.
- Mutation tests (guard removed, test failed): as-of look-ahead (`-1`), age cap, clip, bar end-stamp, early-close stub, same-event reuse in splice, roll flag, return stamped at start instead of end, first-usable gate, 24h rung age, edge-mass threshold, outage window, overnight segment. All 13 killed. The mandatory future-data invariance tests (splice and panel) also kill the look-ahead mutant on their own.
- Spot-checks against raw (independent DuckDB query): Fed 2025-06-04T03:00Z level -0.698603, 2026-02-10T16:30Z -4.116617, 2025-11-05T21:00Z -16.596535 all equal; TLT 2025-06-04 13:30Z bar log(86.0/85.795)=0.002387 on the row ending 14:30Z; XLF 2025-11-28 early-close bar 16:30Z to 18:00Z (90 minutes) return -0.001965 matches.
- Crusader bar: new functions typed and documented, constants named, no `except`, no prints in pure code, writes via temp file and rename. `evaluate_btc` was split after it passed 60 lines.

## Known limits and decisions needed
1. **PM sampling lag (needs a decision).** fid=60 points are stamped a few seconds after each hour, so the strict as-of rule picks the previous hour's point: median `pm_age_s` is about 1h. The Polymarket level at an hour is effectively the price one hour earlier. That is the pre-registered "last observation at or before" rule, applied as written, and it is what no-look-ahead requires; but it biases any lead-lag toward "Polymarket lags" by up to an hour. Step 6 should be told; a tolerance of a few seconds would be a dated amendment and a (tiny) look-ahead.
2. **CPI edge-mass rule drops 65% of hours** and 11 of 21 releases have no usable pre-release level (4-5 bucket partitions in 2024-11 to 2025-08 are almost never below 0.10). Primary test 3 (release-day event study) rests on the 10 remaining releases. Options: accept, or amend the threshold (dated amendment).
3. **BTC `not_bracketed` drops 40% of hours** (no dip or up rung with P above 0.5 within the quoted range, e.g. dip ladder when spot sits just above the nearest rung). Pre-registration says no extrapolation, so hours are dropped. PAV pooling is not rare (22.9%), contrary to the A20 expectation; step 3 only guessed it would be small.
4. The BTC-USD return at :30 stamps is up to 30 minutes stale (hourly bars only); alternatives need minute data.
5. Last-bar and early-close bars are 30 and 90 minutes long (`window_minutes`); step 6 may want to exclude or scale them. The first row of the panel has no start level (`start_unavailable`).
6. Fed `first_usable` uses `gamma_start`; recession uses the market start; neither is in pairs.yaml explicitly (derived in `events.py`).
7. Not done (out of scope for this step): spreads (XLF - SPY, IWM - SPY) are left to analysis; no `--break-lock` for ingest; the other crusader minors (time parsers, `--asof`, `run_stocks` length) were not touched.

## Update after user decisions (2026-10-03)
Applied without committing. Amendments A22, A23, A24 appended to `docs/preregistration.md`; one line added to `docs/handoff/lessons.md`; note added to `docs/step2_pairs.md` (CPI threshold).
1. **A22 sampling tolerance = 53 s** (`PM_STAMP_TOLERANCE_S` in `align/consts.py`). Measured on all 576,638 raw fid=60 rows: stamp offset after the hour is 0-59 s (p50 9, p95 38, p99 53, max 59); 53 s is the smallest whole second covering 99%. An observation stamped up to 53 s after the instant may be used; stocks and BTC-USD spot stay strict. New columns `pm_obs_ts`, `pm_obs_age_s` (negative = tolerance used), `pm_used_tolerance` (replaces `pm_age_s`). Strict mode: `python -m poly_actor.align run --strict-asof` writes `panel_<pair>_strict.parquet` and summary key `<pair>__strict`; `align_summary.json` has `pm_used_tolerance_share` and `pm_stamp_tolerance_s`.
   Effect: median observation age falls from about 3,590 s to -4..-7 s. Share of rows with a valid level that used the tolerance: fed 81.4%, recession 77.4%, bitcoin 80.9%, cpi 81.5%.
2. **A23 CPI edge-mass primary threshold 0.25**; 0.10 kept as per-hour `edge_mass_strict_ok` (60.5% of valid levels pass it). CPI level valid on 58.7% of in-scope rows (was 35.5%); usable releases (valid level on the row at or just before release minus 1h) 12 of 21 (was 10 of 21); both_trading rows 1,759 (was 1,015).
3. **A24** BTC rule kept, recorded only. BTC with tolerance: dropped 40.2%, PAV pooling 23.0%, both_trading 1,690.
Strict-variant numbers differ by under 0.1 percentage point on valid-level and both_trading counts (fed 3,470, recession 3,009, bitcoin 1,695, cpi 1,761), as expected, since the tolerance changes which observation is picked, not coverage.
Tests: 7 new (tolerance at +52 s used, +54 s not used, exactly +53 s used, strict never flags, flag/age/ts on the panel, CPI 0.25/0.10 threshold and flag); total 267 passing; `scripts/check.sh` prints CHECK: PASS.

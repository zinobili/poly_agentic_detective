# Step 8 build report: election-study data (milestone 2)

Plumbing only: no return-vs-odds statistics were computed. Pre-registration untouched.
Milestone-1 modules and tests untouched (mutation tests edited three of them temporarily and
`git checkout` restored them; `git status` shows no tracked change).

## Files
- `config/election.yaml`: signals (event, market, Yes token, question, created/closed), 7 moratorium
  markets, universe (29 AI in 4 sub-baskets + 29 placebo, one-line `why` each), controls, futures,
  vol indices, windows, as-of caps.
- `src/poly_actor/election/`: `config.py` (typed load + `validate`), `ingest.py` (CLOB specs reusing
  `ingest.polymarket`; yfinance fetch/plan/run with manifest; raw readers), `panel.py` (builders +
  `build_all`), `coverage.py`, `cli.py`, `__main__.py`.
- Tests: `tests/test_election_config_ingest.py`, `tests/test_election_panel.py` (30 tests).
  Fixtures `tests/fixtures/election/`: real CLOB response around the 3 Nov close, NVDA 1h (both DST
  switches + 2025-11-28 early close), NVDA 1d, NQ=F 5m at 19:00 ET.
- Reused: `ingest.polymarket` (tiling, clip, manifest, empty handling), `ingest.common`,
  `ingest.stocks.parse_bars/expects_rows`, `align.grid` (sessions, `bar_table`, `restamp_bars`),
  `align.prices.PriceBook` (as-of), `align.stocks.bar_log_returns`.

## How to run
```
.venv/bin/python -m poly_actor.election ingest --workers 4 [--dry-run] [--only pm|yf]
.venv/bin/python -m poly_actor.election panel
```
Raw: `data/raw/election/{polymarket,yf}/` (add-only, manifests inside). Clean:
`data/clean/election/*.parquet` + `coverage.json`. 563 raw parquet files, 18 MB.

## Real pull
- Polymarket: 289 calls, 324,735 rows, 0 failures. yfinance: 274 calls, 231,618 rows, 0 failures.
- Second `ingest`: 0 calls both sources; sha256 of all raw parquet identical before/after.
  `panel` re-run: byte-identical `coverage.json`.
- Tables (rows): daily 23,424 (64 tickers x 366 sessions, 2025-06-02..2026-11-12), odds_daily 1,464,
  hourly 162,587, odds_hourly 10,200, night_5m 573 (555 in the H3 window), vol_daily 13,368,
  moratorium_daily 33.

## Coverage (see `coverage.json`)
| Table | Missing share, all rows | Missing share, in-life rows | Median age_s | p95 age_s |
|---|---|---|---|---|
| odds_daily (4 signals) | 10.5% | 1.4% (18 of 1,326) | 590 | 597 |
| odds_hourly | 10.9% | 1.7% | 590 | 597 |
| night_5m, NQ rows in H3 window (fid 1 only, cap 10 min) | p_sen 22.7%, p_house 8.1%, p_sweep 0%, p_rr 0% | | ~41 | ~43 |
| moratorium_daily | 0% for 6 states, North Carolina 15.2% | | | |

"In-life" = instant between market creation and close (study end for open markets); before creation
and after resolution rows are missing by construction.
- fid-60 and fid-10 points are stamped 14 s (median) and up to 59 s after the grid line, and fid 10
  sits on a 10-minute grid. Daily closes and hourly bar ends are on the same grid, so the freshest
  point is always about 10 minutes old (median 590 s, never fresher than the stamp offset allows).
  Strict as-of is kept (no tolerance). The odds are never fresher than ~10 min outside the
  fid-1 window (lesson 10).
- Tickers: no missing daily sessions for any of the 64 (CRWV complete from 2025-06-02). Hourly: every
  ticker is short exactly 2 sessions, 2026-01-30 and 2026-02-02 (the known Yahoo hole), 9 bars for
  NVDA etc. (2,541 of 2,550); RSP also has 2 off-grid bars (unmatched, not shifted); ^VVIX has fewer
  daily rows (2,221 vs 2,229).
- CLOB `prices-history` clock offsets are listed in `coverage.json: clob_stamp_offsets`.

## Spot checks against an independent re-fetch
Odds (fid 10 re-fetch, last point at or before the close): p_sen 2026-10-30 close 20:00Z: 0.705, age
558 s (panel identical); p_house 2026-03-02 21:00Z: 0.845, 576 s (identical); p_sweep 2025-11-28 early
close 18:00Z: 0.31, 589 s (identical). Returns (yfinance 1d auto_adjust re-fetch): NVDA 2026-11-04
-0.032253, CRWV 2026-11-04 -0.104245, JPM 2025-11-28 +0.017528 (all identical to 6 dp).

## Tests and mutations
- Rules as examples, each a test: 20:58:00 vs 21:00:05 point (age 120 s); 7 h old reading -> p, dp
  missing this and next session; 15:30 ET bar end 21:00Z / 20:00Z (both sides of 2 Nov 2025 and
  8 Mar 2026), early close 18:00Z for odds and bars; futures 19:00 ET bar ends 19:05 ET, point at
  :05:00 used, :05:01 not; clip of a point after `endTs`; missing session not forward-filled; second
  ingest = 0 calls + identical hashes (CLOB and yfinance); empty yfinance frame retried, then a
  recorded failure; config 29 + 29, 4 sub-baskets, no overlap.
- Mutations (each applied temporarily, tests run, restored with git checkout): as-of `side=left`
  (2 tests fail), as-of allowing the next point (10 fail), age cap removed (4 fail), clip removed (2),
  clip `<= end` (initially SURVIVED, test added with a point at t == end, now killed), early-close
  edge dropped (1 fails). All killed.

## Findings and deviations to decide
1. **Event-window dp_sen cannot be built at the daily close.** The p_sen market closed
   2026-11-04 10:54 UTC (CLOB last point 10:54:19); the 4 Nov 21:00Z close is ~10 h later, so the 6 h
   rule makes p_sen missing on 4 Nov and after (p_house closed 13:06Z, p_sweep 17:47Z, p_rr 17:14Z: same
   outcome). The 3 Nov close reads 0.745 (age 40 s), not the 0.755 quoted in the pre-registration
   (0.755 was the 20:40 UTC reading). Options: run the event window on the fid-1 night data, or a
   dated amendment for a different cap on 4 Nov. Not changed here.
2. **No trades 2025-07-11 20:10 -> 2025-07-18 18:24 UTC** for p_sen (confirmed with fid 1/5/30/60
   probes: the server returns nothing). The first 4 sessions of the pre-election sample
   (2025-07-14..17) have missing odds for all 4 signals.
3. **night_5m odds missing at the end of the H3 window:** p_sen from 11:05 UTC (market closed
   10:54), 22.7% of the window's NQ bars; p_house 8.1%.
4. Data end: the pull ends at ET midnight of 2026-11-13 (last session 2026-11-12), because 13 Nov was
   in progress when the data was pulled, not "2026-11-13" inclusive.
5. Hourly yfinance bars are unadjusted (as milestone 1); only the 1d pull uses auto_adjust=True.
   Futures 1h bars (2025-07-01 onward) are in raw only; no clean table was specified for them.
6. Whole-life fid 60 and fid 10 end at Gamma `closedTime` + 1 h (CLOB points continue ~20 s past
   closedTime); fid-1 window clipped to the same end. `closedTime` only bounds the pull.
7. Hourly `ret` is log(close/open) of the bar (milestone-1 convention), not close-to-close
   between bars.

## Self-check
Lessons: CLOB clip and padding (reused, tested + mutated); DST via zoneinfo and real calendar
(tested both switches); bar end-stamping and early closes via `align.grid`; fid-60 offset measured
and reported; no snapshot field selects data at t (`closed` only bounds the pull window); paginating
not applicable (token ids matched by question text, asserted unique); empty frames fail loudly;
rules fire on real data (early-close 2025-11-28, missing-session list, stale rule hits the post-close
rows). `bash scripts/check.sh`: PASS (507 passed, 1 skipped; ruff check and format ok).

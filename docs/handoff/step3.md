# Step 3 hand-off: price ingestion

**Status:** committed 03ad9eb, validator round 1 PASS WITH ISSUES. A fix round is built but **not validated or committed**.

**Next:** validator round 2, scoped to the fix-round diff and the round-1 majors below. Re-check model: sonnet.

## Round-1 majors (must be fixed)
1. **Fidelity-60 holes.** About 1,962 interior gaps longer than 3h, mostly in 2026-03/04.
2. **Empty 200 marked covered forever.** A trading market that returns an empty 200 was never retried.

## Fix round: what the builder claims
- **Backfill.** A fidelity-10 pass covers fid-60 gaps over 3h: 1,893 gaps, 1,882 filled, 10 partial, 1 unfilled. All 11 remaining are one upstream outage, 2025-10-29 09:00–14:00Z. The inventory is in `data/scratch/step3/gap_inventory.csv`. Fidelity 10 is sparse too (spacing up to about 50 min), but it is under the 3h criterion.
- **Empty handling.**
  - An empty response inside the token's life is recorded as `status=empty`, which `covered()` never counts as covered.
  - Each one is probed once at fidelity 1; if that probe is also empty it becomes `empty_confirmed`.
  - Legacy `ok` records with 0 rows inside the life were re-fetched.
  - Totals: 31 empty, 31 empty_confirmed.
- **Manifest robustness.**
  - A torn final manifest line is skipped with a warning.
  - A lock file `data/raw/.ingest.lock` (O_EXCL) stops concurrent runs. A stale lock after a crash must be deleted by hand.
- **Window end.** The last window ends at `floor(asof − 10min, hour)`.
- **Stocks.**
  - A bar-count check against XNYS (early closes have 3 bars) found 23 short days, listed in `data/scratch/step3/stock_gaps.csv`.
  - A 1-day lag before freezing stock data.
  - No sleep after the last failed attempt, and the sleep is injectable for tests.
- **Tests.** Write-once leaves bytes unchanged, literal 60s pad, 15d+1s window, plus 22 new tests in `tests/test_ingest_fixes.py`.
- **Docs.** `docs/step3_ingestion.md`.
- **Results.** 162 tests pass and ruff is clean. A re-run at fixed `--asof 2026-10-01T14:00:00Z` made 0 calls.
- **Row counts.** fid60 576,638 (697 tokens), fid10 47,567 (109), fid1 743,602 (238).

**Also in this round:** `--workers N` (default 4) for concurrent Polymarket downloads, added by the main agent. There is one worker per token, windows run in order within a token, and the manifest and stats are guarded by a lock. Test: `test_parallel_workers_match_sequential_run` (163 tests pass).

**Changed files:** `src/poly_actor/ingest/{cli,common,polymarket,stocks,targets}.py`, `tests/test_ingest.py`, `tests/test_ingest_fixes.py` (new), `docs/step3_ingestion.md` (new).

## What round 2 should check
- **Backfill correctness:** no look-ahead in the `fid=10` rows, and they stay inside each token's life.
- **Empty logic** and its tests.
- **The lock.**
- **The bar-count check** against exchange_calendars.
- **The 1-day lag.**
- **Concurrency:** check thread safety of the manifest appends and `write_parquet_once` under concurrent workers, and whether 4 workers at a 0.25s pause stay within the API rate limit.
- **Mutation tests:** remove the write-once guard, set the pad to 0, and make "empty" count as covered. Each should be killed by a test.

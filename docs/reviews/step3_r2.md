# Step 3 review, round 2

## Verdict
PASS WITH ISSUES. Both round-1 majors are fixed and verified against the data on disk. One new major: the torn-manifest-line recovery does not survive the next append.

## Checked (evidence)
- scripts/check.sh: 163 tests pass, ruff ok, pairs rebuild reproducible, dry-run ok.
- Round-1 major 1 (fid-60 holes): recomputed on data/raw across all fidelities. 11 interior gaps > 3h remain, max 12600s (3.5h), none > 6h. The inventory shows 1882 filled, 10 partial, 1 unfilled, all on 2025-10-29 09:00Z. This matches the claim.
- Backfill look-ahead: all 4591 ok-record files for fid=10 (47,567 rows) lie inside [start_ts, end_ts) and have t <= fetched_at. 0 bad files. All 109 fid=10 tokens sit inside their token life (0 outside).
- Round-1 major 2 (empty 200): manifest has 31 empty and 31 empty_confirmed, 0 failed. Logic read: an empty response overlapping the life is "empty" (never covered); older than 48h it is probed at fid=1, then "empty_confirmed"; legacy 0-row ok windows in the life are re-fetched.
- Mutations (PYTHONPATH temp copy), each killed by a test:
  - write-once removed: test_write_parquet_once_never_overwrites
  - BOUNDARY_PAD=0: test_polymarket_run_is_idempotent_and_manifested
  - empty counted as covered (two variants): test_empty_200_recent_is_not_covered_and_retried
  - legacy zero-row refetch removed: test_empty_outside_life_..._refetched
  - LAG_DAYS=0: test_stock_target_end_has_one_day_lag
  - early close expects 7: test_stock_gap_table_flags_short_days...
  - O_EXCL removed: test_ingest_lock_is_exclusive_and_removed
  - PUBLISH_LAG=0: test_last_window_ends_ten_minutes...
- Bar-count logic: 7 bars on regular days and 3 on early closes (the 11:30 bar runs to 13:00), taken from cal.early_closes. This is consistent with lessons.md.
- 1-day lag: end = ET midnight of yesterday, so the last stored day is the day before yesterday. Correct.
- Concurrency: manifest appends and stats are under one lock; one worker per spec, with windows in order. Paths are unique per (token, fid, window), so the write-once tmp name does not collide in practice. Rate: 4 workers at 0.25s pause is about 10-16 req/s at most, and there were 0 failed records, so no 429s showed up. I made no live calls.

## Issues
- MAJOR: src/poly_actor/ingest/common.py:~186 (Manifest.append) with :164 (read).
  - Torn-line skipping is not durable. `append` does not guard against a final line with no newline.
  - Repro: write a partial line, read (skipped OK), append two records, read again. The result is `JSONDecodeError`. The first post-crash append glues onto the torn line and is lost. After the second append the corruption is interior, so every later run raises.
  - Fix: in `append`, if the file is non-empty and does not end in "\n", write "\n" first. Add a test that appends after a torn line.
- MINOR: stale lock after a hard crash needs a manual delete. It is documented, and the message says so. Could store the pid and check it.
- MINOR: no test of concurrent manifest or write_parquet_once safety beyond the sequential-parity test. The probe's fid=1 window could in theory equal a fid=1 spec window in another worker (tmp-name race). Practically unlikely.
- MINOR: probe records are written as status=ok with n_rows=0 at fid=1, so for a fid=1 spec overlapping the life they count as not covered (harmless refetch).
- MINOR: the "partial" label in the inventory means only "worst remaining gap > 3h" (all 11 are <= 3.5h).
- MINOR: the 31 "empty_confirmed" windows are covered forever on the strength of one fid=1 probe, which is the intended policy.

## Not checked
Live API behavior and rate limits (no network calls made); stock_gaps.csv contents; the docs text; the full-suite flake risk of the parallel test.

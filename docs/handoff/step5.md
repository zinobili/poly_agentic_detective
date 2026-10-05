# Step 5 hand-off (dashboard)

Plan to be written at the start of step 5. Reference: `docs/design/dashboard_ux.md` + `docs/design/dashboard_mockup.html`.

## Minors carried over from step 4 validator r2 (docs/reviews/step4_r2.md)
- **m1 — A22 tolerance never fires on real data.** Every fid-60 point has a fid-1/fid-10 twin at the same stamp; dedup keeps the finer one, so strict == tolerant byte for byte and `pm_used_tolerance` is 0 everywhere. Not look-ahead (stricter than approved). **User decision pending:** retire A22 with a dated amendment (recommended), or build the tolerance series before dedup.
- **m2:** no test that the CLI passes `--strict-asof` through (`align/cli.py:41`); that mutant survived.
- **m3:** lead-lag rows are ~10 min stale (median ~594s). Step 6 must state it and read lag-0/lag-1 with that in mind.
- **m4:** quotes up to 3h old still enter `both_trading` (97 BTC rows > 1500s). Consider a max-age cut-off in step 6 (pre-register it before looking at results).
- **m5:** the hand-off wording on empty fid-10 responses doesn't match the code; empty count is 14 in the build report vs 15 in the manifest. Reconcile the doc.

## Minors from crusader push review 2026-10-05 (docs/reviews/push_2026-10-05_crusader_r1.md)
Fix where step 5 touches the code: `pipeline.py` bare StopIteration on unknown pair id, unguarded `max()` on empty `stamped`, `build_pair_inputs` ~65 lines, `event_tokens` → `Event.tokens()`; `align/cli.py` errors to stdout (use stderr/logging), `time.time()` → `perf_counter`, missing docstrings/TypedDict, unlocked summary read-modify-write, corrupt-JSON error without path; `targets.py` repeated `(FID_LIFE, FID_DENSE)` loop in four planners.

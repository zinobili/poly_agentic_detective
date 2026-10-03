# Step 4 build, round 2 (fix batch after validator r1 FAIL)

## Files changed
- Ingest: `src/poly_actor/ingest/targets.py` (new `FID_DENSE = 10` target: full life of every fed_decision and bitcoin_monthly_ladder token; docstring updated).
- Alignment: `align/prices.py` (freshest-across-fidelities as-of; tolerance only for fid-60 at whole-hour instants), `align/consts.py` (`TOLERANCE_FIDELITY`), `align/events.py` (`active_index`: use_from < x <= use_until), `align/splice.py` (docs), `align/panel.py` (`both_trading` excludes outage rows), `align/report.py` (`pm_obs_age_s_both_trading` median/p90/n), `align/cli.py` (summary written atomically), `align/signals.py` (docstring), `pairs_build/cpi.py` + `config/pairs.yaml` (drop_rule text now says superseded by A23).
- Docs: `docs/preregistration.md` (A25), `docs/progress.md`.
- Tests: new `tests/test_align_asof_rules.py`, `tests/test_align_both_trading.py`; edits in `test_align_prices/panel/pipeline/splice/evaluate/stocks_events`, `test_ingest_fixes`.

## Ingestion (M2 = A)
- Dry run: 2,961 calls (under the 3,000 stop line; 2,894 fid-10, 67 fid-60 for new hours since last asof).
- Real run, `--workers 4`, background: 761 s, 2,961 calls, 2,658,842 rows, 0 failures, 0 empty. No 429 or retry lines in the log. Re-run dry-run: 0 calls (idempotent). Raw untouched apart from additions.

## Rules to tests (the table in step4.md)
All seven rows have tests (`test_align_asof_rules.py`, `test_align_splice.py`, `test_align_stocks_events.py`). Extra: freshest across fidelities, fid-1 at +2 s on a whole hour not used, -1 s age flagged.

## Mutation check (run by hand on the new code, each killed by the offline suite)
Tolerance constant 54; `TOLERANCE_FIDELITY` 10; strict ignored in `run_pair`; BTC-USD stamped at bar start; tolerance on :30 instants; `used_tolerance < -1`; `active_index` side; `both_trading` without outage or without `signal_change.notna()`; CPI edge 0.26. Survivor by design: giving the BTC-USD spot book a tolerance is harmless because spot rows carry no fid-60 label, so it cannot look ahead. `test_spot_book_ignores...` pins that.

## Results: `pm_obs_age_s` on `both_trading` rows (seconds)
| pair | variant | n | median | p90 |
|---|---|---|---|---|
| fed_decision | tolerant | 3469 | 594 | 597 |
| fed_decision | strict | 3469 | 594 | 597 |
| bitcoin_monthly_ladder | tolerant | 1691 | 595 | 598 |
| bitcoin_monthly_ladder | strict | 1691 | 595 | 598 |
| us_cpi_inflation | tolerant | 1759 | 1791 | 1797 |
| us_cpi_inflation | strict | 1761 | 1794 | 3591 |
| us_recession | tolerant | 3008 | 1786 | 1796 |
| us_recession | strict | 3008 | 1792 | 3584 |

Target (Fed and BTC median <= 600 s) met. Fed/BTC tolerant and strict are identical, with 0 `pm_used_tolerance` rows. Rows older than 1500 s: fed 13, btc 97.

## Known limits / decisions needed
- CPI and recession are still ~30 min stale on session rows (fid-10 was scoped to Fed and BTC by the decision). Needs a user decision: extend fid-10 to them (about 15 CPI/recession tokens' worth of calls is small) or accept and document.
- Row counts changed (e.g. cpi 1759 vs 1761) because of the roll-boundary and outage fixes.
- Minors left: m4 (docs wording "11 of 20 in window"), m5 documented only (`pm_obs_ts` = oldest quote), validator-listed items not covered by this batch are unchanged.

## Self-check
lessons.md items re-read: UTC, no look-ahead (strict variant tested), idempotent ingest, empty-is-not-proof, mutation-tested guards, dated amendment (A25). `bash scripts/check.sh`: 284 passed, ruff ok, pairs.yaml reproducible, ingest dry-run 0 calls, CHECK: PASS (after committing the pairs.yaml text change). Committed on `wip/step4-alignment`; not pushed.

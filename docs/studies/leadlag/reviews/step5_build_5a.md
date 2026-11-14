# Step 5, batch 5a build report (alignment cleanup)

## Removed (A22 retired by prereg A26)
- `consts.PM_STAMP_TOLERANCE_S`, `TOLERANCE_FIDELITY`; `PriceBook(tolerance_s=)`, `_tol_series`, `Quotes.used_tolerance`.
- Evaluator `used_tol` plumbing (`_any_tolerance`, fed/cpi/btc/recession), splice `pm_used_tolerance` column, report `pm_used_tolerance_share`.
- Pipeline `strict` / `tolerance_s` args, `panel_*_strict` path, diag `pm_stamp_tolerance_s`; CLI `--strict-asof` and `__strict` summary keys.
- Old tolerance tests replaced (see Tests).

## Panel equality (new panel vs old `_strict` minus `pm_used_tolerance`, pandas `equals`, same column order)
| pair | shape | equals |
|---|---|---|
| fed_decision | 18012 x 27 | True |
| us_cpi_inflation | 18012 x 28 | True |
| bitcoin_monthly_ladder | 18012 x 38 | True |
| us_recession | 18012 x 26 | True |
`pm_used_tolerance` summed to 0 in every old strict panel. Only after this check were the four `_strict` parquet files (derived, in data/clean) and the `__strict` summary keys removed. No file under data/raw touched.

## Minors
Fixed: m2 (moot, flag gone; argparse-rejection test added), m5 (step4.md row 3 reworded; manifest has 15 `empty_confirmed` fid-10: 14 from 2b + 1 from 2026-10-01), unknown pair id -> clear ValueError (`find_pair`), empty-bars guard instead of bare `max()`, `build_pair_inputs` split into helpers (~40 lines), `event_tokens` -> `Event.tokens()`, CLI errors to stderr, `perf_counter`, docstrings, lock file around summary read-modify-write, corrupt-JSON error names the path, `targets.py` `life_pull` replaces the four repeated fid loops.
Skipped: TypedDict for summaries (no consumer yet; step 5b contract adds typing there). m3, m4 are step 6 items.

## Tests (5a example table)
- fid-60 at 14:00:40Z, query 14:00Z -> not used (age 3595 from the earlier point).
- fid-10 at 14:20Z, query 14:30Z -> used, age 600.
- `align run --strict-asof` -> SystemExit 2.
- Plus: never used after the instant at fid 60/10/1 at :00 and :30; ages never negative; no tolerance column; one-panel output; summary lock/merge/corrupt; `Event.tokens`.

## Result
`bash scripts/check.sh`: 280 passed, ruff ok, pairs.yaml reproducible, ingest dry run ok, CHECK: PASS.
Self-check vs lessons: no look-ahead path remains (age >= 0 asserted); no raw deleted; rule examples are tests.

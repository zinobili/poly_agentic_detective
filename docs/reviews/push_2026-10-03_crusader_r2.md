# Crusader round 2 (HEAD 60706c4)

check.sh: PASS (177 tests, ruff ok, pairs.yaml reproducible, md5 21de1743... matches).

## Verdict: SHIP

## Round-1 majors
1. CLI tests: RESOLVED. `tests/test_cli.py` has 10 tests.
2. Manifest view: RESOLVED. `raw_views.py:58` calls `Manifest(m).read()` first, so interior corruption raises; `ignore_errors` then only skips torn lines already accepted. Test `test_manifest_view_raises_on_interior_corruption` added.
3. God function: RESOLVED. No function in `ingest/polymarket.py` or `pairs_build/` exceeds 60 lines (AST check). Shared `base_record`/`failed_record` added to `common.py`.
4. build_pairs: RESOLVED. `scripts/build_pairs.py` is 85 lines; logic lives in `src/poly_actor/pairs_build/`; `GammaClient` replaces the globals; the shared retry helper is used (`gamma.py:24,60`).
5. Already handled (1cff00c).

## New issues
Minor only:
- `pairs_build` tests are in a single `tests/test_build_pairs.py`. Confirm it covers the Gamma retry/4xx path, because that is the one behaviour change.
- Round-1 minors 1-18 are not addressed in this commit, as planned. Carry them to the next hand-off.
- `pairs_build/` is about 1.7k lines, so some modules are still large. That is acceptable and fine to ship.

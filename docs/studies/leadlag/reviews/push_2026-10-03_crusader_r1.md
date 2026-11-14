# Clean Code Crusader: full audit before first push (round 1)

Scope: `src/`, `scripts/`, `tests/`, `.claude/hooks/` (notebooks skipped). `scripts/check.sh`: PASS
(164 tests, ruff clean, pairs.yaml reproducible, dry-run ok). Research correctness is out of scope.

## Verdict: SHIP WITH FIXES
No blockers. No secrets, no `shell=True`, no `eval`/`exec`, no bare `except:`, no `assert` for
runtime checks, no naive datetimes found. Five majors should be fixed or consciously accepted
(and noted in the hand-off) before the repo goes public.

## Scores (1-5)
| Category | Score |
|---|---|
| 1 Design and structure | 3 |
| 2 Readability | 4 |
| 3 Types | 3 |
| 4 Error handling | 4 |
| 5 Tests | 3 |
| 6 Config and constants | 3 |
| 7 Security and safety | 4 |
| 8 Performance | 4 |
| 9 Consistency | 3 |
| 10 Docs and hygiene | 4 |

## Blockers
None.

## Majors
1. **CLI has zero tests.** `src/poly_actor/ingest/cli.py:29-248` (`cmd_run`, `_run`, `cmd_report`,
   exit codes 2 and 3, unknown-pair path, `--asof` parsing, dry-run totals). Only the layers below it
   are tested. Fix: a `tests/test_cli.py` using `main([...])` with `--dry-run`, an unknown pair
   (expect 2), a naive `--asof` (expect 2), a held lock (expect 3), and a `tmp_path` raw dir (make
   RAW_DIR injectable or monkeypatch it).
2. **Silent error skipping in the DuckDB manifest views.** `src/poly_actor/store/raw_views.py:85-89`
   uses `read_json_auto(..., ignore_errors=true)`. `Manifest.read` (`common.py:265-288`) deliberately
   raises on real corruption; the view hides it, so reports can disagree with the ingest logic. Fix:
   drop `ignore_errors` (the sealed torn-line marker is valid JSON), or document and test the
   difference.
3. **God function and nesting in ingestion.** `polymarket.py:212-323` `run_polymarket` is ~110 lines
   and the inner `process` reaches 5 levels of nesting, with the failure-record block duplicated
   (:268-275 and :291-298) and `_fail_rec` (:326) repeating `_call_window`'s record head (:188-195).
   `stocks.py:642-709` `run_stocks` is ~67 lines with the same record pattern (:674-681). Fix: extract
   `_base_record(...)`, `_handle_empty(...)` and `_probe_fid1(...)`; share the record head between
   the two sources in `common.py`.
4. **`scripts/build_pairs.py` is a 1571-line script holding core logic.** `build_btc()` 344 lines,
   `build_cpi()` 211, `get_event()` 151, `build_fed()` 148, `refetch_all()` 102. It also carries
   module-level mutable state (`REFETCH`, `FETCH_SLUGS`, `_call_count`, :84-87, :100) and its own
   retry loop (`_gamma_get`, :99-127) duplicating `common.request_json_with_retry`. Fix (incremental;
   may follow the push): reuse `request_json_with_retry` for Gamma; move the `build_*` functions into
   `src/poly_actor/` with an explicit config dataclass instead of globals; split `build_btc` into
   rung collection / selection / serialisation.
5. **Secrets guard is best-effort but documented as a block.** `.claude/hooks/guard.py:12,30-31` match
   the literal text only, so shell quoting or indirection (a quote inside the name, `$(printf ...)`,
   a Python one-liner building the name) passes, and malformed payloads fail open (:44-49). CLAUDE.md
   says the file is "blocked by hook". (Reasoned from the regexes; I could not run a bypass because
   the hook blocks my own probe commands.) Fix: say in CLAUDE.md and the module docstring that it is a
   convenience guard, keep `.gitignore` plus `permissions.deny` as the real protection, and extend
   deny to `Write(./.env)` and `Read(./.env.*)` (`.claude/settings.json:9-12`).

## Minors (18)
1. `cli.py:124-128` `_write_gap_files` takes `tickers` but never uses it.
2. `cli.py:17` `SCRATCH = DATA_DIR/"scratch"/"step3"` bakes a step number into a path; `cmd_report`
   (:195, :218) writes CSVs although its help says it only reports. Move the path to `config.py`.
3. `cli.py:53` a malformed `--asof` raises a traceback instead of the friendly exit-2 message.
   `--workers 0` and `--pause -1` are not validated.
4. `cli.py:70,104,176` magic numbers (0.5 stock pause, 0.6 s per call estimate, literal `60`) with no
   named constants; `FID_LIFE_FOR_GAPS` (`polymarket.py:62`) duplicates `targets.FID_LIFE`.
5. `cli.py:1` module docstring and the README omit `--only`, `--asof`, `--no-backfill`, `--pause`,
   `--workers`; README has no ingest usage section.
6. Time parsing is implemented three times: `common.to_epoch`, `targets._ep` (`targets.py:373`,
   assumes UTC for naive input, unlike `to_epoch`, which rejects it), and `pairs.load_btc_rungs.ts`
   (`pairs.py:346`). Consolidate in `common`.
7. Missing docstrings or hints on public functions: `common.iso/floor_to/ceil_to/utcnow`,
   `config.ensure_dirs`, `db.connect`, `raw_views.create_raw_views`, `stocks.run_stocks`,
   `stocks.et_midnight_epoch(d)` (untyped), `cli._load_cfg(path=None)`, `write_parquet_once(df, ...)`
   (untyped `df`), `_fail_rec(now, ...)`.
8. Loose dicts for structured records: manifest records, `cfg` (`dict`), `rows: list[list]`. A
   `ManifestRecord` TypedDict would make the status protocol checkable.
9. `ladder: str` in `pairs.py` (`select_ladder`, `is_touched`, `BtcRung.ladder`) and `source: str` in
   `LadderPoint` should be `Literal["up", "dip"]` / `Literal[...]`.
10. `stocks.py:544` `except Exception` is justified (yfinance raises assorted types) and re-raised as
    `IngestError` at :549, but chain the original: `raise IngestError(...) from last`.
11. `common.py:211` imports `requests` inside the function while `polymarket.py` imports it at top
    level; `duckdb` is imported inside functions in `polymarket.py:353,402` and `cli.py` (x3) with no
    circularity reason.
12. `common.Manifest.append` (:290-301) flushes but never `fsync`s; a power loss can drop the last
    record (re-fetch is idempotent, so low impact). `write_parquet_once` leaves a stale `*.tmp` on a
    crash (:342-344); clean it on the next run.
13. `common.ingest_lock` leaves a stale lock after a hard crash (documented). Consider treating a
    dead pid as stale.
14. `stocks.py:700` hashes `raw.to_csv()` (a re-serialisation), not the response bytes, while
    polymarket hashes raw bytes; name the field accordingly or note it.
15. Tests: several multi-concept tests (`tests/test_ingest.py:189-219` covers idempotence, manifest
    schema and incremental extension); `test_modules_import` is near-tautological; no test for the
    `raw_views` manifest views or `Manifest.covered`. Split by concept.
16. `pyproject.toml` marker text says live tests are "deselected by default", but `addopts` has no
    `-m "not live"` and no live test exists, although CLAUDE.md and README document `-m live`. Either
    add the deselect or drop the claim.
17. `scripts/build_pairs.py:602,1525-1537` hard-codes `TODAY`, and does a `str.replace` of
    `status: draft` into `status: approved  # user approved ...` in the generated YAML. Make approval
    an explicit constant and drop the replace hack.
18. `config/pairs.yaml` is 404 KB of generated output and the rebuild needs the git-ignored
    `data/scratch/step2` cache, so CI cannot verify reproducibility (`check.sh` skips it); CI runs
    pytest and ruff only. Note this in the README.

## What is good
- Pure/IO split is clean in ingestion: `parse_prices_history`, `parse_bars`, `plan_windows`,
  `subtract_intervals`, `tile` and `build_token_specs` are pure and well tested; network, clock and
  sleep are injected (`get`, `fetch`, `now`, `sleep`), so tests need no sleeps or network.
- `pairs.py` is a model module: typed, frozen dataclasses, docstrings that cite the amendment and the
  time-t rule, explicit `ValueError`s on bad input.
- Raw immutability is enforced in code (`write_parquet_once`, append-only manifest with torn-line
  sealing, exclusive lock) and each guard has a test.
- Retries are bounded and honour `Retry-After`; the no-network conftest guard blocks sockets and DNS.
- ruff config includes `DTZ`; the UTC rule is respected throughout; zoneinfo is used for DST.
- `scripts/check.sh` and `tests/test_hooks.py` make the standards checkable.

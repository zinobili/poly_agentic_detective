# Crusader review: push 2026-10-08 (step 6 analysis + dashboard), r1

**Verdict: SHIP WITH FIXES** (no blockers; 2 majors are cheap to fix, optional if time-boxed)

Checks: ruff clean. pytest ran green as far as observed (first ~35% before my timeout; the full suite exceeds 2 min). The `scripts/check.sh` output was not captured (timeout), so re-run it before pushing.

## Scores
Design 4, Readability 4, Types 3, Error handling 4, Tests 4, Config 4, Security 5, Performance 4, Consistency 3, Docs 4.

## Major
1. **Loose `dict` as the core result type.** `analysis/results.py` (`_row` L45, `fed_result`/`btc_result`/`cpi_result` take `bh: dict, studies: dict, extra: dict`, return `dict`). `dashboard/contract.py` (about 15 `raw: Any` parsers, L163-L395) re-parses the same shape, so the producer and consumer contracts are held together only by string keys. Fix: TypedDicts for the results document (or build the doc from the contract dataclasses and serialise them), plus a round-trip test (`parse_results(jsonable(result))`) so a key rename fails a test.
2. **Long functions.** `results.py` `fed_result` (64 lines), `btc_result` (78), `cpi_result` (79) and `dashboard/text.py` `glossary` (72) are over the ~60-line guide. They also repeat the assembly skeleton (verdict, confidence, checklist, notes). Fix: extract a shared `_base_doc(core, facts, ...)` and keep only the pair-specific parts in each function.

## Minor (7)
1. `analysis/run.py:338,351` uses `print` for CLI output while `logging` is configured in `main`. Printing a results summary is acceptable for a CLI, but use one idiom, or add a comment that stdout is deliberate.
2. `run.py:cmd_run`, `cmd_counts` have no docstring or type of `args` beyond `Namespace`; `cmd_run` does not log per-pair timing.
3. `run.py cmd_run`: `f.result()` in the pool re-raises without naming the pair. Wrap it, e.g. `raise RuntimeError(f"pair {p} failed") from exc`.
4. `results.py:jsonable` ends with `return obj` for unknown types. That silently passes objects that `json.dumps` will reject with a vague error; raise `TypeError(type(obj))` instead.
5. `results.py:write_json` uses a fixed `.json.tmp` name. Concurrent writers of the same pair could collide (single-writer today). Use `tempfile.NamedTemporaryFile(dir=...)`.
6. `dashboard/contract.py:137` `params: dict[str, Any]` and `dashboard/text.py:108,116` `params_of`/`glossary` use `Any`. A `Params` TypedDict would document the keys.
7. `analysis/inputs.py:pair_inputs` opens a raw DuckDB connection per call. It is correctly closed, but it is repeated per pair; consider passing a shared connection.

## Good
- Atomic JSON writes with `allow_nan=False` and NaN-to-None. `assert` is not used for validation anywhere. No bare or broad `except`. No `shell=True`, `eval` or `exec`.
- Seeds are named constants (`PLACEBO_SEED`, `BAND_DRAWS`). Random draws are deterministic.
- Pure compute modules (`models`, `events`, `cpi`, `placebo`, `verdict`) are separated from I/O (`inputs`, `run`). Raw data is read-only. Missing panel raises with an actionable message.
- Synthetic test fixtures reproduce real sub-hour timing, per the lessons. Tests are offline.
- Wording and chart text were split out of `text.py` (564-line change) into `wording.py` and `chart_text.py`.

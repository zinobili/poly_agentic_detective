# Crusader review: commit a0ddd67 (step 8 election pipeline)

**Verdict: SHIP WITH FIXES** (no blockers; 2 majors, all small)

Scores: design 3.5, readability 4, types 3, errors 4, tests 4, config 3.5, security 5, perf 4, consistency 3, docs 4.

## Major
1. **Duplicated retry/fetch logic** `election/ingest.py:97-128` copies `ingest/stocks.py:89-116` (`fetch_bars`) and `run_yf` (`:163-220`) mirrors `stocks.run_stocks` (failure record, manifest, write_parquet_once). Two retry policies (4 vs 3 attempts) already differ. Fix: generalise `stocks.fetch_bars` with `interval`/`auto_adjust` params (defaults = current behaviour) and call it from the election `fetch`; keep one backoff loop. Run_yf may stay if it is documented as the multi-interval variant.
2. **Validation via magic numbers + hard-coded signal list.** `config.py:108-110` hard-codes 29/58; `coverage.py:129` re-lists `("p_sen","p_house","p_sweep","p_rr")` instead of `SIGNALS`; `coverage.py:83` and `panel.py:180,197` use bare `3600/600/300`. Fix: named constants (`BAR_5M_S = 300`, `FID_STEP_S = {60: 3600, 10: 600}`), `UNIVERSE_PER_BASKET` read from yaml `study` or a constant, use `SIGNALS`.

## Minor (10)
- `panel.py:28` `SESSION_FIELDS` unused (dead).
- `coverage.py:135` stray `# noqa: E501` on a closing brace.
- `cli.py:17,29` `args`/`cfg` untyped; `config.py:57,71` `d: dict`, `raw: dict`; `coverage.py` returns bare `dict`; `ingest.py:136` `failures: list[dict]`; `now: Callable[[], Any]`. Use `argparse.Namespace`, TypedDicts or `Mapping[str, Any]`.
- `ingest.py:111,125` retry counts (4, 2.0 s) are inline; name `YF_ATTEMPTS`, `YF_BACKOFF_S`.
- `ingest.py:122,199` `except Exception` is justified in a comment, but add `# noqa: BLE001` consistently with stocks.py.
- `panel.py:254` lazy import of `coverage` has no cycle reason; import at top.
- `panel.py:233` `idxmax` trick is obscure; use `np.flatnonzero(n_states > 0)[:1]`.
- `panel.py:281,283` clean outputs written non-atomically (plain `to_parquet`/`write_text`); use temp file + `os.replace`.
- `config.py:70` `ElectionConfig` has no class/public docstring; `load_config` and `read_*` lack unit/timezone notes on some returns.
- `cli.py:55` `cmd_panel` relies on dict keys `cov['tables']`; fine but untyped.

## Good
Pure spec/plan functions separate from thin network wrapper; injected `sleep`/`fetch`/`now` make tests offline and deterministic; idempotence and zero-call rerun tested; empty-frame failure path and retry/backoff tested; DST and early-close tests; atomic raw writes reuse `write_parquet_once`; reuses `polymarket.run_polymarket`, `Manifest`, `ingest_lock`; no shell/eval/secrets (token IDs are public market ids).

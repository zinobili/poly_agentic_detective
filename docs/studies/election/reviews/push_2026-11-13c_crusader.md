# Crusader review: push 2026-11-13c (step 9, commit e8a2d64)

Scope: `git diff origin/claude/fervent-mayer-k4klat..e8a2d64`, read from the commit only. Tests and check.sh were not run (the caller asked me not to). Engineering standards only.

**Verdict: SHIP WITH FIXES** (0 blockers, 1 major, 9 minors)

| Category | Score |
|---|---|
| Design and structure | 4 |
| Readability | 4 |
| Types | 3 |
| Error handling | 4 |
| Tests | 4 |
| Config and constants | 3 |
| Security and safety | 5 |
| Performance | 4 |
| Consistency | 4 |
| Docs and hygiene | 4 |

## Blockers
None.

## Major
1. **`analysis.py:323` (and `cli.py` cmd_analyse): wall-clock `generated_at` in the tracked bundle.**
   - `analyse(..., today=None)` stamps `datetime.now(UTC).date()` into `reports/election/results.json:4600`. `cmd_analyse` never passes `today`.
   - Every re-run on another day therefore dirties a tracked file, even when all numbers are identical. The byte-identical test only passes because it injects `today`.
   - Fix: drop the field, or derive it from the data. For example, set `generated_at` to `data_last_session` (already in meta), or add `--date` to the CLI and require it. Prefer deleting the field, since the commit hash already provides provenance.

## Bundle contents (`reports/election/`)
- No secrets, no absolute paths, no raw per-ticker prices or odds. I grepped for paths, key, token and secret, and found none.
- Only derived series are tracked:
  - basket cumulative log returns, plus RSP;
  - daily odds for the 4 signals;
  - the per-stock beta and AR cross-section (statistics, not prices);
  - volatility-ratio paths;
  - a one-night NQ/ES/RTY percent-change path.
- Size is about 5k lines of JSON plus roughly 3.5k lines of CSV. That is acceptable.
- `.gitignore` carries the note "generated outputs embed third-party data". The NQ/ES/RTY night path and the VIX ratios are derived from Yahoo data. Confirm this is acceptable for a tracked bundle (minor, policy).

## Minor
1. `explore.py:152` `iso()` and `stats.py:345` `finite()` are dead code (no callers in src or tests). Delete them.
2. The `lin_test` pattern (build the weight vector, call `ols` with HAC, call `lin_test`) is repeated in `stats.beta_fit`, `explore.e1_rolling:40-43`, `intraday._t_slope:55-58` and `intraday.h3:154-159`. Extract one `stats.coef_test(X, y, idx, hac_lag)` helper.
3. `explore.e1_rolling:38-39` builds the same design twice and fits an extra unused `beta_fit` (`f`) just to get `before_b10_pct`. Reuse `fit`.
4. Magic numbers sit in logic: `1.645` (explore.py:34, use the `CI_LEVEL` z-score), `252.0` (explore.py:82, name `TRADING_DAYS_PER_YEAR`), `len(yy) < 10` (intraday.py:53), `n >= 5` (explore.py:110) and `LAST = 30` / `ROLL = 60` (unitless, add a "rows" comment).
5. The pre-registered dates are duplicated: `analysis.py:39-43` (`H2_EST_END`, `EVENT_DAY`, `ELECTION_DAY`, `W3_END`, `E5_START`), `explore.py:119` (`start="2026-11-04"`) and `explore.ELECTIONS`. Put them in `ElectionConfig` or one constants block, so E5 cannot drift from `E5_START`.
6. Functions over about 60 lines: `analyse` (about 70), `run_h1` (about 70) and `checklist` (about 65, mostly a literal). Split `analyse` into `build_results` (pure) and `build_series`. `_t_slope` returns an anonymous 5-tuple, so use a small `NamedTuple` or dataclass. Most results are bare `dict` (`-> dict`). Consider a TypedDict for the `h1_row` shape.
7. `bundle.checklist` uses `tick = lambda ...  # noqa: E731`. Use a small `def`. Single-letter capitals (`D`, `S`, `B`, `Z`, `_Z`) are fine for matrix code but should be documented in the module docstring.
8. `bundle.publish` does `rmtree` then `copytree`, which is not atomic. A failure mid-copy leaves `reports/election` empty (git can restore it). Copy to a sibling temp dir and then rename. `write()` writes JSON and CSV directly (same minor point).
9. Test gaps:
   - No direct tests for `bundle.clean` (NaN/inf to None), `publish` raising `FileNotFoundError`, `explore.e2_vol` with a missing election day, or `e3` with fewer than 5 rows (n<5 path).
   - `test_planted_h4_and_h3_and_h5` asserts `wald p > 0.0`, which is nearly tautological (`analysis` test:67). Assert something that fails when the guard breaks.
   - `cli.cmd_analyse` and `cmd_publish` are untested.
   - `cli.py` also leaves `args` untyped and imports lazily, which matches the existing pattern.

## What is good
- `stats.py`, `intraday.py` and `explore.py` are pure (no I/O), with the I/O confined to `analysis.load_panels` and `bundle.write/publish`.
- The module split is clear. `poly_actor.analysis.models` and `placebo` are reused (`ols`, `lin_test`, `bh`, `spearman`, `admissible_shifts`) rather than reimplemented.
- Seeds are fixed, with one RNG stream per test. The byte-identical double run is tested. Output is deterministic (sorted keys, fixed float format, LF line endings).
- The look-ahead guard tests (walk-forward, H2 estimation window, pre-sample) are strong. The resolved-market tests cover boundaries.
- Verdict logic is mechanical and table-tested. `ResolvingBook` is small and leaves `PriceBook` unmodified.
- NaN handling in the JSON is explicit, with no silent fill. Missing days are dropped and recorded.

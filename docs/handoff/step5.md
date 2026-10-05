# Step 5 hand-off (dashboard)

Branch `step5-dashboard`. Design reference: `docs/design/dashboard_ux.md` (rules) + `docs/design/dashboard_mockup.html` (layout, made-up data). Read both before building.

## Decisions (2026-10-05)
- **Step 5 comes before the analysis (step 6).** The dashboard is built against a **results contract** that step 6 will fill. No analysis numbers exist yet, so they are **never invented**: every analysis slot shows an honest "Not run yet" state. Only real aligned data (chart 3, coverage, data ages) is shown as real.
- **Stack:** Streamlit + Plotly. Add `streamlit` as an optional extra `[dashboard]` in pyproject (plus to `[dev]` so tests can import it). Launch: `streamlit run src/poly_actor/dashboard/app.py`.
- **Reads only `data/clean/`** (panels + optional `data/clean/results/<pair>.json`). No network, no writes.
- **A22 retired (prereg A26):** remove the tolerance code first (batch 5a).

## Batch 5a — alignment cleanup (do first, own commit)
1. Remove `PM_STAMP_TOLERANCE_S`, the `pm_used_tolerance` column, `--strict-asof`, and the `_strict` panels/summary keys. The as-of is strictly at-or-before at every fidelity.
2. Fix the step-4 minors listed below (validator m2 becomes moot with the flag gone; m5 doc reconcile; crusader minors in `align/` and `ingest/targets.py`).
3. Rebuild panels. **Each new panel must equal the old `_strict` panel minus the `pm_used_tolerance` column** (compare with pandas `equals` before deleting the old files; report it).

| Situation | Expected |
|---|---|
| fid-60 point at 14:00:40Z, query 14:00:00Z | NOT used; take the latest point ≤ 14:00:00Z |
| fid-10 point at 14:20:00Z, query 14:30:00Z | used, `pm_obs_age_s` = 600 |
| `python -m poly_actor.align run --strict-asof` | argparse error (flag removed) |

## Batch 5b — dashboard
**Module layout:** `dashboard/load.py` (read panels + results, pure), `dashboard/text.py` (all reader-facing wording as pure functions of results), `dashboard/charts.py` (Plotly figure builders, pure), `dashboard/app.py` (Streamlit layout only, thin). Tests cover `load`, `text`, `charts`. `app.py` gets a smoke test via `streamlit.testing.v1.AppTest` with a tiny fixture panel in `tests/fixtures/`.

**Results contract** (`dashboard/contract.py`, a dataclass/TypedDict + JSON loader; step 6 writes it). Per pair: `pair_id`, `xcorr` (lags h, r values, noise band), `event_study` (event times, mean path, CI), `checklist` rows (`name`, `status` in Passed/Failed/Weak/Not needed/Not run, `plain`, `technical`), `verdict` (one of the 4 labels or null), `confidence` (level + reason or null), `n_events`. Missing file or missing field → that slot is "Not run yet".

**Page** follows `dashboard_ux.md` top to bottom: banner, headline, scorecard, what counts, pair evidence (verdict panel, ticker chips, chart 1, chart 2, chart 3 last), glossary. Sticky pair tabs as described there (session_state; no scroll reset).

**Rules as examples** (each becomes a test in `text.py`/`charts.py`):

| Input | Expected |
|---|---|
| no results file for any pair | banner "Analysis not run yet: only the raw data below is real"; headline "We haven't run the tests yet"; every card badge "Not run yet", confidence meter empty with reason "Tests not run" |
| xcorr peak +2 h, lag +2 and +3 both outside band, pair Fed/TLT | title "Fed odds tend to move about 2 hours before TLT (long-term bonds)" |
| xcorr peak at 0 | "... and SPY (S&P 500) move in the same hour, so neither gets a head start" |
| one bar outside band, both neighbours inside | "No clear timing link ...: only isolated bars poke out, which is likely luck" |
| all bars inside band | "No clear timing link between ... and ...: every bar sits in the noise zone"; so-what contains "That's a valid result, not a failure." |
| checklist row `Granger causality, BH-adjusted p = 0.012`, status Passed | plain line "✓ Passed: Odds help predict prices beyond their own past"; technical text underneath in small mono |
| pair id `fed_decision` | reader sees "Fed rate decision"; the strings `fed_decision`, `pairs.yaml`, `python -m`, "step 6" never appear in rendered text (test scans `AppTest` output) |
| chart 3 for Fed | two stacked panels, shared x axis (Polymarket signal on top, stock price index below); **never** a secondary y-axis (test: figure has no `yaxis2` with `overlaying`) |
| chart 3 with a gap > 6 h in the panel (weekend) | line breaks (NaN inserted), no line drawn across the gap |
| timestamps | axis shows UTC and says so ("Time (UTC)") |

Ticker plain names come from one mapping in `text.py` (SPY S&P 500, TLT long-term bonds, XLF banks, XLU utilities (control), etc.: read the tickers from the panels and `config/pairs.yaml`).

## Checklist (builder self-checks, validator re-checks)
- [ ] 5a: tolerance code gone; panels equal old strict panels; check.sh PASS
- [ ] Every example row above is a passing test
- [ ] No invented analysis numbers anywhere; "Not run yet" states render
- [ ] Chart 3 values match the panel at 3 sampled timestamps (test + validator spot-check against DuckDB/parquet)
- [ ] App launches (`AppTest` smoke + a manual `streamlit run` headless start reported)
- [ ] Layout order and wording follow `dashboard_ux.md`; no jargon in reader text
- [ ] New code meets the crusader standard (`.claude/agents/clean-code-crusader.md`)
- [ ] Build report ≤250 words; full report `docs/reviews/step5_build_r1.md`

## Minors carried over from step 4 validator r2 (docs/reviews/step4_r2.md)
- **m1 — A22 tolerance never fires on real data.** Every fid-60 point has a fid-1/fid-10 twin at the same stamp; dedup keeps the finer one, so strict == tolerant byte for byte and `pm_used_tolerance` is 0 everywhere. Not look-ahead (stricter than approved). **RESOLVED 2026-10-05: user retired A22 (prereg A26).** Step 5 task: remove `PM_STAMP_TOLERANCE_S`, the `pm_used_tolerance` column, the `--strict-asof` flag and the `_strict` panels. Replace the tolerance tests with "any point stamped after the instant is never used, at any fidelity" (fid-60 at 14:00:40Z, query 14:00Z → NOT used). The panels must come out byte-identical to the current strict panels.
- **m2:** no test that the CLI passes `--strict-asof` through (`align/cli.py:41`); that mutant survived.
- **m3:** lead-lag rows are ~10 min stale (median ~594s). Step 6 must state it and read lag-0/lag-1 with that in mind.
- **m4:** quotes up to 3h old still enter `both_trading` (97 BTC rows > 1500s). Consider a max-age cut-off in step 6 (pre-register it before looking at results).
- **m5:** the hand-off wording on empty fid-10 responses doesn't match the code; empty count is 14 in the build report vs 15 in the manifest. Reconcile the doc.

## Minors from crusader push review 2026-10-05 (docs/reviews/push_2026-10-05_crusader_r1.md)
Fix where step 5 touches the code: `pipeline.py` bare StopIteration on unknown pair id, unguarded `max()` on empty `stamped`, `build_pair_inputs` ~65 lines, `event_tokens` → `Event.tokens()`; `align/cli.py` errors to stdout (use stderr/logging), `time.time()` → `perf_counter`, missing docstrings/TypedDict, unlocked summary read-modify-write, corrupt-JSON error without path; `targets.py` repeated `(FID_LIFE, FID_DENSE)` loop in four planners.

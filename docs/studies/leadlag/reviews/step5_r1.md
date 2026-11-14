# Step 5 validation, round 1

## Verdict
PASS with 1 major (results-contract shape for step 6) and 7 minors. No blockers. Only the major needs a fix (or an explicit user decision) before step 6 writes results.

## Checked (evidence)
- `scripts/check.sh`: 331 passed, ruff ok, pairs reproducible, dry run ok.
- **5a as-of guard.** Mutant `np.searchsorted(t, instants + 60, side="right")` in `align/prices.py` fails `test_fid60_point_40s_after_the_hour_is_not_used`. Restored. In `prices.py` the only lookup is `side="right"` on instants, so a stamp after the instant can never be selected. No tolerance code remains. Real panels: 4 files, no `pm_used_tolerance` column, min of every `*age_s` column is 0.0 (never negative). The old `_strict` panels were deleted by the builder, so I could not re-diff them. I rely on the build report's `equals` table and the identical shapes (18012 rows). Not independently re-verified.
- **Chart 3 vs parquet.** I called `raw_data_figure` on the real panels, at 3 timestamps each, for BTC (COIN and BTC-USD), Fed/TLT and recession/SPY. Plotted signal equals `scale(signal_level)` exactly (for example Fed 2025-09-30 18:30 gives -0.2249 pts from -22.49 bp; BTC 2025-01-30 16:30 gives $97.2k from 11.4848). Final stock index levels match an independent cumsum. One sampled BTC timestamp had a NaN signal, correctly absent from the line.
- **BTC unit.** Over all rows, exp(signal_level)/btc_spot has median 0.996, min 0.83, max 1.13. corr(signal_level, log(btc_spot)) = 0.97. So the signal is the log of a USD price and $k is correct. The inference is confirmed. The prereg has no explicit sentence on it, but A20 describes log-strike interpolation, which is consistent.
- **Launch.** AppTest on the real full panels, with no results and with Fed results: no exception, and all 4 cards open without exception. Headless `streamlit run` returned 200 and health "ok".
- **No invented numbers / no leakage.** I scanned the AppTest proto text (both states) for all 4 pair ids, `pairs.yaml`, `python -m`, "step", `signal_level`, `ret_`, `pm_obs`, `.json`, `nan`, `parquet`. There were zero hits. Every analysis slot reads "Not run yet", and the meter reason reads "Tests not run".
- **Mutation tests on dashboard guards** (each restored afterwards):

| Mutant | Result |
|---|---|
| gap break removed | killed |
| axis title "Time (UTC)" changed | killed |
| "That's a valid result" removed | killed |
| `_naive_utc` shifted to New York time | killed |
| "Preview:" prefix removed | killed |
| BTC scale removed | killed |
| Fed scale removed | killed |
| neighbour check changed | killed |
| `is_session_bar` filter removed | survives, but it is an equivalent mutant (ret is already NaN off session) |

- Example tables: every row has a matching test (read `test_dashboard_*.py`). Chart 3 has no secondary axis and a shared x.

## Issues
**M1 (major) `dashboard/contract.py:48,82`: one `xcorr` and one `event_study` per pair, each with a single `ticker`.** The pairs have 2 to 4 tickers, including the XLU control, and the UX rules say a link in "one hand-picked stock" does not count and the control showing no link is good news. Step 6 would have to pick one ticker, which cherry-picks, or drop results. The loader also cannot carry the control result. Fix: make `xcorr` and `event_study` a ticker-keyed map or list (one per ticker), have the dashboard render the selected ticker, and use a "Not run" state per ticker.

Minors:
- m1 `contract.py:_floats`: NaN or inf in `r`, `mean`, `ci_*` is accepted (`json.loads` allows NaN). `classify_xcorr` treats NaN as "inside the band", which silently reads as "no link". Reject non-finite values (only `band` is checked).
- m2 `text.py:headline`: if every pair has verdict "Too early to tell", it says "So far, Polymarket odds have not moved ahead of stocks in any pair we tested". That overclaims. It should say "too early to tell".
- m3 `text.py` GLOSSARY and `xcorr_expert`: hard-coded analysis parameters ("lags -12 to +12 h", "beyond 2 standard deviations", "0.1 to 0.2 is already notable") are not in the contract and not confirmed by prereg. Step 6 must match them, or they should come from the contract.
- m4 `app.py:229`: `components.html` is deprecated ("removed after 2026-06-01", already past) and logs a warning on every card click. `pyproject` allows `streamlit>=1.40` with no upper bound, so a later release could break scroll-on-click. Pin an upper bound or use `st.iframe`.
- m5 `tests/test_dashboard_app.py:15`: FORBIDDEN omits `bitcoin_monthly_ladder` and `us_cpi_inflation`. I verified they do not leak, but the test would not catch it.
- m6 The Streamlit server binds all interfaces by default (the log shows Network and External URLs). Add `.streamlit/config.toml` with `server.address = "localhost"`.
- m7 `charts.py:stock_index_series`: BTC-USD `ret_` exists only on session bars, so BTC-USD's own line has weekend and overnight breaks although it trades 24/7. This is display only, but the "How to read" text blames "nights and weekends for stocks".

## Deviations vs dashboard_ux.md (acceptable)
- The tab bar is a sticky radio that starts at "Pair evidence", not after the scorecard scrolls off. It has no sub-480px name-only mode. It is acceptable for now, and the build report says a manual browser check is needed. I did not browser-test it.
- Fed "-0.18 pts" formatting appears only as the axis unit, which is fine.
- The banner differs from the mockup's "Made-up numbers", as intended.
- The checklist `name` and `plain` split is a sensible contract choice.

## Not checked
- Browser rendering and the sticky and scroll behaviour.
- Charts 1 and 2 with realistic results (only the AppTest Fed fixture and unit builders).
- Old strict panel equality (the files are gone).
- A crusader-standard review (a separate step before push).

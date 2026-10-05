# Step 5, batch 5b build report (round 1)

Branch `step5-dashboard`. Batch 5a was already committed (77cbbb8).

## Files
- `src/poly_actor/dashboard/contract.py`: results contract (dataclasses, tolerant JSON loader).
- `src/poly_actor/dashboard/load.py`: panels, pair list (from `config/pairs.yaml`), coverage facts.
- `src/poly_actor/dashboard/text.py`: all reader wording, pure functions.
- `src/poly_actor/dashboard/charts.py`: Plotly builders (chart 1, 2, 3), gap breaking.
- `src/poly_actor/dashboard/app.py`: Streamlit layout only.
- `tests/test_dashboard_{text,load,charts,app}.py`, `tests/dashboard_helpers.py`, fixture `tests/fixtures/dashboard_clean/panel_fed_decision.parquet` (one real week, 174 rows).
- `pyproject.toml`: `streamlit>=1.40` in `[dashboard]` and `[dev]`; installed in `.venv` (1.65.0).

## Run
`.venv/Scripts/streamlit.exe run src/poly_actor/dashboard/app.py`. Data folder defaults to `data/clean/`; override with env `POLY_ACTOR_CLEAN_DIR` (used by tests).

## Results contract
`data/clean/results/<pair_id>.json`: `pair_id`, `n_events`, `xcorr{ticker,lags,r,band}`, `event_study{ticker,hours,mean,ci_low,ci_high,event_times}`, `checklist[{name,status,plain,technical}]`, `verdict`, `confidence{level,reason}`. Every slot optional; a missing file, bad slot, wrong pair id or corrupt JSON becomes "Not run yet" (corrupt/mismatch is logged with the path). Full docs in the `contract.py` docstring.

## Tests
51 new (331 total). Every row of the 5b example table has a test: not-run banner/headline/badges/meter, lead/same-hour/lone-bar/all-inside titles and so-what, Granger line, forbidden-string scan on AppTest output (also with results), chart 3 stacked with no overlaying y axis, gap > 6 h breaks, "Time (UTC)". Chart 3 values are checked against the panel at 3 timestamps. Mutation checks: gap threshold and same-sign neighbour guard each fail tests when removed.

## Results
`bash scripts/check.sh`: PASS (331 passed, ruff ok, pairs reproducible, dry run ok). Headless `streamlit run ... --server.headless true`: server up, root 200, health "ok", then stopped.

## Decisions and deviations
- Checklist row: `name` = row title, `plain` = reader text, `technical` = test name and p-value (the brief's example string is the technical text). `plain` falls back to `name`.
- The xcorr slot needs a `ticker` (title names it); without it the slot is "Not run".
- Event-study mean/CI are in percent (contract choice).
- Tab bar is a sticky `st.radio` placed at the start of "Pair evidence" (CSS sticky); it sticks once reached, not from the top of the page. The scroll-to-evidence on a card click uses a tiny JS snippet and is not covered by AppTest.
- Chart 3 signal units per pair: Fed bp/100 (pts), recession x100 (%), Bitcoin exp(log level)/1000 ($k), CPI as is. Stock index = 100 * exp(cumsum(ret + overnight gap)) on session bars. Bitcoin log-level reading is inferred from value range (11.0-11.7); the validator should confirm.
- Panel/ticker names (`IWM-SPY`, derived spread) have no chart-3 series; chips still show it.
- Not done (outside 5b): step 4/crusader minors were handled in 5a.

## Self-check vs checklist and lessons
No invented numbers (all analysis slots are "Not run yet"; real data facts come from the panel). No network/writes. UTC axis labelled. No look-ahead involved (display only). Layout order follows dashboard_ux.md: banner, headline, scorecard, what counts, evidence (verdict, chips, chart 1, 2, 3), glossary.

## Known limits
- Charts 1 and 2 are untested against real results (none exist).
- Sticky tab behaviour and scroll-on-click need a manual browser check.

# Step 4 hand-off: alignment

**Status:** not started. Build an hourly UTC panel per pair from the raw views (`src/poly_actor/store/raw_views.py`).

## Requirements
These come from `docs/milestone1_plan.md` ("Requirements learned in step 1") and `docs/handoff/lessons.md`.

### Polymarket side
- **Resample** across `fid=60`, `fid=10` and `fid=1`, taking the last observation at or before each hour end. Never use a later observation.
- **Prices above 1:** clip the 209 rows with p > 1 (max 1.0055) to [0, 1] and flag them.
- **BTC ladder:** for each hour, run `load_btc_rungs(month)` and then `select_ladder`, then compute the monotone crossing.
  - Log the dropped hours, including each whole-month rung's first 24h.
  - Log the PAV pooling rate.
- **CPI:** log how often the derived-bucket `max(0, …)` clip binds.

### Stock side
- **Re-stamp** each bar to its end time using XNYS, including the early-close rule.
- **Drop or flag** short days, per `data/scratch/step3/stock_gaps.csv`.
- **Known Yahoo gap:** 2026-01-30 11:30 ET to 2026-02-02 13:30 ET, for all equities.

### Joining the two
- **Roll and splice** per `config/pairs.yaml`: roll 1h after each official event time, splice on changes, and set the `roll_hour` flag.
- **Trading hours only:** the lead-lag panel keeps only hours when both sides trade. Overnight and weekend Polymarket moves go in a separate column, set against the opening gap.

## Minors carried over from step 3 (if any)
None yet.

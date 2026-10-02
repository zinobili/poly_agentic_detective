# Step 3: price ingestion (Polymarket CLOB + yfinance)

Code: `src/poly_actor/ingest/` (`common.py`, `polymarket.py`, `stocks.py`, `targets.py`, `cli.py`),
`src/poly_actor/store/raw_views.py`. Tests: `tests/test_ingest.py`, `tests/test_ingest_fixes.py`
(offline, saved fixtures in `tests/fixtures/`).

## How to run

```
.venv/Scripts/python.exe -m poly_actor.ingest run --dry-run     # plan only, no network, no writes
.venv/Scripts/python.exe -m poly_actor.ingest run               # life pass, fid-10 gap backfill, stocks
.venv/Scripts/python.exe -m poly_actor.ingest run --asof 2026-10-01T14:00:00Z   # pinned "now"
.venv/Scripts/python.exe -m poly_actor.ingest run --only polymarket|stocks --pairs a,b
.venv/Scripts/python.exe -m poly_actor.ingest run --no-backfill --min-gap-hours 6
.venv/Scripts/python.exe -m poly_actor.ingest report            # counts, gap inventory, short stock days
```

Idempotent and incremental: a re-run with the same `--asof` makes 0 calls and writes nothing new.
A lock file `data/raw/.ingest.lock` (O_EXCL) stops two concurrent runs; it is removed on exit. After a
hard crash delete it by hand. Failed windows are logged and retried next run. A torn final manifest
line is skipped with a warning.

Order of a run: (1) Polymarket life pass (fid 60 whole life, fid 1 around FOMC/CPI events),
(2) fid-10 backfill of interior gaps, (3) stocks, (4) write `data/scratch/step3/gap_inventory.csv` and
`stock_gaps.csv`.

## Layout (raw is immutable; files are only added)

```
data/raw/polymarket/<token_id>/fid=60|10|1/<start_ts>_<end_ts>.parquet   columns t, ts (UTC), p
data/raw/polymarket/_manifest.jsonl
data/raw/stocks/<ticker>/<start_ts>_<end_ts>.parquet     ts = bar START (UTC), OHLCV, ohlc_all_nan
data/raw/stocks/_manifest.jsonl
data/scratch/step3/{gap_inventory.csv,stock_gaps.csv}    derived summaries, regenerated
```

DuckDB views (`create_raw_views`): `raw_polymarket_prices(token_id, fidelity, t, ts, p)`,
`raw_stock_bars`, `raw_manifest_*`. Step 4 must resample across fid=60, fid=10 and fid=1 (the views
keep all three; they de-duplicate only within a fidelity).

## Manifest statuses (polymarket)

| status | meaning | covered? |
|---|---|---|
| `ok` | data stored, or nothing expected (window outside the token's life) | yes |
| `empty` | HTTP 200, no points, window overlaps the token's [created, closed) life | no, retried |
| `empty_confirmed` | `empty`, window ended more than 48h ago, and the fid-1 probe was also empty (`probe_rows` is 0) or the probe's data was stored under fid=1 | yes |
| `failed` | exhausted retries or bad body | no, retried |

An `empty` window ending within 48h of now is just retried. Older ones are probed once at fidelity 1.
Legacy `ok` records with `n_rows == 0` overlapping a token's life are treated as not covered and were
re-fetched (the first version marked empty 200s covered forever).

## Gap backfill (fidelity 10)

The server's fid-60 history is lossy: hourly points go missing for tens of hours (mostly 2026-03/04).
Gaps are found on the base series (fid 60 + fid 1, never fid 10, so the list is stable across runs):
consecutive points more than 3h apart, interior to the token's data. Each gap is fetched at fid 10 into
`fid=10/`. Fid 10 is itself sparse (example: token 57612516... from 2026-04-05 04:00Z, 36h: fid 1 returns
2,159 points, fid 10 returns 133) but its largest spacing was under 1h, which is enough to resample to
hourly. Fid 1 would be about 10x the volume.

## Known source gaps and quirks

- **Zero-volume BTC rungs** (no trades, flat quotes; treat as no signal):
  `will-bitcoin-reach-72pt5k-in-august-2026-from-august-20` and
  `will-bitcoin-reach-77pt5k-in-september-2026`.
- **Polymarket 2025-10-29 09:00 to 14:00 UTC**: upstream outage across all tokens. 10 gaps stay
  `partial` (largest remaining 3.2 to 3.5h) and 1 `unfilled` (3.4h). Step 4 should not forward-fill across
  more than a few hours.
- **Prices above 1**: 209 Polymarket rows have p > 1 (max 1.0055). Step 4 must clip to [0, 1] or flag.
- **Live point trap**: for active markets the API appends the current price after `endTs`; parsing
  clips to the half-open window. The last window ends at `floor(asof - 10min, hour)` for late-published points.
- **yfinance gaps**: all equities are missing 2026-01-30 11:30 ET through 2026-02-02 13:30 ET upstream
  (SPY: 1 bar on 01-30, 3 on 02-02). BTC-USD is short on 2025-10-28 (13 of 24), 2025-11-29 (5 of 24),
  plus single missing hours on 2025-01-02, 2025-11-28 and 2026-05-08. Early closes have 3 bars, not 4
  (yfinance omits the 12:30 bar). TLT 2026-02-02 09:30 is an all-NaN row, kept and flagged. Short days
  are listed in `data/scratch/step3/stock_gaps.csv` and never fail a run.
- **Stock start moves forward**: 1h bars reach back at most 730 days (we use 729), so the start is
  2024-10-02 today and rolls forward each day. Already-ingested raw files are kept. Data is ingested
  up to ET midnight of yesterday (a 1-day lag so Yahoo revisions land first).
- Stock bars are unadjusted (`auto_adjust=False`) and stamped by bar START; step 4 re-stamps to the end.

## Gap inventory summary (run of 2026-10-01)

1,893 interior gaps over 110 tokens (12,303 gap-hours; median 5h, max 36h; 691 gaps over 6h). The
fid-10 backfill took 1,894 calls and stored 47,567 points (109 tokens).
After the backfill: 1,882 filled, 10 partial, 1 unfilled (all 11 are the 2025-10-29 outage). Row counts
in the raw views: fid 60 576,638 (697 tokens), fid 10 47,567 (109), fid 1 743,602 (238).
Re-run `report` for current numbers.

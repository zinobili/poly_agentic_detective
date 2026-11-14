# Step 8 hand-off (milestone 2: election study, data)

Branch `claude/fervent-mayer-k4klat`. Study design and frozen hypotheses:
`docs/election/preregistration.md` (read it first; do not change it). This step builds the data
only: config, ingestion, clean panels. No statistics.

Environment: Linux cloud container, `.venv/bin/python`. Network allows Polymarket (gamma, clob),
Yahoo Finance (yfinance) and en.wikipedia.org. FRED and Stooq time out: do not use them.

## Decisions (main, 2026-11-13)
1. New subpackage `src/poly_actor/election/` (`config.py`, `ingest.py`, `panel.py`,
   `__main__.py`). Reuse, don't copy: `poly_actor.ingest.polymarket` (CLOB client, tiling,
   clipping, manifest), `poly_actor.ingest.common`, the XNYS calendar helpers used by
   `poly_actor.align` for bar end-stamping. Milestone-1 code and its tests stay untouched.
2. `config/election.yaml` is the single source of truth: signals (event id, market id, Yes token
   id, question), universe with sub-basket and a one-line rationale per name, placebo basket,
   controls, futures, vol indices, event timestamps. Token ids come from Gamma
   `GET /events/<id>`: 32224 (Senate), 32225 (House), 32228 (balance of power), and the
   moratorium events 1103960 (Indiana), 1103681 (Ohio), 1103684 (Texas), 1103961 (Oklahoma),
   1103970 (Missouri), 1103971 (Louisiana), 1139944 (North Carolina): the "by December 31, 2027"
   market of each. Match markets by question text, never by list position.
3. Raw (immutable, add-only) under `data/raw/election/`; clean under `data/clean/election/`.
4. CLI: `python -m poly_actor.election ingest [--workers N] [--dry-run]`, `... panel`.
   Both idempotent; a second ingest run makes zero network calls for closed markets.

## Data to pull
| What | Source | Range | Resolution |
|---|---|---|---|
| p_sen, p_house, p_sweep, p_rr (Yes tokens) | CLOB prices-history | 2025-07-11 → market close | fid 60 whole life + fid 10 whole life |
| same 4 tokens | CLOB | 2026-11-03 18:00 UTC → 2026-11-04 18:00 UTC | fid 1 |
| 7 moratorium tokens | CLOB | creation → 2026-11-13 | fid 60 |
| 29 AI + 29 placebo + RSP, SPY, TLT, QQQ, SMH, XLU | yfinance | 2025-06-01 → 2026-11-13 | 1d (auto_adjust=True) and 1h |
| NQ=F, ES=F, RTY=F | yfinance | 2026-10-27 → 2026-11-07 | 5m; also 1h for 2025-07 → now |
| ^VIX, ^VIX9D, ^VIX3M, ^VXN, ^VVIX, ^NDX | yfinance | 2018-01-01 → 2026-11-13 | 1d |

## Clean panels (parquet, tz-aware UTC `ts` columns)
- `daily.parquet`: one row per XNYS session and ticker: `session`, `close_ts` (the real session
  close in UTC, early closes included), `ticker`, `ret` (close-to-close log return, adjusted).
- `odds_daily.parquet`: per session and signal: `p` as-of `close_ts`, `age_s`, `dp` (change vs
  the previous session's as-of value). Missing when the reading is older than 6 h.
- `hourly.parquet`: per ticker, regular-session bars stamped at bar END (lesson: yfinance bars are
  start-stamped; last bar ends at the session close), `ret` within session only (no overnight
  return in this table).
- `odds_hourly.parquet`: per signal, `p` as-of each bar end, `age_s`, `dp` vs the previous bar end
  of the same session. Missing when older than 30 min.
- `night_5m.parquet`: futures 5-min bars stamped at bar end for the H3 window, plus `p_sen` etc.
  as-of each bar end from fid 1 (missing when older than 10 min).
- `vol_daily.parquet`: vol indices and ^NDX daily closes.
- `moratorium_daily.parquet`: per session, per state `p` as-of close, and the cross-state mean.
- `coverage.json`: per table row counts, date range, share of missing odds readings, median and
  p95 `age_s`; per ticker the number of sessions and any missing sessions.

## Rules as examples (each becomes a test)
| Input | Expected |
|---|---|
| CLOB points at 20:58:00 and 21:00:05 UTC, session close 21:00:00 UTC | as-of value is the 20:58:00 point (age 120 s); the 21:00:05 point is never used |
| Last CLOB point 7 h before the close | daily `p` is missing, `dp` missing for that session and the next |
| yfinance 1h bar stamped 15:30 ET on a normal day | end stamp 16:00 ET = 21:00 UTC (20:00 UTC in summer; test both sides of a DST switch) |
| Early-close session (2025-11-28, 13:00 ET) | `close_ts` = 18:00 UTC and the daily odds are read as-of 18:00 UTC, not 21:00 |
| Futures 5m bar stamped 19:00 ET | end stamp 19:05 ET; odds as-of 19:05:00, a point at 19:05:01 is not used |
| CLOB response containing a point after `endTs` (live-price trap) | clipped away |
| CRWV (listed 2025-03-28) | present for the whole sample; a ticker with missing sessions is listed in `coverage.json`, never silently forward-filled |
| Second `ingest` run | zero CLOB calls for closed tokens; identical file hashes |

## Checklist
1. `config/election.yaml` complete; every universe name has a rationale; a test checks 29 + 29
   names, 4 sub-baskets, no ticker in both baskets.
2. All tables built on real data; `coverage.json` written; report the share of missing odds
   readings and the median `age_s` at daily closes and at hourly bar ends.
3. No look-ahead: tests above pass; mutation-test the as-of guard (changing `<=` to allow a later
   point must fail a test) and the clip.
4. Offline tests with trimmed real fixtures in `tests/fixtures/election/`; no network in tests.
5. Spot-check in the report: 3 daily odds values and 3 stock returns against a raw re-fetch.
6. `bash scripts/check.sh` PASS. Full report → `docs/reviews/step8_build.md`; reply ≤ 250 words.

## Known traps (beyond lessons.md)
- `yfinance` 1h history is capped at 730 days and returns silent empty frames; check row counts.
  "Crumb fetch rate-limited (HTTP 429)" warnings are harmless; retry with backoff on empty frames.
- Futures trade ~23 h a day and have no exchange-calendar session: stamp bars at start + 5 min.
- The 4 midterm tokens resolved to ~1.0/0.0 on 4 Nov; closed markets keep serving history.
- BRK-B is the Yahoo symbol (not BRK.B).

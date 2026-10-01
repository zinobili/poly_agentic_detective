# Milestone 1 — Signal Lab: development plan

Question: does Polymarket lead, lag, or move with related stocks?
Approach: thin end-to-end slice first (1 market, 1 ticker, 1 chart), then widen. Every step ends with an independent validator check (`/validate-step N`).

## Decisions (2026-10-01)
- Stock data: **yfinance first** (1h bars, ~730 days). Alpaca later if needed.
- Pairs: Claude proposes well-known ones (step 2).
- Learning: **build first, explain after** (tutor agent writes lessons after each step).
- Pace: check in with user after step 0; then continue autonomously, always with validator.
- Agents: data-engineer, quant-researcher, validator, tutor.
- Python env: stdlib `venv` + pip (uv not installed). `pyproject.toml` is uv-compatible.

## Steps
| # | Step | Output | Main risk |
|---|------|--------|-----------|
| 0 | Setup + harness | repo, venv, tests, CLAUDE.md, agents, hooks, `/validate-step` | — |
| 1 | Data check | notebook: 1 market + 1 ticker on one chart; resolution findings | resolved markets may only return coarse history |
| 2 | Pick pairs | `config/pairs.yaml` with rationale | per-meeting Fed markets need stitching ("rolling") |
| 3 | Ingestion | `ingest/{polymarket,stocks,trends,news}.py` → `data/raw/*.parquet` | rate limits, pytrends successor stability |
| 4 | Alignment | UTC hourly panel, market-hours mask, log-odds Δ and log returns | look-ahead, tz/DST bugs |
| 5 | Dashboard | Streamlit + Plotly overlay per pair | — |
| 6 | Analysis | cross-corr, Granger, event study, placebo + multiple testing | fooling ourselves |
| 7 | Write-up | per-pair verdict: lead / lag / none + confidence | overclaiming |

## Requirements learned in step 1 (validator-confirmed)
Step 3 (ingestion):
- CLOB `prices-history`: use explicit `startTs`/`endTs` in **≤15-day** windows (15d+1s → HTTP 400, at fidelity 1 and 60). `interval=max` silently degrades or returns empty at fine fidelity.
- **Look-ahead trap:** for active markets the API appends the *current* live price after `endTs`. Drop every point outside `[startTs, endTs]`, with a test.
- yfinance 1h: `start=`/`end=` are capped at 730 **calendar** days. `period="730d"` means 730 *trading* days. A failed request returns an empty frame silently, so check row counts.
- Gamma timestamps come in mixed formats (`...Z` and `"2025-09-17 21:08:44+00"`); the parser must accept both.

Step 4 (alignment):
- yfinance 1h bars are labelled by their **start** time. Re-stamp each bar to its end time (the last bar of the day, 15:30–16:00 ET, is 30 minutes) or the stock side leaks up to 1h of the future.
- yfinance index is America/New_York; convert to UTC.

## Candidate pairs (to verify in step 2)
- Fed rate decision markets (per FOMC meeting) ↔ TLT, SPY, XLF
- US recession / GDP markets ↔ SPY, IWM
- Tariff / trade-deal markets ↔ sector ETFs (e.g. XLI, SOXX), specific exporters
- Crypto price / regulation markets ↔ COIN, MSTR
- Election / policy markets ↔ policy-sensitive sectors

## Done when
One command refreshes data; dashboard shows all pairs; lead-lag + event study results per pair with an honest conclusion.

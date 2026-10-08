# poly_actor

A research lab that asks one question: **do Polymarket prediction-market odds lead, lag, or move
together with related stock prices?**

> **Disclaimer.** This is a personal research project. Nothing here is financial or investment
> advice, and no result should be read as a trading recommendation. The code is **paper only**: it
> never places orders or moves money. Data comes from public third-party sources (Polymarket,
> Yahoo Finance via `yfinance`) and may be incomplete, delayed, or wrong. Use at your own risk.

## Status

Milestone 1 (lead, lag or move together?) is in its write-up step. See
[`docs/progress.md`](docs/progress.md) for the current step and
[`docs/milestone1_plan.md`](docs/milestone1_plan.md) for the plan.

| Step | What | Status |
|---|---|---|
| 0–2 | Setup, data feasibility check, pre-registered market→ticker pairs | done |
| 3 | Ingestion of Polymarket and stock price history | done |
| 4 | Alignment into hourly panels (no look-ahead, market hours only) | done |
| 5 | Dashboard for a lay reader | done |
| 6 | Pre-registered statistical analysis | done |
| 7 | Write-up: generated findings report, one-command refresh | in progress |

## Findings

The per-pair answers, with effect sizes, confidence intervals, the multiple-testing correction,
what the results do **not** show and every amendment made after seeing results, are in
[`docs/findings.md`](docs/findings.md). That file is generated from the analysis results by code
(`python -m poly_actor.analysis report`), so this README states no verdicts or numbers of its own.
It is not financial advice.

## Method in brief

- **Pre-registration.** The market→ticker pairs and tests were fixed in
  [`docs/preregistration.md`](docs/preregistration.md) and [`config/pairs.yaml`](config/pairs.yaml)
  before any price history was viewed. Each pair has a written rationale.
- **No look-ahead.** A value at time *t* only uses data available at or before *t*.
- **UTC everywhere.** All timestamps are timezone-aware UTC.
- **Immutable raw data.** Downloads go to `data/raw/` and are never edited. Derived data goes to
  `data/clean/`. The `data/` folder is not committed and is re-created by running the ingestion.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on macOS/Linux
```

No API keys are needed for the current data sources. Optional keys for future sources are listed in
[`.env.example`](.env.example). Copy it to `.env`, which is git-ignored.

## Run the pipeline and the dashboard

One command refreshes everything: it fetches new data, rebuilds the panels, re-runs the analysis
and regenerates `docs/findings.md`. It stops at the first stage that fails and names it.

```bash
.venv/Scripts/python.exe -m poly_actor.refresh --workers 4    # ingest -> align -> analysis -> report
.venv/Scripts/python.exe -m poly_actor.refresh --dry-run      # print the stages; run nothing
.venv/Scripts/streamlit.exe run src/poly_actor/dashboard/app.py   # opens on http://localhost:8501
```

The stages can also be run one at a time:

```bash
.venv/Scripts/python.exe -m poly_actor.ingest run --workers 4    # fetch raw data into data/raw/
.venv/Scripts/python.exe -m poly_actor.align run                 # build hourly panels in data/clean/
.venv/Scripts/python.exe -m poly_actor.analysis run --workers 4  # tests -> data/clean/results/*.json
.venv/Scripts/python.exe -m poly_actor.analysis report           # results -> docs/findings.md
```

Until the analysis writes `data/clean/results/`, the dashboard shows the raw data and marks every
analysis section "Not run yet". Restart Streamlit after a refresh if it was already running.

## Tests and lint

```bash
.venv/Scripts/python.exe -m pytest              # offline; network access is blocked in tests
.venv/Scripts/python.exe -m pytest -m live      # tests that call real APIs
.venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .
```

## Layout

```
src/poly_actor/   ingest/ store/ align/ analysis/ dashboard/
config/           pairs.yaml (pre-registered pairs)
docs/             plans, pre-registration, step reports, progress
notebooks/        exploration and short lessons
scripts/          one-off generators (e.g. build_pairs.py)
tests/            offline tests and small fixtures
.claude/          agent definitions and hooks used to build this repo with Claude Code
```

## Data sources and terms

- [Polymarket](https://polymarket.com) public CLOB/Gamma APIs
- Yahoo Finance via [`yfinance`](https://github.com/ranaroussi/yfinance), which is unofficial and not
  affiliated with Yahoo

This repo does not redistribute datasets. You download data yourself and are responsible for
following each provider's terms of use.

## License

[MIT](LICENSE)

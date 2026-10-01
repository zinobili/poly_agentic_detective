# poly_actor

A research lab that asks one question: **do Polymarket prediction-market odds lead, lag, or move
together with related stock prices?**

> **Disclaimer.** This is a personal research project. Nothing here is financial or investment
> advice, and no result should be read as a trading recommendation. The code is **paper only**: it
> never places orders or moves money. Data comes from public third-party sources (Polymarket,
> Yahoo Finance via `yfinance`) and may be incomplete, delayed, or wrong. Use at your own risk.

## Status

Work in progress (milestone 1). See [`docs/progress.md`](docs/progress.md) for the current step and
[`docs/milestone1_plan.md`](docs/milestone1_plan.md) for the plan. No findings have been published yet.

| Step | What |
|---|---|
| 0–2 | Setup, data feasibility check, pre-registered market→ticker pairs |
| 3 | Ingestion of price data (in progress) |
| 4–7 | Alignment, dashboard, statistical analysis, write-up |

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

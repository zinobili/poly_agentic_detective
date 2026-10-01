# poly_actor

Polymarket-to-stock-market signal lab. Goal of milestone 1: find out whether Polymarket odds lead, lag, or move with related stocks. Plans: `docs/milestone1_plan.md`, `docs/agents_and_harness.md`. Status: `docs/progress.md`.

## Commands (Windows, Git Bash paths)
- Tests (offline, default): `.venv/Scripts/python.exe -m pytest`
- Live API tests: `.venv/Scripts/python.exe -m pytest -m live`
- Lint/format: `.venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format .`
- Install: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"`

## Hard rules
- **UTC everywhere.** Store tz-aware UTC timestamps. Never use naive datetimes (ruff `DTZ` enforces).
- **No look-ahead.** A value at time t may only use data available at or before t.
- **Tests never hit the network** unless marked `@pytest.mark.live`. Use saved responses in `tests/fixtures/`.
- **Raw data is immutable.** Ingestion writes to `data/raw/`; derived data goes to `data/clean/`. Never delete raw.
- **Paper only.** No code that places real orders or moves real money.
- **Secrets** live in `.env` (git-ignored, blocked by hook). Document new keys in `.env.example`.
- Every market→ticker pair in `config/pairs.yaml` needs a written rationale.

## Workflow (every step)
1. Plan the step → 2. build (hooks auto-run ruff) → 3. run tests →
4. **independent validation**: spawn a fresh `validator` agent via `/validate-step <N>` →
5. fix findings → 6. summarize to user (what changed, setup steps, what to test, limits) → 7. update `docs/progress.md`.
Do not mark a step done without a validator report. Check in with the user after step 0; afterwards continue, but always validate.

## Layout
`src/poly_actor/{ingest,store,align,analysis,dashboard}`, `config/`, `data/{raw,clean}` (ignored), `notebooks/`, `tests/`, `docs/`.

## Agents (`.claude/agents/`)
`data-engineer`, `quant-researcher`, `validator` (read-only + runs tests), `tutor` (explains after build).

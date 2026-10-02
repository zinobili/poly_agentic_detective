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
1. **Plan.** Write or refresh `docs/handoff/step<N>.md` with the decisions, requirements, the minors carried over, and the checklist. Write rules as 2–3 input → expected-output examples, not prose.
2. **Build.** Brief the builder agent short: "Read `docs/handoff/lessons.md` and `step<N>.md`, then do X." The builder self-checks against the checklist and the lessons before reporting.
3. **`bash scripts/check.sh`** runs the tests, ruff, the pairs.yaml rebuild and the ingest dry run.
4. **Validate** with `/validate-step <N>`, using a fresh validator. Severity gate: only blockers and majors trigger a re-check, and minors move to the next step's hand-off. **At most 2 rounds**, then ask the user.
5. **Commit** locally, then update `docs/progress.md`.
   **Before any push to GitHub:** run the `clean-code-crusader` agent on the unpushed diff (software-engineering standards). Fix its blockers and majors, run `scripts/check.sh`, then push.
6. **Report to the user once per step boundary**, not after every agent report.

Do not mark a step done without a validator report.

**Agent reports are ≤250 words.** Full reports live in `docs/reviews/step<N>_{build,r<K>}.md`; open them only when needed.

**Long data runs:** use concurrent workers (`--workers`) and run in the background while other work, such as code review or tests, continues.

## Usage guard (5-hour plan limit)
In the desktop app, `mcp__ccd_session_mgmt__get_usage` reports the 5-hour % (not available in a plain terminal session). The limit can still hit between checks, so stay resumable:
- **Reminder:** when reporting to the user at a workflow boundary, check `get_usage`; if the 5-hour window is ≥ 85%, add one line: `⚠ 5-hour usage at N%, resets HH:MM UTC`. Below 85%, say nothing.
- At every workflow boundary (before starting a step, before spawning an agent, after each agent returns), keep a `## Resume here` section at the top of `docs/progress.md` current: date, current step and workflow stage, what's done, what's half-done (files touched), exact next action, open validator findings, what's waiting on the user.
- Prefer one big agent at a time over several in parallel, and keep agent briefs scoped and lean.
- When the user says usage is near the limit: finish the current small task, update the resume note, don't spawn new agents, and end the turn.
- On resume, read `## Resume here` first and continue from "next action". Keep the section updated, don't delete it.
- Commits: after a step's validator passes, commit locally (user-approved for all steps). Never push without asking.

## Layout
`src/poly_actor/{ingest,store,align,analysis,dashboard}`, `config/`, `data/{raw,clean}` (ignored), `notebooks/`, `tests/`, `docs/`.

## Agents (`.claude/agents/`)
`data-engineer`, `quant-researcher`, `validator` (research correctness: read-only + runs tests), `clean-code-crusader` (engineering standards review before each push), `tutor` (explains after build).

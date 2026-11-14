# Docs map

| Where | What |
|---|---|
| [`studies/README.md`](studies/README.md) | How the lab is organised and how to add a study |
| [`studies/leadlag/`](studies/leadlag/README.md) | Study 1: do Polymarket odds lead, lag, or move with related stocks? |
| [`studies/election/`](studies/election/README.md) | Study 2: the partisan beta of AI around the 2026 US midterm |
| [`lessons.md`](lessons.md) | Every bug class a validator has caught. Builders and validators read it first |
| [`progress.md`](progress.md) | Status, decision log, and the "Resume here" note |
| [`backlog.md`](backlog.md) | Open minors and ideas, per study |
| [`harness/`](harness/agents_and_harness.md) | The agents, hooks and workflow used to build the repo |
| [`reviews/`](reviews/README.md) | Pre-push reviews that span several studies or only shared code |

Inside a study folder: `preregistration.md` (the frozen plan and its dated amendments),
`findings.md` (generated from results, never typed), `handoff/step<N>.md` (the plan for each
step), `reviews/` (builder, validator and code-review reports), and images.

## Paths before the restructure of 2026-11-14

Hand-offs, reviews and `progress.md` are records and keep the paths of their time. Read them with
this table.

| Old | New |
|---|---|
| `src/poly_actor/{ingest/common,ingest/polymarket,ingest/stocks}.py` | `src/poly_actor/core/ingest/` |
| `src/poly_actor/align/{grid,prices}.py`, `align/stocks.py` | `src/poly_actor/core/timegrid/{grid,prices}.py`, `core/timegrid/bars.py` |
| `src/poly_actor/analysis/models.py` | `src/poly_actor/core/stats/models.py` |
| `src/poly_actor/store/`, `dashboard/style.py` | `src/poly_actor/core/store/`, `core/ui/style.py` |
| `src/poly_actor/{ingest,align,analysis,dashboard,pairs_build}/`, `pairs.py`, `refresh.py` | `src/poly_actor/studies/leadlag/` |
| `src/poly_actor/election/` | `src/poly_actor/studies/election/` |
| `config/pairs.yaml`, `config/election.yaml` | `config/leadlag/pairs.yaml`, `config/election/election.yaml` |
| `docs/milestone1_plan.md`, `docs/preregistration.md`, `docs/findings.md`, `docs/step*.md`, `docs/design/`, `docs/images/` | `docs/studies/leadlag/` (`plan.md`, …) |
| `docs/election/`, `docs/images/election/` | `docs/studies/election/`, `docs/studies/election/images/` |
| `docs/handoff/step3–7.md`, `docs/reviews/step3–7_*`, `push_2026-10-*` | `docs/studies/leadlag/{handoff,reviews}/` |
| `docs/handoff/step8–10.md`, `docs/reviews/step8–10_*`, `push_2026-11-*` | `docs/studies/election/{handoff,reviews}/` |
| `docs/handoff/lessons.md`, `docs/handoff/milestone2_backlog.md` | `docs/lessons.md`, `docs/backlog.md` |
| `docs/agents_and_harness.md`, `docs/playbook/` | `docs/harness/` |
| `tests/test_*.py`, `tests/*_synth.py`, `tests/fixtures/` | `tests/{core,leadlag,election}/`, helpers and `fixtures/` inside each study's folder |
| `python -m poly_actor.{ingest,align,analysis,refresh}` | `python -m poly_actor.studies.leadlag.{ingest,align,analysis,refresh}` |
| `python -m poly_actor.election` | `python -m poly_actor.studies.election` |

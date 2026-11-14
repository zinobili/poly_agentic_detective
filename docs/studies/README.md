# Studies

This repo is a lab: several studies, one shared toolkit. A study asks one question, freezes its
plan before looking at outcomes, and ends in a generated findings report and a Streamlit page.
`python -m poly_actor` lists the studies and how to run each.

| Study | Question | Verdicts |
|---|---|---|
| [`leadlag`](leadlag/README.md) | Do Polymarket odds lead, lag, or move with related stocks? | [findings](leadlag/findings.md) |
| [`election`](election/README.md) | Did AI stocks carry a partisan beta around the 2026 US midterm? | [findings](election/findings.md) |

## Where things live

| Piece | Path | Rule |
|---|---|---|
| Shared toolkit | `src/poly_actor/core/` | Never imports a study |
| Study code | `src/poly_actor/studies/<id>/` | Never imports another study |
| Registry | `src/poly_actor/studies/__init__.py` | Every study is listed once |
| Config | `config/<id>/*.yaml` | Every market, pair or universe name has a written rationale |
| Plan, findings, hand-offs, reviews, images | `docs/studies/<id>/` | Findings are generated, never typed |
| Tests | `tests/<id>/`, with its synthetic-data helpers and saved responses in `tests/<id>/fixtures/` | Offline unless marked `live` |
| Raw and derived data | `data/raw/<id>/`, `data/clean/<id>/` | Git-ignored; raw is immutable |
| Published results | `reports/<id>/` | Tracked, small, derived aggregates only |

`tests/core/test_architecture.py` fails if a study is unregistered, lacks one of its standard
places, or if the import rules are broken. The lead-lag study predates the layout in one respect:
its data sits at the top of `data/raw/` and `data/clean/`.

## What `core` gives a new study

| Need | Use |
|---|---|
| Polymarket odds history | `core.ingest.polymarket` (tiling, clipping of the live-price look-ahead trap, manifest, gap backfill) |
| Stock, ETF, futures and index bars | `core.ingest.stocks.fetch_bars` (any interval, retries on silent empty frames) and `parse_bars` |
| Idempotent, add-only raw storage | `core.ingest.common` (`Manifest`, `write_parquet_once`, `ingest_lock`, interval arithmetic) |
| Sessions, early closes, bar end-stamping | `core.timegrid.grid` |
| "Latest value at or before t", with a staleness cap | `core.timegrid.prices.PriceBook` |
| Bar returns and opening gaps | `core.timegrid.bars` |
| HAC regression, linear tests, Spearman with permutation p, BH, bootstrap CIs | `core.stats.models` |
| Circular-shift placebos | `core.stats.shifts` |
| Strict JSON and atomic writes | `core.io` |
| Eastern Time to UTC | `core.timeutil` |
| Page styling shared by the Streamlit apps | `core.ui.style` |

When a second study needs something that lives inside a study, move it to `core` first, with its
tests, and import it from there in both.

## Adding a study

1. **Pick an id** (short, lower-case, e.g. `earnings`). It names the package and every folder.
2. **Scout the data, look at nothing else.** Confirm sources, resolution and date range. Write
   down every number seen during scouting; it goes into the disclosure.
3. **Freeze the plan.** Copy [`_template/preregistration.md`](_template/preregistration.md) to
   `docs/studies/<id>/preregistration.md`, fill it in and commit it before any outcome is compared
   with the signal. The commit is the timestamp.
4. **Create the standard places:** `src/poly_actor/studies/<id>/` (with `__init__.py` and a
   `__main__.py` or CLI module), `config/<id>/`, `tests/<id>/`, `docs/studies/<id>/README.md`,
   and a `Study(...)` entry in the registry.
5. **Work in steps** (data, analysis, presentation is the usual split). For each step, copy
   [`_template/handoff/step.md`](_template/handoff/step.md) to
   `docs/studies/<id>/handoff/step<N>.md` and follow the workflow in `CLAUDE.md`: plan, build,
   `scripts/check.sh`, independent validation, commit, code review before the push.
6. **Generate, don't type.** The analysis writes a results file; the findings report and the page
   read only that file. A number that is not in the results is not shown.
7. **Close out.** Verdicts and review paths go into `docs/progress.md`, open minors into
   `docs/backlog.md`, new bug classes into `docs/lessons.md`.

The election study is the reference for a study that publishes a tracked results bundle
(`ingest → panel → analyse → publish → report` in one CLI). The lead-lag study is the reference
for a multi-pair study driven by a generated config.

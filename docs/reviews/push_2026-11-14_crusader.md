# Pre-push review, 2026-11-14 (step 10), clean-code-crusader r1

Scope: `git diff origin/claude/fervent-mayer-k4klat..03136d4`. ruff clean. Tests not run (586 passed per caller).

**Verdict: SHIP WITH FIXES** (0 blockers, 2 majors, 8 minors)

| Category | Score |
|---|---|
| Design/structure | 4 |
| Readability | 4 |
| Types | 3 |
| Error handling | 3 |
| Tests | 4 |
| Config/constants | 4 |
| Security | 5 |
| Performance | 4 |
| Consistency | 3 |
| Docs/hygiene | 4 |

## Majors

1. **Swallowed errors in `_guarded`** (`report_text.py:477-488`). It catches `KeyError, TypeError, IndexError, ValueError, AttributeError` and returns `missing=True` with no log. A malformed bundle (renamed key, wrong type) is shown as "not in the results" and the cause is lost. It also masks genuine bugs in the text functions. Fix: `log.warning("chart text %r unavailable", kicker, exc_info=True)` in the except branch. Also narrow the list where possible, and type the decorator (`Callable[[Callable[..., ChartText]], Callable[..., ChartText]]`).
2. **Corrupt-bundle paths are untested** (`report_load.py:48-54, 60-64`). Tests cover only a missing folder (`test_election_report.py:368`). Nothing covers invalid JSON, a JSON list (the `not isinstance(dict)` branch), an unreadable CSV, a series path that points to a missing file, or `bundle_signature` changing on rewrite. Each branch is a guard that can be deleted with no test failing. Fix: add 4 small `tmp_path` tests. Also log a warning for a missing series file (`report_load.py:58-59`) and for the non-dict case (line 54). Both return silently today, unlike the other two failure paths.

## Minors

1. `report_load.py:91` / `app.py:91`: `signature: tuple` is a bare tuple. Use `tuple[tuple[str, int], ...]`. The cache key is also computed on each rerun with a full `rglob` plus `stat`. This is fine at the current size.
2. `charts.py:34-52`: `PALETTE` and the style constants duplicate the idea in `poly_actor.dashboard.style` and `dashboard/charts.py`, and the two modules now have different `_layout` and margin conventions. Share the palette in one place, or note why the election study keeps its own.
3. `app.py:189-190, 210-211`: `# fmt: skip` on hand-wrapped `st.markdown` calls. Extract a `_kicker(label)` helper. It is also reusable at `app.py:118`.
4. `app.py:120-124`: `st.subheader(ct.title, ...)` is duplicated across the `missing` branch. Hoist it above the `if`.
5. `app.py:239`: `zip(..., strict=False)` hides a length mismatch. That is intended for the odd last block, so add a comment saying so.
6. `findings.py:171`: `render` has no docstring. `slots` (about 50 lines) is long but flat, so it is acceptable.
7. `report_text.py` is 1333 lines. Consider splitting formatters (`pct`, `span`, `day`) from per-block prose. The module is cohesive, so this is not urgent.
8. `.claude/launch.json`: the added `election-linux` entry is machine-specific and sits beside Windows paths. It is harmless, but the README says to use `.venv/bin`. Keep one convention.

## Checked and fine

- No secrets or absolute paths in the diff. `docs/images/election/` totals 1.9 MB across 10 PNGs, which is acceptable. The fixture bundle is a small CSV set.
- README commands match the CLI: `report` exists, and the `ingest|panel|analyse|publish` list is correct. `pyproject` package-data now includes `*.txt`.
- Layout is cleanly separated: `app.py` is layout only, `charts.py` holds figures, `report_text.py` holds prose, and `report_load.py` does read-only I/O. `findings.py` reuses `report_text`, so there is no duplicated prose. It writes atomically and the slot filler fails loudly on an unknown slot.
- Tests are strong. They trace numbers back to the results, check the template for stray digits, check determinism, run `AppTest` offline, and assert the committed findings match the bundle.
- The `cli.py` type hints were added, and `cmd_report` returns exit code 2 with a clear message.

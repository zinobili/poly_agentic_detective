---
name: validate-step
description: Run independent validation of a finished poly_actor milestone step by spawning a fresh validator agent with that step's checklist. Use after finishing any step, or when the user types /validate-step <N>.
---

# Validate a step

Argument: the step number (0–7). If missing, ask.

1. Make sure `docs/handoff/step<N>.md` is current: decisions, requirements, the builder's claims, and the path to the builder's report. Keep the brief short: "Validate step N, round K. Read docs/handoff/step<N>.md and the checklist below." Don't paste history.
2. Spawn a **fresh** agent (`subagent_type: validator`). Do NOT fork: the validator must not inherit the builder's assumptions.
   - **Model:** the default (sonnet) for re-checks and mechanical steps. Pass `model: "opus"` only for the FIRST validation round of analysis-heavy steps (4 and 6), or when sonnet reports something it couldn't resolve.
   - **Re-check rounds:** scope the brief to the diff since the last round plus the previous review's blockers and majors.
3. **Severity gate.** When the ≤250-word summary arrives:
   - Blockers or majors: fix them, then re-validate (scoped).
   - Minors only: the step PASSES. Commit, and append the minors to `docs/handoff/step<N+1>.md` so the next builder handles them. Don't spend a round on them.
4. **Round cap: at most 2 validation rounds per step.** If round 2 still has blockers or majors, stop and ask the user. Options: accept with known issues, park the failing part (e.g. one pair), or do one more round. Don't loop.
5. Record the verdict and the review path in `docs/progress.md`. Add any new general lesson (a bug class the builder should have caught) to `docs/handoff/lessons.md`.
4. Tell the user: verdict, what was fixed, what remains open.

## Checklists

**Step 0 — setup**
- Fresh install works: new venv, `pip install -e ".[dev]"`, `pytest` passes, `ruff check .` clean.
- `.env` and `data/` are git-ignored; no secrets tracked (`git ls-files`, `git check-ignore`).
- Hooks: guard blocks `.env` reads and force-push; post-edit hook formats .py files. Settings JSON is valid.
- Layout matches `CLAUDE.md`; agent files have valid frontmatter.

**Step 1 — data check**
- Independently re-fetch the same Polymarket market and ticker; confirm reported resolution and date range.
- Check finest `fidelity` returned for a resolved vs. active market.
- Confirm timestamps are UTC and the plotted series match raw data at 3 random points.

**Step 2 — pairs**
- Each pair in `config/pairs.yaml` has a rationale; challenge whether the link is real.
- Rolling/stitching across per-meeting markets: no gaps or overlaps; roll dates documented.

**Step 3 — ingestion**
- Running twice yields identical files (hash them). Incremental fetch only pulls new rows.
- 429/5xx handling with backoff exists. Tests pass offline (disable network if possible).

**Step 4 — alignment**
- UTC correctness, DST transitions, market-hours mask, no forward-fill across long gaps.
- No look-ahead: shift tests; spot-check 3 aligned rows against raw sources.

**Step 5 — dashboard**
- App launches; chart values match DuckDB for a sampled pair/time.

**Step 6 — analysis**
- Methods recover a planted lag in synthetic data; return nothing on independent noise.
- Placebo events and multiple-testing correction present; CIs reported.

**Step 7 — write-up**
- Every number in the write-up traces to code output; conclusions don't overclaim.

# Crusader review: push 2026-11-13 (docs only, c535852..534d5c1)

**Verdict: SHIP.** Scores: design 5, readability 4, types n/a, errors n/a, tests 4 (as specified), config 4, security 5, performance n/a, consistency 4, docs 4.

## Blockers / majors
None.

## Checks done
- Counts: 8+6+8+7 = 29 AI names; placebo list = 29; no overlap. Step 9 "pooled 58" matches.
- Verdict strings, Holm example (0.03 > 0.025), MDE 0.5%/0.8% thresholds, shift counts (1,000 / min 20 / 10,000), BH over 7 lags: identical across prereg, step 9, step 10.
- Dates: freeze 2026-11-13 = 10 days after 2026-11-03; first session 2025-07-14 (Mon) after 2025-07-11; H2 cutoff 2026-10-30 vs the "no row >= 2026-11-02" test is consistent (no session between).
- Paths and reuse targets exist: docs/design/dashboard_ux.md, .claude/launch.json, dashboard/style.py:page_css, analysis/models.py (ols, bh, spearman, spearman_perm_p, fisher_ci), analysis/placebo.py, lessons B1. `data/` is git-ignored, `reports/` is not (needed for tracked bundle).
- No secrets, keys, personal paths or emails in the diff. UTC rule respected (ET only for display/window definitions). Paper-only respected.

## Minor
1. step8.md: 10-min odds staleness for the 5m night table is not in the prereg (prereg only fixes 30 min / 6 h). Record it as a dated amendment or note it as an implementation detail before the data is seen.
2. step8.md pulls QQQ and SMH; the prereg uses neither. Drop or mark unused.
3. progress.md: "push to the branch at the end without asking again" departs from CLAUDE.md "Never push without asking". It is a recorded explicit user decision, so acceptable, but keep that wording attributed to the user.
4. Prereg H2 one-sided direction is justified by the observed event ΔP sign; the disclosure covers the odds path, so fine, but state it under "seen before freeze" explicitly.
5. step9/10 refer to `docs/reviews/step8_build.md` and CLI subcommand `report`, which do not exist yet (expected, produced by later steps).

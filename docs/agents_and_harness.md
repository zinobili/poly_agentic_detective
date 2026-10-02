# Agents and harness

## Build-time agents (active)
| Agent | File | Job | Tools |
|---|---|---|---|
| data-engineer | `.claude/agents/data-engineer.md` | ingest, store, align | full + web |
| quant-researcher | `.claude/agents/quant-researcher.md` | analysis methods + interpretation | full |
| validator | `.claude/agents/validator.md` | independent check after each step | read + bash, no edits |
| clean-code-crusader | `.claude/agents/clean-code-crusader.md` | engineering-standards review before every push (design, types, errors, tests, security, performance) | read + bash, writes only docs/reviews/ |
| tutor | `.claude/agents/tutor.md` | lessons after each step | write `notebooks/` only |

Bring in as needed: Planner (built-in `Plan`), Source Scout, Market Mapper, Compliance/Risk, Scribe, Code Reviewer (`/code-review`).

Later runtime agents (milestone 3+): News Classifier, Signal Agent, Risk Manager, Paper Trader, Monitor.

## Multi-agent patterns
- **Pipeline (every step):** plan → build → validator → `/code-review` → user/summary → progress.md
- **Parallel fan-out:** independent work only (e.g. one ingest module per agent, in separate git worktrees).
- **Adversarial:** validator tries to break steps 4 and 6 with synthetic data, placebo events, leakage tests.

## Harness pieces
| Piece | Location | Status |
|---|---|---|
| Project rules | `CLAUDE.md` | done |
| Agents | `.claude/agents/` | done (4) |
| `/validate-step N` | `.claude/skills/validate-step/` | done |
| Guard hook (.env, force-push, reset --hard, clean -f) | `.claude/hooks/guard.py` | done, tested |
| Post-edit ruff hook | `.claude/hooks/post_edit.py` | done |
| Permissions | `.claude/settings.json` | done |
| Hook tests | `tests/test_hooks.py` | done |
| More skills (`/add-source`, `/add-pair`, `/explain`) | — | when needed |
| pre-commit, CI | — | later |
| Scheduled refresh | — | later |

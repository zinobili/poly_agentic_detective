# Playbook: token saving and speed in multi-agent Claude Code projects

This is a portable set of lessons and templates for any repo that uses a main agent plus subagents (builder → independent validator). It comes from a real project, a data and quant research repo, where one step used about **1.3M subagent tokens across 12 agent runs**, mostly on rework. A comparable step run with these practices used about 340k.

Copy this file into a new repo, then adapt the templates at the bottom.

---

## 1. Where the tokens actually go

| Cost driver | Typical symptom | Share of waste |
|---|---|---|
| **Rework loops** | The validator fails the builder, the builder fixes, the validator fails again on a different issue (6+ rounds) | Largest |
| **Long agent reports in the main context** | Every 3–5k-token report is pasted whole into the main conversation, and the main context bloats | Large |
| **Re-explaining context** | Each fresh agent gets a long brief re-telling history, especially after a session restart | Medium |
| **Main agent narrating** | A status update to the user after every single agent report | Medium |
| **Duplicate checks** | The main agent and each validator re-derive tests, lint and rebuild checks by hand | Small but constant |
| **Sequential I/O** | Long data pulls at about 1 request/s while nothing else happens | Wall-clock time, not tokens |

**Main insight:** the work itself is cheap. Rework is what costs. Optimize for getting it right the first time and for short handoffs, not for skipping validation.

---

## 2. The ten practices

### 1. Give the builder the validator's checklist up front (biggest saver)
- Each builder brief points to the exact checklist the validator will use, plus a **lessons file** of every bug class caught so far.
- The builder self-checks against both before reporting.
- *Why:* most validation failures were predictable ("used derived dates instead of the official calendar", "didn't paginate the API"). A builder who knows the exam passes the first time.

### 2. Keep a living `lessons.md`
- Every time a validator catches a *class* of bug, add one line to `docs/handoff/lessons.md`.
- Group it by theme: time and look-ahead, data sources, design, process.
- Builders and validators read it first.
- This is how the project stops repeating its mistakes.

### 3. Cap agent replies (≤250 words); full reports go to files
- Agents write their full report to `docs/reviews/step<N>_{build,r<K>}.md`.
- They return only: verdict, blockers and majors (one line each, with file:line), a count of minor issues, and the file path.
- The main agent opens the file only when it needs to.
- *Savings:* about 60–70% of main-context growth.

### 4. Severity gate and round cap on validation
- **Only blockers and majors trigger a re-validation.** Minor issues roll into the next step's hand-off file.
- **At most 2 validation rounds per step.** After that, escalate to the user with three options: accept with known issues, park the failing part, or allow one more round.
- *Why:* without a cap, perfectionism on one sub-feature, such as one data series, can consume more than the rest of the step combined. Park it early.

### 5. Scope re-checks to the diff
- A re-validation brief covers the **diff since the last round plus the previous review's blockers and majors**. Never re-audit everything.
- Builders keep the expensive validator's confirmed facts ("tests pass, rebuild md5 X") in the hand-off file, so nobody re-derives them.

### 6. Match the model to the job

| Job | Model |
|---|---|
| Builder for plumbing and data | Mid tier (e.g. sonnet) |
| First validation of analysis or statistics-heavy work | Top tier (e.g. opus) |
| Re-checks, mechanical checks, doc review | Mid tier |
| Tutor, explainer, summaries | Mid or small tier |

Set the default in the agent's frontmatter (`model:`) and override it per call only when needed.

### 7. Use hand-off files instead of long briefs
- `docs/handoff/step<N>.md` holds the decisions, requirements, carried-over minors, the builder's claims, and what the next round should check.
- Briefs shrink to: *"Read `docs/handoff/lessons.md` and `step<N>.md`, then do X."*
- It survives session restarts, which matters because agent transcripts may not.

### 8. One check command
- `scripts/check.sh` (or `make check`) runs the tests, lint and format, any reproducibility check (e.g. "regenerated config is byte-identical"), and a dry run of the pipeline.
- Builders, validators and the main agent all run that one command.
- It prints one line per check and ends with `CHECK: PASS` or `CHECK: FAIL`.

### 9. Write specs as examples, not prose
- State each rule as 2–3 concrete input → expected-output cases, and turn them straight into tests.
- *Real failure:* a direction rule ("strike ≥ K" vs "≤ K") was written backwards in prose. It was caught only because the builder questioned it, and then it leaked into the generated docs anyway.
- Tell builders: **"If the brief and the data disagree, flag it. Don't silently pick one."**

### 10. Speed: parallel I/O and background runs
- Long API pulls get **N concurrent workers** within the rate limit. Use one worker per independent unit (e.g. per market or ticker), keep ordered work inside a unit, and put a lock around shared logs and manifests. Test that parallel output is byte-identical to sequential.
- Run long jobs **in the background** while code review or tests continue.
- Keep a **dry run** that prints planned calls and estimated time before anything real runs.

---

## 3. Main-agent communication habits
- **One user update per step boundary**, plus anything that needs a decision. Not one per agent report.
- When relaying an agent result, give the verdict, what changed, and what's next in 5–10 lines.
- Keep a `## Resume here` section at the top of `docs/progress.md`, updated at every boundary. Include: the date, the current step and stage, what's done, what's half-done (files touched), the exact next action, open findings, and what's waiting on the user. **The usage limit can hit without warning.** This note makes a cut-off free.
- Prefer **one big agent at a time** when usage is tight. Parallel agents finish faster but spike usage.

---

## 4. What NOT to cut
- **The independent validator.** In the source project it caught a future-data leak in the API, wrong official dates, a release that never happened (government shutdown), silent data holes and an inverted rule. Each would have silently corrupted the final results. Save tokens by reducing *rounds*, not by skipping validation.
- **Mutation tests on key guards.** A test that still passes after its guard is removed is worthless. Validators should break the guard on purpose and confirm the test fails.
- **Fresh (non-forked) validators.** A forked validator inherits the builder's blind spots.

---

## 5. Templates

### 5.1 Agent frontmatter and report rules (builder)
```markdown
---
name: data-engineer
description: Builds data plumbing (ingest/, store/, align/).
tools: Read, Grep, Glob, Edit, Write, Bash, WebFetch, WebSearch
model: sonnet
---
Start by reading docs/handoff/lessons.md, docs/handoff/step<N>.md, and the step's
checklist in .claude/skills/validate-step/SKILL.md.

Sourcing: take dates and schedules from official sources; paginate every listing until it
comes back empty; if the brief and the data disagree, flag it.

Before reporting:
1. Self-check against the checklist and lessons.md. Fix what fails.
2. Run scripts/check.sh.
3. Write the full report to docs/reviews/step<N>_build_r<K>.md.
4. Return at most 250 words: what was done, the check.sh result, decisions needed, the report path.
```

### 5.2 Validator agent
```markdown
---
name: validator
description: Independent skeptic. Read-only on code; writes only docs/reviews/.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---
Read CLAUDE.md, docs/handoff/lessons.md, docs/handoff/step<N>.md.
Run scripts/check.sh once. Verify claims yourself. Be adversarial and mutation-test key guards.
On a re-check round, check only the diff plus the previous blockers and majors.
Write the full review to docs/reviews/step<N>_r<K>.md.
Return at most 250 words: verdict, blockers and majors (file:line), minor count, review path.
```

### 5.3 Validate-step skill: core rules
```markdown
1. Keep docs/handoff/step<N>.md current. Brief: "Validate step N round K. Read the hand-off + checklist."
2. Spawn a FRESH validator (never fork). Use the default model; use the top model only for the first
   round of analysis-heavy steps.
3. Severity gate: blockers or majors → fix and re-validate (scoped). Minors only → PASS, commit,
   and move the minors to step<N+1>.md.
4. At most 2 rounds, then ask the user (accept / park / one more round).
5. Record the verdict and review path in progress.md; add new bug classes to lessons.md.
```

### 5.4 `scripts/check.sh` skeleton
```bash
#!/usr/bin/env bash
set -u; cd "$(dirname "$0")/.."
fail=0; step(){ printf '%-26s' "$1"; }
step "tests";        out=$(python -m pytest --color=no 2>&1); rc=$?
echo "$out" | grep -Eo '[0-9]+ (passed|failed)[^=]*' | tail -1; [ $rc -eq 0 ] || fail=1
step "lint";         ruff check . -q && echo ok || fail=1
step "format";       ruff format --check . -q && echo ok || fail=1
step "reproducible"; python scripts/build_config.py >/dev/null && git diff --quiet -- config/ \
                       && echo ok || { echo DIFFERS; fail=1; }
step "dry-run";      python -m mypkg.ingest run --dry-run 2>&1 | tail -1
[ $fail -eq 0 ] && echo "CHECK: PASS" || echo "CHECK: FAIL"; exit $fail
```
*Gotcha:* if the project's pytest config already sets `-q`, don't add another `-q`, or pytest drops the summary line.

### 5.5 Hand-off file
```markdown
# Step <N> hand-off: <name>
**Status:** … **Next:** …
## Requirements (as input → expected-output examples where possible)
## Builder's claims (numbers, md5s, counts) and the full report path
## Carried-over minors from step <N-1>
## What the next validation round should check (scoped)
```

### 5.6 `CLAUDE.md` workflow block
```markdown
## Workflow (every step)
1. Plan: refresh docs/handoff/step<N>.md (rules as examples).
2. Build: short brief → builder self-checks vs the checklist and lessons.md.
3. Run scripts/check.sh.
4. Validate with a fresh validator: severity gate, at most 2 rounds, then ask the user.
5. Commit locally → update docs/progress.md "Resume here".
6. One user update per step boundary.
Agent replies ≤250 words; full reports in docs/reviews/.
Long data runs: concurrent workers, in the background.
```

---

## 6. Quick-start checklist for a new repo
- [ ] `docs/handoff/lessons.md` (start empty, grow it every round)
- [ ] `docs/handoff/step<N>.md` template
- [ ] `docs/reviews/` folder
- [ ] `scripts/check.sh`
- [ ] Agent files with `model:`, the self-check, and the 250-word report rule
- [ ] Validate-step skill with the severity gate and the 2-round cap
- [ ] `CLAUDE.md` workflow block plus a "Resume here" note in `docs/progress.md`
- [ ] A dry run and `--workers` on any long-running pipeline

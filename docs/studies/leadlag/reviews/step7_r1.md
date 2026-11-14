# Step 7 validation, round 1

## Verdict
PASS (no blockers, no majors; 4 minors).

## Checked (evidence)
- `bash scripts/check.sh`: run in full, CHECK: PASS (pytest, ruff, pairs rebuild, ingest dry-run).
- `python -m poly_actor.analysis report` re-run: `docs/findings.md` byte-identical (cmp), git tree clean afterwards.
- Read the whole generated findings.md against the checklist: headline equals the dashboard string; BTC published "Too early to tell" with the A29 reason, the literal "No head start" appears only in section 4 as post-hoc and "not a finding"; Fed "No head start" is stated as a bound (upper bound below the MDE, smaller leads not excluded); CPI 12 releases; recession descriptive; overnight tests read "moves with"; BTC-control tests marked biased and noted as still inside the exploratory BH family; Chart 2 CPI "0 of 20" design limit listed rather than redefined; disclaimer present. No "lead"/"first" claims anywhere.
- Diff 62424c3..HEAD of verdict.py, results.py, run.py: only labelling (XLU placebo row "Not valid" under A29, A29 note on all BTC Chart 1/2 panels, extra A29 exploratory test, code_commit in summary) plus a comment-only change in verdict.py. No statistic, rule or BH family change.
- `refresh --dry-run`: prints 4 stages in order, exit 0, git status unchanged. refresh.py logic read: non-zero code or exception or SystemExit stops the loop and names the stage. Tests (test_refresh.py) would fail if `return code` or the dry-run `continue` were removed (runner/boom assertions); read, not executed as mutations.
- test_findings.py: number-tracer has its own mutation test (invented number caught); template digit test has a negative test; rows 1, 4, 5 assert concrete strings. Row 7 test asserts the later stages never run.
- README: no verdicts or digits-as-results; run instructions match the CLIs. Carried minors: BTC Chart 2 note, XLU panel, spot-gap docstring, "undecided" tab label, softened Fed so-what: done in diff.

## Issues
- minor: findings.md section 4 (findings_template.txt:95-100) mentions "A29 addendum" but not addendum 2 (the BTC XLU placebo row changed from Passed to Not valid, post-hoc, user decision). The row itself shows "Not valid" + A29 note, but the post-hoc list is incomplete. Fix: add a bullet for addendum 2.
- minor: tests/test_findings.py `untraced_numbers` is permissive: a token passes if it matches ANY value in ANY results file, including rounding to 1 significant figure, so a wrong number that coincidentally rounds to some other value would pass. Tracing is by value, not by field. Acceptable for this step; stronger would be per-field assertions.
- minor: results JSON lives in git-ignored data/clean, so a public reader cannot verify the fingerprint/commit in findings section 6 without re-running the pipeline (and ingest data drifts over time). State this in the section, or commit a copy of the results.
- minor: I did not execute source mutations (read-only rule); mutation conclusions for refresh/headline tests are by inspection.

## Not checked
- Real-browser dashboard render (relied on main's report).
- Live ingest/align/analysis through `refresh` without --dry-run.
- Reproducibility of results JSON itself from raw data.

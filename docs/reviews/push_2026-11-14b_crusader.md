# Crusader review, push 2026-11-14b (origin/claude/fervent-mayer-k4klat..7b83fd3)

Scope: election report text/findings/app changes, tests, docs, screenshots. ruff clean. check.sh passed per caller (not re-run).

**Verdict: SHIP**

| Category | Score |
|---|---|
| Design/structure | 4 |
| Readability | 4 |
| Types | 4 |
| Error handling | 4 |
| Tests | 4 |
| Config/constants | 4 |
| Security | 5 |
| Performance | 5 |
| Consistency | 4 |
| Docs/hygiene | 4 |

## Blockers
None.

## Majors
None.

## Minors (5)
1. report_text.py `e1_chart` (~1049): `shift == 0` falls to "higher"; harmless but state "unchanged" or use `<= 0`-neutral wording.
2. report_text.py `amendments` docstring: summary line is a multi-line sentence; give a one-line summary, then detail. The A1-A3 prose is hard-coded in code; fine now, but move to a constant tuple if more amendments follow.
3. report_text.py `chart_texts` (~1129): the conditional-expression layout for odds/returns is hard to scan; use a small helper `_series_or_missing(kicker, builder, res, series)`.
4. tests/test_election_report.py: `"5.6% per 10 points lower"` and `"+1.1%"` assertions are coupled to the fixture bundle values; acceptable, but derive from `bundle.results` as the E1 test above already does for the findings check.
5. `test_methods_and_amendments_claim_only_what_was_done` bundles many concepts (one-concept-per-test); split into methods, amendments, and wording-regression tests.

## Good
- E1 chart text now has one source of truth with and without series; the findings no longer special-case "e1".
- E5 title is sign-aware, with a test covering both branches and the reversal case.
- Numbers in the amendments are traced to the bundle, and a test asserts `untraced_numbers == []`.
- The disclosure appears once in findings, which a test enforces; the app and the findings share `text.amendments`.
- Re-taken screenshots are smaller (net size down).

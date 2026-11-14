# Step 10 review, round 2 (diff 10ad6bf..7b83fd3)

Verdict: PASS. No blockers, no majors.

## Checked
- Major 1: findings.md E1 section now states the -5.56 shift (as 5.6), before-estimate +0.32, 90% range and "post hoc", all from `exploratory.e1`. `python -m poly_actor.election report` left git status clean (byte-identical). `test_findings_never_call_present_data_missing` asserts no "not in the results" and no `missing` block for non-series-only keys, so a present block reported missing fails it. tests/test_election_report.py passes.
- Major 2: no "surprise" in src, findings or README (only unrelated gamma.py comment). Replacement "fixed event window ... election-day close to the next close" matches the design. Test asserts the word is gone.
- Minors: A1-A3 listed on page and findings section 11; E5 title sign-aware (+1.1% vs -4.49); E2 so-what non-causal; MDE no longer beside the odds move; "wasted premium" and "simply noisier" gone from src/findings; E1 title and so-what agree and say post hoc.
- No stat computed in dashboard code (app.py change is one markdown line). `git diff 10ad6bf 7b83fd3 -- reports/` is empty. A3 drop-5 row p 0.492 matches bundle 0.4915.

## Issues
Minor:
1. `docs/election/preregistration.md:26` still says "wasted premium" (frozen document, likely correct to leave).
2. A3 text describes recomputed figures only qualitatively; acceptable but unverifiable from the bundle.
3. Screenshots not re-inspected.

## Not checked
Full test suite, visual QA, dark theme.

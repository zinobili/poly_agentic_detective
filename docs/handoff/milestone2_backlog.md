# Milestone 2 backlog (carried from milestone 1)

## From step 7 (docs/reviews/step7_r1.md)
- `tests/test_findings.py` `untraced_numbers`: a number passes if it matches any value in any results file, including 1-significant-figure rounding. Tighten to per-pair, per-field tracing.
- Findings section 6 fingerprints results JSON that lives in git-ignored `data/clean`; a public reader can't verify without re-running. Consider publishing the results JSON (or a hash manifest) with each release.
- Validator could not run source mutations (read-only); a builder should mutation-test the rules-as-examples tests.
- Not yet verified: a live (non-dry-run) `python -m poly_actor.refresh`, and that results reproduce from raw data end to end.

## From step 6/7 (research)
- BTC: re-specify the spot control with bar-aligned sub-hour spot data (each bar's own start and end), as a new pre-registered test.
- CPI Chart 2 signing window (all 20 releases unsigned; missing vs tiny moves not split).
- More CPI releases and recession episodes are needed before those pairs can be answered.

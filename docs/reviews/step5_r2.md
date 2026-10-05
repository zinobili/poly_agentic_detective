# Step 5 validator review, round 2

## Verdict
PASS. The r1 major (one ticker per xcorr/event_study) is fixed. No blockers or majors.

## Checked
- `scripts/check.sh`: 343 passed, ruff ok, pairs reproducible, dry-run ok.
- The contract is ticker-keyed (`contract.py` `_by_ticker`). Each ticker is parsed on its own, and bad entries are logged and skipped. A mixed TLT+XLU file keeps TLT.
- `_floats` rejects NaN/inf, and the band is checked via `_floats`. A bad slot becomes None, so the UI shows "Not run yet" and never "no link". A missing ticker gives "Not run yet" (`finding`, `so_what`).
- The picker (`st.radio`, default is the first ticker, i.e. the main one) drives charts 1-3, and chart 3 reads the same ticker. The label shows "(control)" for XLU, and the control good-news sentence is appended.
- The headline returns "Too early to tell for every pair so far" when all verdicts are too early.
- Minors: the forbidden list covers all 4 pair ids (the unit test iterates `_PAIR_INFO`), `.streamlit/config.toml` sets `address = "localhost"`, and streamlit is `<2` in both extras.
- Mutations, each caught:
  1. Removing the isfinite guard fails 4 parametrized load cases and the bad-ticker test.
  2. Disabling the control note fails the text test and the app test.
  3. Making one bad ticker drop all fails `test_one_bad_ticker_does_not_drop_the_others`.

## Adequacy of the Fed/XLU gap
Adequate. The Fed pair has no XLU, so the "XLU selected" row is covered at text level (`test_control_ticker_no_link_is_good_news`) and end to end on the bitcoin pair. The code path is pair-agnostic. The residual risk is that the Fed pair's controls (SPY, XLF) are not in `CONTROL_TICKERS`. That is a design question for step 6, not a defect.

## Issues
- minor: the headline is only guarded when every verdict is "Too early to tell". A mix of too-early and "No extra information" verdicts falls through to the old wording, which says "not moved ahead ... in any pair we tested". This is mild overclaiming. Not covered by a test.
- minor: `test_ticker_without_results_shows_not_run` uses a loose `count >= 1`.
- minor: the radio key is per pair, so the picker selection persists across reruns. If the available tickers change, Streamlit resets it. This is fine.
- carried to step 6 (as planned): the glossary's hard-coded parameters, the `components.html` deprecation, and the BTC 24/7 line breaks.

## Not checked
The live browser rendering and the visual layout. The panel data was not re-verified (out of scope).

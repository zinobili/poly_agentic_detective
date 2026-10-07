# Step 7 hand-off (write-up)

Plan to be written at step start. Carried-over items below.

## Carried-over items

### From step 6 (docs/reviews/step6_r2.md, step6_r1.md m8)
- BTC Chart 2 is residualised on the same misaligned spot control and has no A29 note. Add the note (no suppressor bias, since there is no odds term, but the control is still misaligned).
- `_spot_gap`, the BTC overnight spot-control test (r1 m8) and the XLU residualised panel have no A29 note.
- CPI Chart 2: all 20 releases are unsigned (10 have a missing odds reading in the signing bar, 10 move < 0.005 pp; the signing bar is ~17 h before the release). Design flaw, not a code bug. Any re-definition of the signing window must be a dated amendment labelled post-hoc.
- BH-rejected overnight exploratory tests (fed_overnight_TLT, btc_overnight_IBIT) read as "moves with", never as timing claims, in the write-up.
- Fed so-what wording is slightly strong next to Low confidence; soften.
- Biased BTC exploratory p-values (COIN/MSTR/IBIT lag tests) still sit in the exploratory BH family; say so wherever the family is reported.
- No real-browser render was checked by the validator; check the dashboard in a browser on the real results.

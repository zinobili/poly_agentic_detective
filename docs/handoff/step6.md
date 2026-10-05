# Step 6 hand-off (analysis)

Plan to be written at the start of step 6. Step 6 writes `data/clean/results/<pair_id>.json` in the ticker-keyed contract of `src/poly_actor/dashboard/contract.py` (see `docs/handoff/step5.md`, Round 2).

## Carried over from step 4 (docs/reviews/step4_r2.md)
- **m3:** PM prices on lead-lag rows are ~10 min stale (median ~593 s). State it, and read lag 0 / lag 1 with that in mind.
- **m4:** quotes up to 3 h old still enter `both_trading` (97 BTC rows > 1500 s). Pre-register a max-age cut-off before looking at results.

## Carried over from step 5 (docs/reviews/step5_r1.md, step5_r2.md)
- The glossary hard-codes analysis parameters (lags ±12, 2 SD, "0.1 to 0.2 is notable"). Step 6 writes the real parameters into the contract, and the glossary reads them from there.
- `components.html` is deprecated in Streamlit. Replace it.
- The BTC-USD line in chart 3 breaks overnight although it trades 24/7. Use the gap rule per asset.
- `text.headline`: a mix of "Too early to tell" and "No extra information" verdicts still says "not moved ahead in any pair" (slight overclaim; untested).
- `test_ticker_without_results_shows_not_run` uses a loose `count >= 1`.
- The picker state resets when the ticker set changes (harmless).
- Design question: which tickers count as controls. Only `CONTROL_TICKERS` get the "(control)" label; SPY/XLF in the Fed pair do not.
- Not yet looked at in a real browser: the sticky pair tabs and the scroll-on-card-click.

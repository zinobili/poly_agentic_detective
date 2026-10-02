# Dashboard UX: design reference for steps 5–7

Agreed with the user on 2026-10-03. The reference mockup is [dashboard_mockup.html](dashboard_mockup.html). Open it in a browser. **Its data is made up**, and its verdicts, confidence levels and checklists are written by hand.

**Audience:** a lay reader who is smart but doesn't know what log-odds, correlation, Granger causality, event studies or p-values are. They should come away with an answer, not a set of charts.

## Page structure (top to bottom)
1. **Banner** (only while any number is a placeholder): "Made-up numbers".
2. **Headline answer:** the cross-pair verdict in one sentence. Below it, the question in plain words and a tally, e.g. "1 leads, 2 no head start, 1 needs data".
3. **Scorecard:** one card per pair. Each card has a plain question, a verdict badge, a one-sentence finding, a confidence meter and a "See the evidence →" link. Clicking a card opens that pair's evidence.
4. **What counts as evidence:** a "Counts" list, a "Doesn't count" list, and a panel saying that "no head start" is a result too.
5. **Pair evidence:**
   - A verdict panel with the finding as its title, a "so what", the confidence level with its reason, and a 5-row pass/fail checklist.
   - Ticker chips, each with a plain name, e.g. "TLT long-term bonds", "XLU utilities, control".
   - Chart 1, "Who moves first?" (cross-correlation).
   - Chart 2, "What happens after a big odds jump?" (event study).
   - Chart 3, the raw data. It goes last and is labelled as context only. It uses two stacked panels on a shared timeline, never a chart with two y-axes.
6. **Glossary** (collapsed): each plain term mapped to its technical term.

## Navigation
- Once the scorecard scrolls off screen, a compact tab bar stays fixed at the top. Each tab shows a short name and a short verdict. Below 480px, tabs show the name only.
- Clicking a tab keeps you where you are: the section you're looking at stays in the same place on screen.
- Clicking a big scorecard card scrolls you down to that pair's evidence.

## Rules (input → expected output)

**Every chart has four parts:** a kicker question, an action title computed from the results, a "How to read" line, and a "So what" line. A collapsed "For experts" note holds the technical definition and the numbers.
- Peak correlation at lag +2 h, with that lag and the next one both outside the noise band → title "Fed odds tend to move about 2 hours before TLT (long-term bonds)".
- Peak at lag 0 → "Recession odds and SPY (S&P 500) move in the same hour, so neither gets a head start".
- All lags inside the noise band → "No clear timing link between … and …: every bar sits in the noise zone". The "so what" says "That's a valid result, not a failure."

**A single spike is not a link.**
- One bar outside the noise band, with both neighbours inside it → no clear link, and the title says "only isolated bars poke out, which is likely luck". (This is a simplification from the UX review. Step 6/7 must confirm or replace it with the real test.)
- The peak bar plus an adjacent bar, both outside the band with the same sign → a clear link.

**Plain language first, jargon second.**
- "Granger causality, BH-adjusted p = 0.012" → shown as "✓ Passed: Odds help predict prices beyond their own past". The test name and p-value go underneath in small mono text.
- "Expected change (bp)" → shown as "Expected Fed rate change", formatted "−0.18 pts".
- `fed_decision`, `config/pairs.yaml`, CLI commands and step numbers → never shown to the reader.

**Confidence is a word and a meter, never only a p-value.**
- Levels are Not enough data, Low, Medium and High, each with a one-sentence reason.
- Example: all tests pass but the data covers only 2 FOMC meetings → Medium, "We'd need a longer history before calling it high."
- Example: 2 CPI releases → "Not enough data". Its charts are titled as previews, not results.

**Verdict labels:**
- "Polymarket moves first"
- "Moves at the same time"
- "No extra information" (the Bitcoin pair: no edge over BTC spot)
- "Too early to tell"

The control asset (XLU) showing no link is presented as good news for the method.

## Open items for step 7 (must be computed, not hand-written)
- The rules that map test results to a verdict label and to a confidence level, e.g. minimum event counts (the mockup uses 30+ events, or 12+ for CPI releases), placebo pass, and many-pairs correction pass.
- The rules for each checklist row's status: Passed, Failed, Weak, Not needed or Not run.
- Whether the "lone bar = luck" rule holds or is replaced by the formal test.
- The headline sentence and the tally are generated from the per-pair verdicts.

## Implementation notes for step 5 (Streamlit + Plotly)
- The mockup is plain HTML and SVG. The real dashboard is planned as Streamlit, so the layout and wording carry over even if the visual details don't. In Streamlit, one way to get the persistent tabs is a top `st.tabs` or segmented control, with page state held in `st.session_state` so switching pairs doesn't reset the scroll position.
- Chart titles and "so what" text come from functions of the analysis results, with unit tests in the input → output style above.
- Background: the v1 mockup was criticised as "data bragging": graphs without meaning, a dual-axis overlay chart first, and the verdict buried at the bottom. The full audit table of that version is summarised by the rules above.

# Step 10 build report: election presentation and generated findings (milestone 2)

Builder, 2026-11-14. No statistics were added and no method changed. Everything shown is read
from `reports/election/results.json` and `reports/election/series/*.csv`. Not committed.
`analysis*.py`, `panel.py`, `ingest.py`, the bundle, the pre-registration and every milestone-1
module are untouched.

## What was built
| File | Role |
|---|---|
| `src/poly_actor/election/report_load.py` | Read-only bundle loader (`Bundle`, `load_bundle`, cache signature). Folder override: `POLY_ACTOR_ELECTION_BUNDLE`. |
| `src/poly_actor/election/report_text.py` | Every word: headline, cards, "what this means for an AI book", checklist lines, the four parts of each of 14 chart blocks, robustness and window tables, methods, limits, disclosure, glossary. Pure functions of the results. |
| `src/poly_actor/election/charts.py` | 14 Plotly builders, light and dark palettes, one y-axis per panel. |
| `src/poly_actor/election/app.py` | Streamlit layout only. Reuses `poly_actor.dashboard.style.page_css`. |
| `src/poly_actor/election/findings.py`, `findings_template.txt` | `docs/election/findings.md` generator; the template holds no digits except section numbers and ids. |
| `src/poly_actor/election/cli.py` | `report` subcommand added (additive), plus typed args. |
| `tests/test_election_report.py`, `tests/fixtures/election/bundle/` | 23 offline test functions (24 cases) on a 140 KB fixture bundle (the real bundle, per-ticker coverage dropped, long series thinned). |
| `docs/election/findings.md` | Generated (230 lines). |
| `README.md`, `.claude/launch.json`, `pyproject.toml` | Milestone-2 section with one screenshot and no typed result numbers; `election` and `election-linux` launch entries (port 8502); template added to package data. |

Run:
```bash
.venv/bin/streamlit run src/poly_actor/election/app.py
.venv/bin/python -m poly_actor.election report
```

## How the nulls are presented
- Title: "Too noisy to tell whether AI stocks carried a partisan beta, and pre-election betas did
  not predict election night". It is built only from the two pre-registered verdict labels. The
  bundle's own `headline.sentence` sits under it in small mono type.
- A panel "What this means for an AI book going into an election" follows the verdicts: no
  measured beta to size a hedge on; that is not the same as no exposure (the detectable effect is
  stated next to the size of the election-night odds move, with no arithmetic between them); the
  non-AI basket is tightly bounded; betas did not rank the night or other large-odds days; and
  one descriptive line on the night's mean abnormal returns.
- The H1 chart draws each 90% range over a grey bar of ±MDE, so "too small to detect" is visible.
- H2's negative correlation and its two-sided p appear once, in a warning box that starts
  "Exploratory, not a finding" and names the three reasons (opposite tail, one night,
  uncorrected). A test checks that the value appears once on the page and once in findings.md,
  and nowhere in a title, card, checklist line or expert note.
- H3 carries "Descriptive only: one night, and the futures path was seen before the plan was
  frozen" in the section caption and in both blocks. E1, E2, E3 and E5 carry an "Exploratory" tag
  and their so-what starts with that word. E4 rows are marked in the robustness table.

## Verification
- Headless browser (Playwright, Chromium) on the real bundle: HTTP 200, 14 Plotly charts, 0
  Streamlit exception boxes, 0 page errors, nothing in the server log, light and dark.
- Tests: the eight rules-as-examples rows, plus title-never-exceeds-verdict, missing parts,
  figure values, one y-axis per panel, ET clock on the night chart. The number tracer has a
  mutation check (an invented number is caught), and the committed findings.md is compared
  byte for byte with a fresh render of the published bundle.
- `findings.md` regenerates byte-identically (same sha256 on two runs).
- `bash scripts/check.sh`: **PASS** (582 passed, 1 skipped; ruff check and format ok; the pairs rebuild and ingest dry run skip because this container has no raw data).

## Screenshots (`docs/images/election/`, deviceScaleFactor 2, 1360 px wide)
`full-page.png`, `01-answer.png`, `02-setup.png`, `03-h1.png`, `04-h5.png`, `05-h2.png`,
`06-h3.png`, `07-h4.png`, `08-derivatives.png`, `09-exploratory.png`, `10-method.png`, and one
dark-theme sample `05-h2-dark.png`. Total about 10.5 MB; `full-page.png` alone is 5.5 MB (main later halved and palette-compressed the section images to ~1.8 MB and kept full-page.png out of git). Main
may want to drop or downscale it before a push.

## Not in the bundle (not computed here, not shown as numbers)
Nothing on the page falls back to "not in the results" on the real bundle. These were wanted and
left out because the bundle does not carry them:
1. The equal-weight AI composite's raw return on 4 Nov (quoted in the step 9 report). The page
   uses the bundle's mean abnormal returns instead.
2. The number of eligible days in H2b (the 205 of amendment A2). The tie rule is described in
   words.
3. The election-night window's clock times and bar length. Written in words ("five-minute",
   "evening window"); the chart axis shows the clock.
4. An MDE for H2 (what rank correlation was detectable with 29 names). Only H1 has one.
5. `meta.preregistration` still reads "amendment A1" although A2 exists. The string is not shown.

## Deviations from the hand-off
1. The page title is the plain-language headline; `headline.sentence` is shown beneath it, not as
   the title, because it is technical ("b = ..., MDE80 = ...").
2. Checklist rows take status and plain wording from the bundle, but the small technical line is
   formatted here from the bundle's numbers. The bundle's `technical` strings carry unrounded
   floats and repeat the two-sided p.
3. The logit robustness row is labelled "per +0.1 log-odds", which is what the stored `b10_pct`
   is. No rescaling is done.
4. Charts A and B are two charts with the same time axis, not one stacked figure. H3 and E2 use
   stacked panels. The derivatives section leads with implied against realised.
5. The number tracer accepts numbers in the bundle's keys and strings (`ci90`, `MDE80`,
   `band_max_abs_t_95`), a value x100 (a share printed as percent or points), and skips the index
   names "S&P 500", "Nasdaq-100" and "Russell 2000". Three titles built from chart series (odds,
   cumulative returns, the E1 range) are on the page but not in findings.md, which reads
   `results.json` only.
6. No pytest starts a real server (tests may not open sockets beyond localhost and the suite
   stays fast). Row 8 is covered by AppTest on the real bundle plus the manual headless run.
7. `.claude/launch.json` has two new entries, `election` (Windows path, as the existing one) and
   `election-linux`.

## Carried-over minors (crusader 2026-11-13b)
- Fixed: `cli.py` untyped `args`/`cfg`; `config.py` `d: dict`, `raw: dict` and a class docstring
  for `ElectionConfig`; `coverage.py` bare `dict` returns. The stray `noqa` in `coverage.py` was
  already gone.
- Deferred, because the files are frozen while the validator reviews steps 8 and 9: `panel.py`
  (unused `SESSION_FIELDS`, lazy `coverage` import, `idxmax`, non-atomic clean writes) and
  `ingest.py` (retry constants, `noqa: BLE001`, `failures`/`now` types). `cmd_panel` reading
  `cov['tables']` is left as is.

## For the validator and main
- If the bundle is republished, re-run `python -m poly_actor.election report`: findings.md carries
  a fingerprint of `results.json`, and a test fails until it is regenerated.
- Observation, not changed: the first odds reading (2025-07-18) is a 0.50 opening print and the
  next is 0.29, so the first session of the H1 sample has the largest odds change in it. The
  "without the largest odds-move days" robustness row already drops that day. The odds chart
  title starts from the first H1 session for this reason.
- The H3 lag chart colours a bar when its 90% range excludes zero. That is a look-up on the
  bundle's interval, not a test, and the title says it is not evidence of an ordering.

## Self-check against the checklist and lessons
1. Renders every section on the real bundle with no error; screenshots saved. Done.
2. Tests pass offline; findings.md byte-identical. Done.
3. No overclaiming: titles are functions of the verdicts (tested with a positive estimate under a
   null verdict). H3 and E blocks labelled. Done.
4. README section with run commands and one screenshot, no typed result numbers. Done.
5. launch.json `election`. Done.
6. Lessons: headlines come from the pre-registered verdicts only (tested: emptying the
   exploratory and robustness trees leaves the headline, cards and takeaways unchanged); UTC is
   kept in the data and converted to ET with zoneinfo only for display; no network in tests.

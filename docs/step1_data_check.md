# Step 1 — Data check

Research spike (not production code). Run with:

```
.venv/Scripts/python.exe notebooks/step1_data_check.py
```

Outputs: `notebooks/step1_data_check.html` (chart), raw API dumps under
`data/scratch/step1/*.json|csv` (git-ignored; scratch evidence for this spike,
kept out of `data/raw/` which CLAUDE.md reserves for the real ingestion
pipeline's immutable output). Two inline self-tests
(`_self_test_clip_lookahead`, `_self_test_restamp_to_bar_end`, both pure
functions, no network) run automatically at the top of `main()` and assert
the look-ahead guard and the bar-end re-stamping logic described below are
correct.

**Note on `data/raw/step1` vs `data/scratch/step1` (transparency under the
"never delete `data/raw/`" rule):** this spike's dumps were originally
written to `data/raw/step1/` by mistake. They were subsequently **moved**
(not deleted — every file's content was preserved, just relocated) to
`data/scratch/step1/`, since `data/raw/` is reserved under CLAUDE.md for the
immutable output of the real ingestion pipeline (`src/poly_actor/ingest/`),
not throwaway research-spike scratch dumps. Nothing under `data/raw/` was
ever deleted; `data/raw/` itself still exists and is used by other
concurrent work (step 2's pair discovery dumps). Flagging this explicitly
since "move files that were briefly under `data/raw/`" is adjacent enough to
the immutability rule's intent that it deserves a paper trail rather than a
silent `mv`.

All numbers below are from an actual run on 2026-10-01 (re-validated after
two rounds of validator feedback); re-running later will shift the exact
timestamps/counts but the qualitative findings (limits, quirks) should hold.

## Markets used

| Role | Event slug | Submarket slug | Yes token id | Status |
|---|---|---|---|---|
| ACTIVE | `fed-decision-in-october-20260617190323537` | `will-there-be-no-change-in-fed-interest-rates-after-the-october-2026-meeting-20260617190324031` | `111061902544814266207267295505639408607400625795891618462682726460921782993748` | open, Oct 2026 FOMC meeting |
| RESOLVED | `fed-decision-in-september` | `fed-decreases-interest-rates-by-25-bps-after-september-2025-meeting` | `56831000532202254811410354120402056896323359630546371545035370679912675847818` | closed, resolved YES (25bps cut), Sep 2025 FOMC meeting |

Found via Gamma: `GET /events?tag_slug=fed-rates&closed=false` (browsed for
the current FOMC-series event) and a direct `GET /events?slug=fed-decision-in-september`
lookup for the resolved one. Free-text `search=` on `/events` was unreliable —
it returned unrelated sports/politics markets for queries like "Fed decision",
so slug/tag-based lookup was used instead (see "Surprises" below).

## 1. Polymarket CLOB `prices-history`

### 1a. LOOK-AHEAD LEAK (critical — read this first)

**When called with explicit `startTs`/`endTs` on an ACTIVE (not yet resolved)
market, the API appends one extra point stamped at the current wall-clock
time, after `endTs`.** Reproduced directly (see script section 3, raw dumps
`clob_active_lookahead_repro_fid1.json` / `_fid60.json`):

```
GET /prices-history?market=<ACTIVE Yes token>&startTs=2026-07-01T00:00Z
    &endTs=2026-07-15T00:00Z&fidelity=1
```
- Last real point in range: `2026-07-14T23:59:05Z, p=0.58`
- Followed by an extra point: `2026-10-01T09:58:11Z, p=0.635` ← this is
  **"now"** (the time the request was made), far outside the requested
  window — a textbook look-ahead leak if ingested naively.
- Same leak at `fidelity=60`: last real point `2026-07-14T23:00:06Z`,
  followed by the same current-time point.
- **The RESOLVED market does not do this.** Explicit-window requests against
  it return only points inside `[startTs, endTs]`, as expected.

**Fix, implemented in the script:** `parse_clob_history(body, start_ts=...,
end_ts=...)` drops every point with `t < start_ts` or `t > end_ts` whenever
the caller supplies those bounds. Verified by an inline test
(`_self_test_clip_lookahead`, pure function, no network) that runs at the top
of `main()` and asserts: (a) a synthetic out-of-range point before `start_ts`
is dropped, (b) a synthetic look-ahead point after `end_ts` is dropped, and
(c) calling the parser *without* bounds does NOT drop anything (proving the
guard is opt-in and explicit, not silently hiding data in other contexts e.g.
`interval=max`, which has no bounds to clip against and by construction
returns data ending "now" anyway).

**Step 3 ingestion requirement:** any CLOB ingestion code that uses explicit
`startTs`/`endTs` MUST clip the response to `[startTs, endTs]` before storing
or using it, for ACTIVE markets in particular. Treat this as a hard rule, not
an edge case — it will silently inject a future/current price into historical
data otherwise.

### 1b. Fidelity, history depth, gaps

| Endpoint / mode | Finest fidelity returned | History depth | Gaps (tolerance-based, see 1c) | Timestamp format/tz | Max range per request |
|---|---|---|---|---|---|
| `interval=max`, ACTIVE market | Requested `fidelity=1` or `5` both actually returned **10-minute** spacing (median delta 600s); only `fidelity=60` genuinely gives hourly and `fidelity=720` genuinely gives 12-hourly | `fid=1/5`: 30.0 days back (4314 pts). `fid=60`: 30.0 days (720 pts). `fid=720`: **104.9 days** back (211 pts) | At `fid=1/5`: only 3/4314 deltas exceed 1.5× the median (the data is genuinely clean at its true ~10-min cadence — see 1c for why an earlier fixed-600s-threshold reading of "41% gaps" was wrong) | `t`: unix seconds (UTC by construction), `p`: probability 0–1 | n/a (interval=max, server picks window) |
| `interval=max`, RESOLVED market | `fid=1/5/60` all returned **0 points** (empty); only `fid=720` returned data | `fid=720`: full market lifetime, 132.5 days (266 pts) | none at 12h resolution | same as above | n/a |
| Explicit `startTs`/`endTs`, **fidelity=1, 14-day chunk, EARLY in a resolved market's life** (2025-06-01→06-14, not just near resolution) | **Genuinely 1-minute** (median delta 60s) | 18710 points over 13.0 days | 7/18710 deltas exceed tolerance — essentially clean | same | See below |
| Explicit `startTs`/`endTs`, **fidelity=1, 14-day chunk, ACTIVE market mid-life** (2026-07-01→07-15, clipped per 1a) | **Genuinely 1-minute** (median delta 60s) | 20067 points over 14.0 days | 7/20067 deltas exceed tolerance — clean | same | See below |
| Explicit `startTs`/`endTs` range-length probe | — | — | — | — | **15 days OK, 16+ days → HTTP 400** `"invalid filters: 'startTs' and 'endTs' interval is too long"` — confirmed at **both `fidelity=1` and `fidelity=60`** (a 30-day window at `fidelity=60` also 400s; the 15-day cap is not fidelity-dependent, at least not between 1 and 60) |

Key findings:
- **`interval=max` does not reliably give the finest fidelity.** For the
  ACTIVE market, requesting `fidelity=1` or `fidelity=5` with `interval=max`
  both silently returned ~10-minute-spaced points (not 1- or 5-minute) over a
  30-day window. For the RESOLVED market, `interval=max` with any fidelity
  finer than 720 returned **zero** points. The server appears to pick an
  effective bucket size based on data volume/age rather than honoring the
  requested fidelity when `interval=max` is used.
- **To actually get 1-minute resolution, you must pass explicit `startTs`/`endTs`**
  (not `interval=max`), **and clip the result for the look-ahead leak (1a)**.
  The window is capped at **15 days** per request, confirmed at both
  `fidelity=1` and `fidelity=60`.
- **Fine-grained (1-minute) data is available across a market's WHOLE life,
  not just near resolution.** Confirmed by pulling a 14-day chunk from early
  June 2025 (market created May 2025, resolved September 2025) and getting
  genuinely 1-minute data (18710 points, clean). Equally confirmed for the
  ACTIVE market's mid-life (July 2026, 20067 points, clean). This directly
  contradicts an earlier draft of this document, which incorrectly concluded
  fine data was only available in the most recent ~30 days — that was an
  artifact of only testing `interval=max`, which silently coarsens, not of
  any real data gap.
- **Timestamps**: unix epoch seconds (`t`), inherently UTC, no tz field.
  Converted with `pd.to_datetime(df["t"], unit="s", utc=True)`.
- **Rate limiting**: no 429s observed under light polling (~0.4s sleep between
  calls, ~40 CLOB calls total in this run). Retry/backoff code is in place as
  a precaution but was never exercised. This is not strong evidence of the
  real rate limit — just that we didn't hit it at this call volume.
- **Gamma `search=` is unreliable** as a discovery mechanism (free-text search
  returned off-topic results); `tag_slug=`/`slug=` lookups worked reliably
  and are used in the script.

### 1c. Gap-detection artifact (fixed)

The first draft of this spike flagged "41% of points have gaps >10 minutes"
on the ACTIVE market's `interval=max, fidelity=1` series. That was wrong: the
series' *true* cadence there is ~600s (10 minutes, per finding 1b above, not
1 minute), so a fixed 600-second threshold flags roughly half of normal
~601-602s polling jitter as a "gap." `describe_gaps()` now uses a tolerance
of **1.5× the series' own median spacing** instead of a fixed threshold; on
the same data this correctly reports only 3/4314 points as gaps. Always use
a cadence-relative tolerance, not an absolute one, when a series' true
resolution isn't already known.

## 2. yfinance — TLT / SPY

### 2a. `period=` is in TRADING days, not calendar days (surprise, now explained)

An earlier draft of this doc reported "730d gives ~1064 calendar days of
history" as a yfinance quirk/cap change. That was a misreading. Confirmed
directly:

| Request | Rows | Distinct trading days | Calendar span |
|---|---|---|---|
| `period="60d"`, `interval="1h"` | 420 | **60** | **84** days |
| `period="730d"`, `interval="1h"` | 5074 | **730** | **1064** days |

`period=` for intraday intervals counts **trading days**, not calendar days —
60 trading days naturally spans ~84 calendar days (5 trading days/week), and
730 trading days spans ~1064 calendar days (≈ 2.9 calendar years). This is
expected, documented Yahoo/yfinance behavior, not a looser-than-expected cap.

**The actual calendar-day cap is enforced on explicit `start=`/`end=`
requests**, and is **730 calendar days**, confirmed directly:
```
yf.Ticker("TLT").history(start=<800 calendar days ago>, interval="1h")
-> 0 rows, yfinance prints:
   "1h data not available for startTime=...: The requested range must be
    within the last 730 days."
```

**Step 3 ingestion requirement:** incremental ingestion using explicit
`start=` pulls for 1h bars cannot reach back more than 730 **calendar** days
from "now" — plan backfill chunking (or accept a hard floor) accordingly.
`period="730d"` is a convenient shorthand that happens to span ~1064 calendar
days because it counts trading days, but an explicit `start=` 1064 days back
would fail; only `start=` ≤730 calendar days back is guaranteed to work.

### 2b. Full results table

| Ticker | Interval | Requested period | Rows | Index tz | Trading days / calendar span | Gaps | Extended hours? |
|---|---|---|---|---|---|---|---|
| TLT | 1h | `730d` | 5074 | `America/New_York` (NOT UTC) | 730 trading days / 1064 calendar days (2023-11-01 → 2026-09-30) | 729 overnight/weekend jumps (expected); intraday deltas mostly 3600s, plus a handful of 14400s — these come from the 2026-02-02 missing-bar data gap (§2c), NOT early closes (confirmed: all 7 known early-close dates in range have exactly 3 bars each, no anomalous deltas) | No — bars run 09:30–15:30 ET on regular days, 09:30–11:30 on early closes, no pre/post-market bars |
| SPY | 1h | `730d` | 5072 | `America/New_York` | 730 trading days / 1064 calendar days | 729 overnight/weekend jumps; intraday deltas uniformly 3600s | No |
| TLT | 1h | `60d` (sanity check) | 420 | `America/New_York` | 60 trading days / 84 calendar days | 59 overnight/weekend jumps | No |
| TLT | 1h | explicit `start=` 800 calendar days back | 0 (fails) | — | — | — | — |
| TLT | 1m | `8d` (single request) | 3120 | `America/New_York` | 8 trading days / 9 calendar days | 7 overnight/weekend jumps; intraday delta uniformly 60s | No |
| SPY | 1m | `8d` | 3120 | `America/New_York` | 8 trading days / 9 calendar days | 7 gaps | No |
| TLT | 1m | `30d` single request | 0 (fails, silently) | — | — | — | — |

Key findings:
- **Index is `America/New_York`, not UTC.** Every value must go through
  `.tz_convert("UTC")` before joining with Polymarket data.
- **Bars are labelled by their START time, not end time** (see §2c).
- **1-minute bars**: confirmed max **8 days per single request** and **30-day
  total lookback** (both produce explicit, catchable error strings from
  yfinance — `period="30d"` returned 0 rows silently, but an explicit
  `start=/end=` 31-days-back request printed `"must be within the last 30
  days"`). To assemble a full 30-day 1m history you need ~4 chunked 8-day
  requests.
- No extended-hours (pre/post-market) bars at either interval — only regular
  09:30–16:00 ET session, confirmed by the ~6.5h/day, 7-bars/day pattern.
- No rate-limit errors observed; no explicit backoff was needed for this
  volume of yfinance calls, but the script still sleeps briefly between calls.

### 2c. Bar timestamps are START-labelled, and the daily bar count is NOT always 7 (step 4 requirement)

Corrected from an earlier draft of this doc, which incorrectly claimed "every
observed trading day has exactly 7 hourly bars." Confirmed directly, three
distinct patterns exist in the pulled 730-trading-day window:
- **Regular sessions** (most days): exactly **7** hourly bars, timestamps
  `09:30, 10:30, 11:30, 12:30, 13:30, 14:30, 15:30` (ET).
- **Early closes / half days** (7 known dates in range: 2023-11-24,
  2024-07-03, 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24):
  exactly **3** hourly bars, `09:30, 10:30, 11:30` — confirmed by direct
  count on the raw CSV, all 7 dates show exactly 3 bars, none flagged as a
  data gap.
- **Real data-gap days** (2 found in the pulled window): `2026-01-30` (only
  2 bars: `09:30, 10:30`; the 10:30 bar's 229k volume suggests the feed was cut
  off mid-morning) and `2026-02-02` (4 rows: a `09:30` row that is **all-NaN
  with volume 0**, then `13:30, 14:30, 15:30`; 10:30–12:30 are absent; the 13:30
  bar's 8.6M volume suggests Yahoo merged the morning into it). These are
  genuinely missing bars in the yfinance feed, not early closes (both are
  regular NYSE sessions per the XNYS calendar). **Step 4 must drop or flag rows
  with NaN OHLC before alignment.** The step-1 script does not drop them.

In all cases, the `09:30` bar's timestamp is the bar's **start** — its close
price isn't knowable until `10:30`. On a regular day the last bar (`15:30`)
is only 30 minutes long (`15:30`–`16:00`, the close); on an early close the
last bar (`11:30`) is **90 minutes** long (`11:30`–`13:00`, the close) — NOT
30 minutes, a distinction an earlier draft of `restamp_to_bar_end` got wrong
(see below).

This matters for alignment: comparing a Polymarket "as of t" probability to a
yfinance bar using the bar's *start* timestamp would let the bar's close
price "be available" up to an hour (or more, on an early close) before it
actually was — a look-ahead bug of the same family as §1a, just on the stock
side.

**Fix, implemented in the script and applied in the chart:**
`restamp_to_bar_end(df)` re-stamps each bar's index to its END time using the
REAL NYSE (XNYS) session close for that date, via the `exchange_calendars`
package, not a hardcoded close time or a "next bar's start" heuristic:
- The **last bar observed for a given date** is stamped to that date's actual
  session close (`exchange_calendars` `XNYS` calendar) — correctly giving a
  30-minute last bar on a regular day and a 90-minute last bar on an early
  close.
- **Every other bar** is stamped to `start + 60 minutes` (capped at the
  session close, which in practice never binds for a non-last bar). This
  deliberately does NOT look at "what's the next bar's actual start" —
  earlier drafts used that rule, which breaks on a day with a missing
  mid-day bar (e.g. `2026-02-02`: the `09:30` bar's next *observed* bar is
  hours later, and stamping to that would leak hours into the future).

`restamp_to_bar_end` also returns a list of **gap days**: dates with fewer
bars than expected after accounting for early closes (3 expected on a half
day, 7 otherwise) — currently `2026-01-30` and `2026-02-02` in the pulled
window. These are reported, not silently smoothed over, because the last bar
of a gap day gets stamped to the session close by the rule above and so can
end up covering an unusually long span (e.g. `2026-01-30`'s 10:30 bar is
stamped 16:00: late, never early, so no leak). Callers should treat gap days
with caution rather than trust them at face value. Validator round 3
confirmed every end stamp is at or after the true bar end. It also confirmed
the "session ≤ 5h" early-close heuristic matches `cal.early_closes` exactly
over 2023-11 to 2026-09; production code should use `cal.early_closes` directly.

An inline self-test (`_self_test_restamp_to_bar_end`, no network, uses
`exchange_calendars` directly) checks all of the above on synthetic data:
a regular day, a `2025-11-28`-style early close, and a `2026-02-02`-style
missing-mid-day-bar day, and runs automatically at the top of `main()`.

Verified in the chart run: the last TLT point of September moved from
`2026-09-30 19:30 UTC` (start-stamped, i.e. 15:30 ET) to `2026-09-30 20:00
UTC` (end-stamped, i.e. 16:00 ET close) after applying `restamp_to_bar_end`.

**Step 4 (alignment) requirement:** always re-stamp yfinance intraday bars to
bar-END time before aligning with any other "as of t" series (Polymarket
probabilities, news timestamps, etc.), using the calendar-based rule above
(last bar of day → real session close via `exchange_calendars`; every other
bar → `start + 60min`) — not a fixed `+1h`, not a hardcoded `+30min` for the
last bar, and not a "next observed bar's start" rule (breaks on gap days).

## 3. Chart

`notebooks/step1_data_check.html` — ACTIVE market ("No change" submarket, Yes
probability, hourly via `fidelity=60`/`interval=max`) vs TLT 1h close
(re-stamped to bar-end time per §2c), both converted to and plotted on a
shared **UTC** x-axis, dual y-axes (probability 0–1 on the left, TLT USD on
the right). Overlap window used: 2026-09-01 11:00 UTC → 2026-09-30 20:00 UTC
(704 probability points, 147 TLT points — exact counts drift slightly run to
run since both are live feeds).

**Why the point counts differ (~700 vs 147) — this is expected, not a data
quality issue:** Polymarket trades around the clock (crypto-style, no market
hours), so at hourly fidelity it can have up to 24 points/day, 7 days/week.
TLT only trades during the regular NYSE session (09:30–16:00 ET, ~7
hourly bars/day) on the ~5 trading days/week the market is open. ~704 ≈ 30
days × ~23.5 pts/day (minus the illiquid stretches coarsened to the
`interval=max` server-side bucket); 147 ≈ 21 trading days in September × 7
bars/day.

## Recommendation: is hourly lead-lag analysis feasible?

**Yes — hourly (or finer) lead-lag analysis is feasible across a Fed market's
entire life, both while active and after resolution, as long as ingestion
chunks CLOB `prices-history` requests correctly.** This supersedes an earlier,
overly pessimistic draft of this recommendation, which incorrectly claimed
fine data was only available in the most recent ~30 days of an active market
or the last few weeks before a resolved market's resolution — that
conclusion was an artifact of testing only `interval=max` (§1b); explicit
`startTs`/`endTs` chunking gives genuine 1-minute data for any 15-day window
anywhere in a market's life, both active and resolved (§1b, confirmed with a
chunk from early in each market's life).

- **CLOB side**: chunk every pull into ≤15-day windows with explicit
  `startTs`/`endTs`, at `fidelity=1` (or `fidelity=60` if latency/volume
  matters more than the ability to self-verify the API's effective
  granularity — both fidelities share the same 15-day cap). **Always clip the
  parsed result to `[startTs, endTs]`** to avoid the look-ahead leak (§1a) —
  this is non-negotiable for ACTIVE markets. A typical 4-month FOMC market
  needs ~9 chunked requests to cover its full life.
- **Chunk-boundary behavior is inconsistent; don't rely on it.** The builder
  and the validator got conflicting results, and validator round 3 re-tested
  exact-boundary windows on both markets (fidelity=1):
  - Resolved `[t0, t1]` (2 adjacent points) → empty.
  - Resolved `[t0-120, t0]` → both ends included.
  - Active `[t0, t1]` → only t1 (start excluded) plus the live point.
  - Active `[t0-120, t0]` → end included.

  The server appears to bucket requests rather than apply a clean interval.
  **Step 3 rule:** clip on the client to half-open `[start, end)`, tile chunks
  back to back, and **de-duplicate on `t`** after concatenating. Never assume
  the server's boundary semantics.
- **Stock side**: yfinance 1h bars are reliably available for the full
  observed market lifetimes tested here (FOMC markets run weeks to ~4-5
  months; yfinance 1h goes back up to 730 calendar days via `start=`, more
  via `period=`). **Re-stamp bars to bar-END time (§2c)** before aligning —
  this is also non-negotiable, it's a look-ahead bug otherwise, just a
  smaller one (up to 1 hour) than the CLOB leak.
- **Recommendation for step 3/4 ingestion**: do NOT rely on `interval=max`
  for CLOB pulls — chunk with explicit bounds and clip. Do NOT use yfinance
  bar start-timestamps directly for alignment — re-stamp to bar end. Both are
  now implemented as reusable functions in this spike's script
  (`parse_clob_history(..., start_ts=, end_ts=)` and
  `restamp_to_bar_end`) and should be ported into
  `src/poly_actor/ingest/` in step 3 essentially as-is.
- **Fallback if chunked ingestion proves impractical at scale** (e.g. rate
  limits appear once ingesting many markets in parallel): fall back to
  `fidelity=720` (12-hourly) via `interval=max`, which is always available
  for a market's full life with a single request, and do daily/12h-resolution
  lead-lag/event-study analysis instead of hourly. This is a graceful
  degradation, not something expected to be needed based on what was
  observed here.

## Surprises / anomalies worth flagging to the team

1. **Look-ahead leak**: `prices-history` with explicit `startTs`/`endTs` on an
   ACTIVE market appends a point at the current wall-clock time, after
   `endTs`. See §1a. This is the most important finding in this doc — it
   will silently corrupt backtests if not clipped.
2. `interval=max` + fine `fidelity` on the CLOB does **not** behave as
   documented/expected — it silently returns coarser buckets (ACTIVE market)
   or **empty results** (RESOLVED market) rather than an error or a
   fidelity-respecting response. Always use explicit `startTs`/`endTs` for
   fine-grained pulls (and remember to clip per §1a).
3. Gamma's `/events?search=` free-text parameter returns largely irrelevant
   results; use `tag_slug=`/`slug=` for reliable discovery instead.
4. Gamma's own timestamp fields are **not uniformly formatted**: most (e.g.
   `endDate`, `createdAt`) are ISO-8601 with a trailing `Z`
   (`"2025-09-17T12:00:00Z"`), but `closedTime` on individual markets uses a
   different, non-ISO format: `"2025-09-17 21:08:44+00"` (space separator,
   no `T`, no minutes on the UTC offset). `pd.to_datetime(x, utc=True)`
   parses both correctly and should be the standard parser; a hand-rolled
   strict-ISO8601 regex/parser would silently fail or mis-parse `closedTime`.
   **Step 3 parser requirement**: use `pd.to_datetime(..., utc=True)` (or
   equivalent dateutil-based parsing) for all Gamma timestamp fields, never a
   format-locked parser.
5. yfinance `period=` is measured in **trading days, not calendar days** —
   `period="730d"` spans ~1064 calendar days, `period="60d"` spans ~84
   calendar days. This is expected behavior, not a cap change, once you know
   `period` ≠ calendar days. The actual calendar-day cap (730 days) only
   applies to explicit `start=`/`end=` requests. See §2a. (An earlier draft
   of this doc mischaracterized this as "yfinance now allows looser history
   than documented" — that was wrong; it's just trading-day vs calendar-day
   unit confusion.)
6. yfinance 1m data: the 30-day-total-lookback and 8-day-per-request limits
   are enforced, but inconsistently surfaced — a single out-of-range
   `period="30d"` request returns an **empty DataFrame silently** (printed
   warning only, no exception), while an explicit `start=`/`end=` request
   past 30 days back also returns empty with a clearer warning. Ingestion
   code must check `len(df) == 0` rather than relying on exceptions.
7. yfinance 1h bars are **labelled by their start time**, with the session's
   last bar 30 minutes long (15:30–16:00 ET) on regular days but **90
   minutes** (11:30–13:00 ET) on early closes — not a uniform 30 minutes, and
   not a uniform 7 bars/day either (3 on early closes; see §2c for a third
   pattern, real data gaps, found at 2026-01-30 and 2026-02-02 in the pulled
   window). Must re-stamp to bar-end, using the real NYSE session close per
   day (`exchange_calendars`), before using as an "as of" timestamp anywhere
   alignment happens — a fixed +30min or +60min rule is wrong on early closes.
8. The CLOB's `startTs`/`endTs` boundaries are **inconsistent** across
   markets and windows: sometimes inclusive, sometimes exclusive, sometimes
   empty for tiny windows. See "Chunk-boundary behavior" under Recommendation.
   Clip client-side to `[start, end)` and de-duplicate on `t`.

# Lesson 1 — Time, Fidelity, and Look-Ahead Bias

*Read time: ~10 minutes. No network calls — everything here is either a toy
example or numbers already captured in `docs/step1_data_check.md` and
`notebooks/step1_data_check.py` from a real run.*

This lesson is about the single most dangerous bug class in this whole
project: **letting a model see the future by accident**. Step 1 (the data
check spike) found two real, concrete ways that happens before you even get
to any modeling. We'll build up the intuition, show a toy example, then show
you exactly where it happened in our real data.

---

## 1. Time resolution: fidelity, 1h bars, and why we chunk

**ELI5:** imagine you're filming a race with a camera that only takes one
photo per hour. If the lead changes hands three times in that hour, your
photos just show "runner A was ahead at 1pm, runner A was ahead at 2pm" — you
never *see* the three lead changes in between. "Fidelity" is how often the
camera clicks. Daily data is a camera that clicks once a day; it's nearly
blind to anything that resolves within a day.

**Why this matters for us:** the whole point of milestone 1 is "does
Polymarket lead or lag the stock market?" Lead-lag is a question about
*order* and *timing* — which one moved first, and by how much. If your data
is daily, and both series move on the same day, you simply cannot tell which
one moved first. You need bars fine enough that a real lead/lag gap (minutes
to hours, probably) actually shows up as "A moved in bar N, B moved in bar
N+1," not as "they both moved in the same giant bucket."

That's why the spike pushed for **1-minute or hourly bars**, not daily:
- Polymarket's CLOB `prices-history` endpoint: `fidelity=1` ≈ 1-minute,
  `fidelity=60` ≈ hourly (see `fetch_prices_history` in
  `notebooks/step1_data_check.py`).
- yfinance: `interval="1h"` or `interval="1m"`.

**Why ≤15-day chunks?** This isn't a design choice we made for fun — it's a
hard server limit we discovered by testing it directly (§1b of
`docs/step1_data_check.md`, "max-range-per-request probe"): requesting more
than 15 days of CLOB history in one call with explicit `startTs`/`endTs`
returns an HTTP 400, *at both* `fidelity=1` and `fidelity=60`. So to get
1-minute data across a 4-month FOMC market's whole life, you can't make one
request — you tile ~9 requests of ≤15 days each, back to back, and
concatenate. (yfinance has its own, different limits: 1-minute bars cap at 8
days per request and 30 days of total lookback — see §2b.)

Side note on a trap here: the spike also found that asking for the
*theoretically* finest fidelity isn't the same as actually getting it.
`interval=max` with `fidelity=1` silently returned 10-minute-spaced points
on the active market, and *zero* points on the resolved one — the server
quietly substitutes a coarser bucket instead of erroring. The fix is: use
explicit `startTs`/`endTs`, not `interval=max`, whenever you actually need
fine resolution.

---

## 2. Look-ahead bias

**ELI5:** look-ahead bias is when your "historical" data secretly contains
information from the future. It's like grading yesterday's weather forecast
using today's actual weather report that got stapled to the same page by
mistake — of course the forecast looks amazing, but only because you cheated.
In backtesting, look-ahead bias is the single easiest way to convince
yourself a strategy works when it doesn't, because the leak is invisible
unless you go looking for it.

The hard rule in `CLAUDE.md` is blunt about this: **"A value at time t may
only use data available at or before t."** Step 1 found two real violations
of that rule hiding in raw API responses, not in any of our own logic.

### Trap (a): the CLOB appends "now" to old requests

When you ask Polymarket's CLOB for an ACTIVE (unresolved) market's price
history with an explicit window — say, July 1 to July 15 — you'd expect back
only points between those two dates. Instead, the spike found the API
tacks on **one extra point stamped at the current wall-clock time** (the
moment you made the request), sitting after your requested end date.

Concretely, from the real repro in `docs/step1_data_check.md` §1a:
- Requested window: `2026-07-01` → `2026-07-15`.
- Last real point in range: `2026-07-14T23:59:05Z, p=0.58`.
- Then: `2026-10-01T09:58:11Z, p=0.635` — that's "now" (the day this spike
  was run), nearly three months outside the requested window.

If you ingested that naively, you'd have a "July" dataset that secretly
contains an October price. Any backtest using it would be implicitly peeking
at the future.

**The fix:** `parse_clob_history(body, start_ts=..., end_ts=...)` in
`notebooks/step1_data_check.py` drops any point with `t < start_ts` or
`t > end_ts` whenever you pass those bounds. There's even an inline test for
it, `_self_test_clip_lookahead`, that asserts a synthetic leaked point gets
dropped. Go look at both — they're short and worth reading once.

### Trap (b): stock bars are timestamped by when they *start*, not when they end

This one is sneakier because it's not a bug in the API, it's a *convention*
that silently breaks your assumptions. A yfinance 1-hour bar labelled
`09:30` covers the window `09:30`–`10:30`. Its `Close` value — the price at
10:30 — literally cannot be known until 10:30. But if you treat the
`09:30` timestamp as "this is what we knew as of 09:30," you've just let the
model see 60 minutes into its own future.

It gets worse on early-close days (half days, like the day before
Thanksgiving): the market closes at 13:00 instead of 16:00, so the day only
has 3 hourly bars (`09:30, 10:30, 11:30`) instead of 7, and the **last** bar
of the day runs `11:30`–`13:00` — a 90-minute bar, not the usual 60. A fixed
"+30 minutes" or "+60 minutes" rule gets this wrong; you need the *real*
exchange calendar to know where the session actually closes that day.

**The fix:** `restamp_to_bar_end(df)` in `notebooks/step1_data_check.py`
re-stamps every bar's index to its true end time, using the real NYSE
(`XNYS`) session close for that date (via the `exchange_calendars` package)
for the day's last bar, and `start + 60min` for every other bar. There's an
inline test for this too, `_self_test_restamp_to_bar_end`, covering a
regular day, an early-close day, and a day with a missing mid-day bar.

### Toy timeline: how a wrong timestamp manufactures a fake "lead"

Here's a tiny made-up example with one stock bar and one Polymarket point,
showing how trap (b) alone can make it *look* like Polymarket predicts the
stock market, when actually nothing of the sort happened.

Imagine some news breaks at 10:15 that moves both the stock and the
Polymarket market. Here's what really happened, second by second:

| Wall-clock time | Event |
|---|---|
| 09:30 | Stock bar opens. Nothing special yet. |
| 10:15 | News breaks. Polymarket price jumps 0.50 → 0.70 almost instantly (continuous trading). |
| 10:15 | Stock price *also* starts moving, same news. |
| 10:30 | Stock bar closes. `Close` finally reflects the news-driven move. |

Now compare the **wrong** (start-labelled) table to the **correct**
(end-labelled) table:

| Bar / point | Wrong timestamp used | Correct timestamp |
|---|---|---|
| Stock 09:30 bar (close reflects 10:30 price) | `09:30` | `10:30` |
| Polymarket point (jumped right after the news) | `10:15` | `10:15` |

- **With the wrong timestamp:** your aligned table says "stock moved at
  09:30, Polymarket moved at 10:15" — i.e. the stock moved *first*, 45
  minutes before Polymarket. A lead-lag analysis would conclude "the stock
  market leads Polymarket," which is backwards and purely an artifact of the
  mislabeled bar.
- **With the correct timestamp:** the stock bar's close is honestly dated
  `10:30`, which is *after* Polymarket's `10:15` move. Now the (correct)
  picture is "Polymarket moved first, stock confirmed later" — or, more
  carefully, "we don't actually know the stock's price before 10:30, so we
  can't claim anything about the gap between 10:15 and 10:30."

Trap (a) can manufacture an even more dramatic fake result: if an October
price gets labelled as a July data point, a naive backtest could "discover"
that Polymarket in July perfectly anticipated something that only became
knowable in October — which isn't prediction, it's just the leaked future
answer sitting in the training data.

**The common thread:** both traps make the data say "we knew X at time T"
when in reality X wasn't knowable until some time *after* T. Whenever you
align two series, always ask: *could I have actually observed this value at
this exact timestamp, in real time, with nothing later leaking in?*

---

## 3. Time zones: why UTC, and what DST breaks

**ELI5:** "3pm" means something different in New York, London, and Tokyo —
so a bare "3pm" with no timezone is like a street address with no city. UTC
is the one timezone that doesn't change with the seasons and doesn't depend
on where you are, so everyone can agree on what "3pm UTC" means, always.

`CLAUDE.md` makes this a hard rule: **"Store tz-aware UTC timestamps. Never
use naive datetimes."**

Two real reasons this matters, both found directly in step 1:

1. **Polymarket's CLOB timestamps (`t`) are unix epoch seconds** — inherently
   UTC by definition, no tz field at all. Easy to parse right
   (`pd.to_datetime(df["t"], unit="s", utc=True)`), but if you ever eyeballed
   one of these as a naive datetime and assumed it was your local time,
   you'd be off by however many hours your timezone is from UTC.

2. **yfinance's intraday index comes back already tz-aware, but in
   `America/New_York`, not UTC** (§2b). If you join that directly against
   UTC-stamped Polymarket data without converting first, every comparison is
   silently off by the ET-UTC offset — and that offset **isn't even
   constant**: it's `UTC-5` in winter (EST) and `UTC-4` in summer (EDT,
   daylight saving time). A join that happens to work correctly in July could
   be off by an hour in January, purely because DST shifted the offset and
   nobody re-converted.

The fix is simple and already in the script: always call
`.tz_convert("UTC")` on the yfinance index before comparing it to anything
else. Do the tz conversion *before* re-stamping to bar-end in some cases and
after in others — the actual script does `restamp_to_bar_end` first (while
still in `America/New_York`, so day boundaries and the NYSE calendar line up
correctly), *then* converts to UTC. Converting to UTC first and restamping
second would use UTC day boundaries, which don't match NYSE trading days and
would misassign early closes.

---

## 4. Common mistakes checklist

- [ ] Using daily bars for a question that's fundamentally about intraday
      timing (you'll never see the lead-lag).
- [ ] Trusting `interval=max` to give you the fidelity you asked for — it
      silently coarsens or returns empty instead of erroring.
- [ ] Requesting more than 15 days in one CLOB call with explicit
      `startTs`/`endTs` (HTTP 400).
- [ ] Not clipping an ACTIVE market's CLOB response to `[start_ts, end_ts]`
      — the trailing "now" point will leak in.
- [ ] Using a yfinance bar's start timestamp as its "as of" time instead of
      restamping to bar-end.
- [ ] Assuming every trading day has exactly 7 hourly bars — early closes
      have 3, and real data gaps (found at `2026-01-30`, `2026-02-02` in the
      spike) can have fewer still; both need handling, not a hardcoded count.
- [ ] Comparing a `America/New_York` index to a UTC index without
      `.tz_convert("UTC")` first — correct in summer, silently wrong by an
      hour after a DST change.
- [ ] Converting to UTC *before* restamping to bar-end (breaks NYSE
      day-boundary logic); always restamp in exchange-local time first.

---

## Quiz

1. You pull a 20-day window of 1-minute CLOB data for an ACTIVE market in
   one request. What happens, and what should you do instead?

2. A yfinance 1h bar is labelled `14:30` on a regular trading day. What time
   period does its `Close` value actually reflect, and what UTC-equivalent
   timestamp should you use if you want to treat that close as "known as of"
   a given moment?

3. True or false: converting a UTC timestamp to `America/New_York` always
   involves subtracting a fixed 5 hours. Why does this matter for a
   multi-year backtest?

<br><br><br><br><br><br>

### Answers

1. **It fails with HTTP 400** — the spike confirmed the CLOB caps explicit
   `startTs`/`endTs` windows at 15 days (at both `fidelity=1` and
   `fidelity=60`; §1b, "max-range-per-request probe"). Instead, chunk the
   pull into ≤15-day windows, tile them back to back, concatenate, and
   de-duplicate on `t` (chunk-boundary inclusion is inconsistent — see the
   "Chunk-boundary behavior" note in `docs/step1_data_check.md`).

2. The `14:30` bar covers `14:30`–`15:30`, so its `Close` is the price at
   `15:30` — not knowable until `15:30`. After running it through
   `restamp_to_bar_end`, the bar's index becomes `15:30` ET, which you then
   `.tz_convert("UTC")` to get the correct UTC "known as of" timestamp
   (`19:30 UTC` in EDT, `20:30 UTC` in EST — the offset itself changes with
   DST, which is exactly why you always convert explicitly rather than
   hardcoding an offset).

3. **False.** `America/New_York` is `UTC-5` (EST) in winter and `UTC-4`
   (EDT) in summer because of daylight saving time — the offset isn't fixed.
   This matters because a project like this one runs backtests across many
   months or years, crossing multiple DST transitions; any code that
   hardcodes "subtract 5 hours" instead of using proper tz-aware conversion
   (`.tz_convert("UTC")`, which knows the DST rules) will silently be wrong
   by an hour for roughly half the calendar year.

# Step 2 - Pick pairs (round 3)

Status: **DRAFT, pending user approval** (`config/pairs.yaml`, `status: draft  # pending user approval`).
Analysis plan frozen in `docs/preregistration.md` (2026-10-01, before any price history was viewed).

## How this was built

- `scripts/build_pairs.py` regenerates `config/pairs.yaml` from the Gamma dumps in
  `data/scratch/step2/`. Run `.venv/Scripts/python.exe scripts/build_pairs.py` (offline, from cache) or add
  `--refetch` to re-pull from the live Gamma API. Do not hand-edit the yaml.
- **Dump location moved.** The first draft wrote its dumps to `data/raw/step2/`. `data/raw/` is reserved for
  step-3 ingestion, so the whole folder was *moved* (not deleted or copied) to `data/scratch/step2/`;
  `evidence_dir` in the yaml now says `data/scratch/step2/`. `data/raw/` is currently empty.
- Round 3: 2 more Gamma calls (`november-inflation`, `august-inflation-us-annual-1786474662954`). The script is now
  offline by default: a cache miss raises `CacheMiss`; use `--fetch-slugs SLUG ...` (targeted) or `--refetch` (all).
  Pure helpers (`et_to_utc`, `parse_cpi_bucket`, `ladder_crossing`, `parse_strike`) live in `src/poly_actor/pairs.py`
  with tests in `tests/test_build_pairs.py`.
- API use in this rework: 39 calls in a first run that was cut short (see pagination below) + 67 calls in the
  completing run = 106 calls, 0.5 s sleep, retry/backoff on 429/5xx. The original draft used 69 calls.
- Market-level Gamma fields (`startDate`, `endDate`, `closedTime`) are authoritative; event-level ones can be
  stale (the 2026 recession event says 2026-12-31, its market says 2027-01-31).

### Pagination (validator blocker) and a deliberate deviation

The first draft's tag listings were capped at exactly 50 or 100 rows (silent truncation), which is why meetings
and months went missing. Fix: `paginate_events` pages with `offset` until a short or empty page, with a page cap.

- **Fed** (`tag_slug=fed-rates`): fully paginated (144 closed + 27 open events). Every FOMC meeting from
  2024-11 to 2027-01 is read off that list, not guessed. It also exposed an older naming series
  (`fed-interest-rates-<month>-<year>`) that holds the 2024-11, 2024-12 and 2025-01 meetings.
- **Bitcoin and CPI**: `tag_slug=bitcoin` and `economy` are enormous (bitcoin: 2,100+ closed events and a server
  422 past offset 2100; economy: 1,277 events) and `inflation` mixes every country. Exhaustive pagination would have
  burned the call budget on irrelevant events. Because both series are strictly one-event-per-month, they are
  discovered by **direct per-month slug lookup** (`BTC_MONTHS`, `CPI_MONTHS` in the script), and a month with no
  hit is recorded as an explicit gap. This is a methodology deviation from "paginate every tag you use"; the
  boundedness of each series makes it equivalent in coverage. A non-obvious slug (e.g. a month that exists under an
  unguessed suffix) could still be missed - flagged in risks.
- **Tariffs, recession tags**: paginated (small tags).

## Summary

| id | priority / analysis | tickers (expected sign) | events | coverage | volume |
|---|---|---|---|---|---|
| `fed_decision` | primary / hourly lead-lag + decision-hour event study | TLT +, SPY + (weak), XLF ambiguous (tested as XLF-SPY) | 19 meetings (16 resolved, 3 active) | 2024-10-01 to now (and 3 future meetings) | ~$3.46B |
| `bitcoin_monthly_ladder` | primary / hourly lead-lag vs BTC-USD baseline | IBIT +, COIN +, MSTR +, BTC-USD baseline +, XLU placebo 0 | 22 monthly events (21 resolved, 1 active), 2 gaps | 2024-11 to now; usable ladders from 2025-01 | ~$944M |
| `us_cpi_inflation` | primary / release-day event study | TLT -, QQQ - | 21 monthly events (20 resolved, 1 active); 2025-10 excluded (no BLS release), 2026-02 gap ($0) | 2024-11 to 2026-10 | ~$15.9M |
| `us_recession` | secondary / event study | SPY -, IWM -, TLT +, IWM-SPY - | 2 markets (1 resolved) | 2025-01 to 2027-01 | ~$14.0M |

Data coverage for hourly work: Polymarket resolved markets are reconstructable at 1-minute fidelity by chunking
`prices-history` into windows of at most 15 days (step 1); yfinance 1h reaches back past 2024-10-01 (step 1 saw
~1,064 days; 730 days is the conservative bound used here). Both sides therefore overlap from about 2024-10-01 for
Fed, from 2025-01 for Bitcoin (2024-11 and 2024-12 have no dip ladder), and from 2024-12 for CPI. Hourly overlap is
limited to US regular-session hours for equity targets.

## Pair 1 - `fed_decision`

Each meeting in the official FOMC calendar maps to exactly one event. Decision time = 14:00 ET of the second day,
converted to UTC with `zoneinfo` (America/New_York); roll = +1 hour.

| Meeting | Event slug | Decision (UTC) | Outcome | Volume |
|---|---|---|---|---|
| 2024-11 | `fed-interest-rates-november-2024` | 2024-11-07 19:00 | cut 25 | $189.5M |
| 2024-12 | `fed-interest-rates-december-2024` | 2024-12-18 19:00 | cut 25 | $58.8M |
| 2025-01 | `fed-interest-rates-january-2025` | 2025-01-29 19:00 | no change | $190.9M |
| 2025-03 | `fed-decision-in-march` | 2025-03-19 18:00 | no change | $78.0M |
| 2025-05 | `fed-decision-in-may-2025` | 2025-05-07 18:00 | no change | $88.4M |
| 2025-06 | `fed-decision-in-june` | 2025-06-18 18:00 | no change | $106.9M |
| 2025-07 | `fed-decision-in-july` | 2025-07-30 18:00 | no change | $136.6M |
| 2025-09 | `fed-decision-in-september` | 2025-09-17 18:00 | cut 25 | $220.6M |
| 2025-10 | `fed-decision-in-october` | 2025-10-29 18:00 | cut 25 | $252.5M |
| 2025-12 | `fed-decision-in-december` | 2025-12-10 19:00 | cut 25 | $393.9M |
| 2026-01 | `fed-decision-in-january` | 2026-01-28 19:00 | no change | $659.5M |
| 2026-03 | `fed-decision-in-march-885` | 2026-03-18 18:00 | no change | $260.1M |
| 2026-04 | `fed-decision-in-april` | 2026-04-29 18:00 | no change | $284.2M |
| 2026-06 | `fed-decision-in-june-825` | 2026-06-17 18:00 | no change | $164.6M |
| 2026-07 | `fed-decision-in-july-181` | 2026-07-29 18:00 | no change | $144.0M |
| 2026-09 | `fed-decision-in-september-762` | 2026-09-16 18:00 | hike 25 | $208.0M |
| 2026-10 | `fed-decision-in-october-20260617190323537` | 2026-10-28 18:00 (active) | - | $20.2M |
| 2026-12 | `fed-decision-in-december-20260729232808632` | 2026-12-09 19:00 (active) | - | $2.2M |
| 2027-01 | `fed-decision-in-january-20260729233815502` | 2027-01-27 19:00 (active) | - | $0.19M |

Calendar sourcing (round 3): all 19 decision dates are hardcoded from the official calendar
(https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) in `FOMC_DECISION_DATES_ET`. The first draft derived
2026-10 / 2026-12 / 2027-01 from the UTC day of a Gamma endDate set at 23:59 ET (the next UTC day), which put them a day
late (2026-10-29, 2026-12-10, 2027-01-28); that derivation is removed. Every event time is also cross-checked at build
time: for each resolved event the decision/release must fall on the same ET day as, or before, the earliest market
`closedTime` (an assertion; a mismatch table is printed). Official 2024-2025 meetings not in the table
(2024-01/03/05/06/07/09) have either no market or fall outside the yfinance window.

Signal: `sum(p_i * delta_i) / sum(p_i)` in bp, delta = -75/-50/-25/0/+25/+50; open-ended buckets ("50+", "75+",
"25+") use the stated size (documented bias: understates tails); missing buckets count as 0; each event's outcome set is
stored in the yaml. Dovishness = minus the signal. The 2024-11 and 2024-12 events carry a catch-all "another level"
bucket, excluded and tracked as `other_mass`. Splicing and roll rules are in section "Common rules".

Rationale (see yaml): cuts priced lowers long yields so TLT up; SPY weaker and regime dependent; XLF ambiguous
(margin compression vs credit easing), so it is tested relative to SPY.

## Pair 2 - `bitcoin_monthly_ladder`

22 of 24 months (2024-11 to 2026-10) have an event; **2025-03 and 2025-12 have none** (checked
`what-price-will-bitcoin-hit-in-march`, `-march-2025`, `-december-2025`; an unguessed suffix remains possible, like
the `-985` suffix on Oct 2025). `what-price-will-bitcoin-hit-in-november-2025` was recovered ($53.0M). 2024-11 and
2024-12 have only an up ladder (no "dip to" rungs), so no ladder level exists for them.

The first draft's "nearest 0.50 reach threshold" is replaced: touch markets pin to 1 and close within days, and
zombie rungs (e.g. a $100k dip rung with $2 of volume) can be picked. New signal: at each hour t use only rungs that
are open at t, in an event that has been open for at least 24h (round 3 replaced the $1,000 lifetime-volume floor, which
is only known at pull time, i.e. look-ahead; a touched rung counts as P=1 after its closedTime so 0.5 stays bracketed); log-interpolate K_up* (P(reach)=0.5) on the up ladder and K_dn* (P(dip)=0.5) on
the dip ladder; `ladder_level = exp(mean of the logs)`, `skew = ln K_up* + ln K_dn* - 2 ln S_t`. Primary signal =
hourly change in `ln(ladder_level)`. BTC-USD spot (yfinance, 24/7) is a **required baseline**: the question is whether
Polymarket adds information beyond spot. IBIT is a direct target; XLU is a placebo.

Corrected sample note (old `pairs.yaml:578`): the earlier text said spot was about $85-87k by crossing "reach 90k"
(0.475) with "dip 80k" (0.605). That mixed the two ladders. From the cached Oct-2026 snapshot, the up-ladder crossing
is about $89.5k, the dip-ladder crossing about $78.5k, ladder level about $83.8k. This is a snapshot of Gamma
`outcomePrices`, not a price-history look.

Month-start gap: a new monthly event opens up to ~2 days into the month (largest observed 38 h, Jan 2025), while the
previous month's event rolls out at month end + 1h. Hours between that roll and the new event's `first_usable_utc`
(open + 24h) carry no signal and are dropped; `event_open_lag_hours_after_month_start` and `first_usable_utc` are in the
yaml per month and step 3 reports the dropped share.

## Pair 3 - `us_cpi_inflation` (release-day event study)

Signal `sum(p*c)/sum(p)`; edge buckets use boundary +/- 0.1 as centre with an `edge_mass` flag, drop hour if edge mass
exceeds 0.10. The CPI series is analysed as a **release-day event study** (08:30 ET is outside stock hours; the implied
level barely moves between releases), not hourly lead-lag. January 2025 (`january-inflation-annual`, $0.26M) recovered.
January 2026 is two overlapping events (`...-lower-brackets-817` and `january-inflation-us-annual`), merged into 11
buckets with a derived "2.7-2.8" bucket and the redundant "<=2.8" dropped. March 2026 has two companion events; the
primary `march-inflation-us-annual` has **9 buckets** (not 10) and resolved in the `>=2.8` edge bucket (not "2.8"), the
`-higher-brackets` companion (resolved 3.3) refines that tail; merged to 15 buckets. Round 3 changes: November 2024
(`november-inflation`, release 2024-12-11 08:30 ET, resolved 2.7, $0.40M) added; August 2026
(`august-inflation-us-annual-1786474662954`, 12 buckets, $156K, closed 2026-09-11 14:32Z, resolved 3.4, release
2026-09-11 12:30Z) added (it is not a gap, it just carries an unguessable numeric suffix); the "or greater / or more /
or higher / or above / or lower / or below" wording is parsed as an edge bucket (Dec 2024 `...2pt9-or-greater...` is a
high edge with centre 3.0). **October 2025 is excluded**: BLS never published October-2025 CPI (shutdown, no October
survey), so there is no 08:30 ET release to anchor a roll or event window; the Polymarket event
`october-inflation-annual` ($282K) resolved on 2025-11-22 by market rule and is dropped. The only remaining gap is 2026-02
(event exists, $0 volume). Release dates are the BLS schedule (https://www.bls.gov/schedule/news_release/cpi.htm,
fetched 2026-10-01): 2025-09 CPI was shutdown-delayed to 2025-10-24, 2026-01 CPI was 2026-02-13, 2026-06 CPI was
2026-07-14, and 2026-09 CPI is scheduled 2026-10-14 (confirmed on that page). Method validation against each resolved month's winning bucket is pre-registered
(winning bucket and centre are stored per month in the yaml); it needs price history, so it runs in step 3/4 before any
return is examined.

## Pair 4 - `us_recession` (secondary, event study)

`us-recession-in-2025`: market starts 2025-01-08, **closedTime 2026-01-01 09:23:25Z** (event-level end 2026-02-28 is
misleading), resolved No, $11.7M. `us-recession-by-end-of-2026`: **market endDate 2027-01-31** (event-level 2026-12-31
stale), active at 8.5%, $2.2M. No recession market exists before 2025-01-08 (`signal_first_active_utc`), so
2024-10-01 to 2025-01-08 is a recorded gap. Priority secondary, effectively one episode, so no lead-lag claim. Added TLT (positive,
flight to quality) and the IWM minus SPY spread. Roll is a pre-registered fixed time (2025-10-01 00:00 UTC), not
closedTime.

## Common rules (also in `pairs.yaml`)

- **Roll timing**: never on Gamma `endDate` (set hours before the announcement) or the `closed` flag (current state,
  look-ahead). Hardcoded official-date tables for FOMC (14:00 ET), BLS CPI (08:30 ET) and BTC month end (00:00 ET),
  converted with `zoneinfo` (DST-correct, e.g. BTC 2026-10 month end = 2026-11-01T04:00Z); roll 1 hour after the event
  time. Zero probability mass in an hour (sum p = 0) drops the hour (Fed, CPI).
- **Splicing**: signals are spliced from changes, never levels; never difference across two events; at a roll hour use
  the new event's own 1-hour change and set `roll_hour` so step 6 can exclude it.
- **Trading-hours artifact**: lead-lag only on hours when both markets trade; overnight/weekend moves compared against
  the opening gap separately; BTC pair additionally controlled for BTC-USD.

## Rejected candidates

- **Tariff / trade** (re-checked after pagination): `tariff` has 6 closed + 1 open events, `general-tariff` 1 closed +
  0 open. Largest is a one-off ($6.7M, 2025-04 to 06 trade-deal markets); only one open market ($16K). No continuing
  series. Still rejected.
- **BTC daily up/down and above-X markets**: current volumes of tens of thousands of dollars per day vs tens of millions
  per month, and about 250 rolls per year.
- **BTC deadline-bucket markets** (`when-will-bitcoin-hit-150k`, `bitcoin-all-time-high-by`): deadline buckets resolve
  to a terminal No as dates pass, awkward for a continuous signal.
- **`recession` and `macro-inflation` tags**: nearly empty/abandoned; the real series sit under other tags/slugs.

## Open risks

1. Per-month slug enumeration for BTC/CPI could miss an event with an unguessable suffix (CPI Aug-2026 was exactly
   this: found in round 3 under `-1786474662954`; the two BTC gaps, 2025-03 and 2025-12, are the remaining candidates to
   double check in step 3 against the `economy`/`bitcoin` listings).
2. Composite signals (Fed bp score, BTC ladder level, CPI expected value) are our constructions; the CPI method is
   validated against winning buckets in step 3/4 before use. Open-ended Fed buckets understate tails.
3. Thin liquidity early in each event's life (Jan-2027 Fed $0.19M, Sep-2026 CPI $83K, Oct-2026 BTC $71K); rungs and
   buckets can be stale. The BTC volume floor was dropped in round 3 (lifetime volume is a pull-time, look-ahead
   quantity); the time-t rule is event age >= 24h plus rung open at t. Cumulative volume to t may be added in step 3 from
   trades. The share of dropped hours (0.5 not bracketed, month-start gap) is a step-3 metric.
4. Overlapping Fed events need the "next meeting" rule; any level spliced across events would be wrong.
5. Hourly reconstruction cost: ~16 resolved Fed events x 5 buckets x several 15-day chunks, plus ~20 BTC rungs per
   month and ~10 CPI buckets per month; step 3 must be incremental and cached.
6. CPI and Fed hours carry the trading-hours artifact: the decisive moves occur at 14:00 ET (in session) for Fed but
   08:30 ET (pre-open) for CPI.
7. FOMC dates are the official federalreserve.gov calendar and CPI dates the BLS schedule (2026-09 CPI on 2026-10-14
   confirmed on bls.gov); future dates (2026-10 onward) can still be rescheduled. The build asserts each event time
   against the earliest Gamma `closedTime` for resolved events only; active events (FOMC 2026-10/12, 2027-01, CPI
   2026-09) are not cross-checked.
8. Prices and volumes of active markets are a 2026-10-01 snapshot.
9. Recession pair: one episode, not a basis for inference.
10. Several event slugs for 2025-2026 carry unexplained numeric suffixes; the slug table in the yaml is the only
    authoritative mapping.

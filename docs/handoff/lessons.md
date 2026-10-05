# Lessons (read before building or validating any step)

Every bug class an independent validator has caught so far. Builders self-check against this list before reporting.

## Time and look-ahead
- **CLOB live point.** For active markets the CLOB appends the *current* price after `endTs`. Clip every response to `[start, end)`.
- **CLOB window boundaries are inconsistent.** Pad the request, clip on the client, tile windows back to back, and de-duplicate on `t`.
- **yfinance bars are start-stamped.** Re-stamp each bar to its end using the XNYS calendar: the last bar of the day ends at the session close, and on early closes the 11:30 bar runs to 13:00. Use `cal.early_closes`, not hardcoded hours.
- **DST.** Convert ET to UTC with `zoneinfo`, never with date-based offset rules. Test the switch days.
- **fid-60 CLOB points are stamped seconds after the hour;** strict as-of makes them ~1h stale and biases lead-lag toward "Polymarket lags". Measure the stamp offset before resampling.
- **Snapshot fields are look-ahead.** Lifetime volume, final `active` and `closed` flags, and anything "known at pull time" must not select data at time t. Use only facts known at t (e.g. `created_utc + 24h ≤ t`, `closed_time ≤ t`).

## Sources and dates
- **Official calendars only.** FOMC dates come from federalreserve.gov, CPI releases from the BLS schedule, sessions from `exchange_calendars`. Never derive event times from Gamma `endDate` (it falls hours before the announcement) or from the UTC day of a 23:59 ET timestamp.
- **The 2025 government shutdown moved CPI releases**, and the Oct-2025 CPI was never published.
- **Paginate every Gamma listing until it comes back empty.** Page caps of 50 or 100 rows silently drop events.
- **Gamma metadata is messy.** Timestamp formats are mixed, slugs carry numeric suffixes, the same question is re-listed under a new slug, titles can contradict the resolution text (resolve by the description), and volume fields are unreliable. Don't filter on volume.
- **yfinance:** `period=` counts trading days, `start=` is capped at 730 calendar days, an empty frame comes back silently (check row counts), and Yahoo has missing-bar days (e.g. 2026-01-30 to 02-02).

## Signal design
- **Splice on changes, never levels,** across a roll. Flag roll hours.
- **Normalize bucket probabilities by Σp.** Handle open-ended edge buckets explicitly.
- **Ladders must be monotone,** with one rung per strike per hour. A touched strike implies every strike beyond it is touched too (dip: every higher strike; up: every lower strike).
- **Closed-market hours create fake leads.** Test only on hours when both sides trade.

## Process
- **Write rules as 2–3 concrete input → expected-output examples** and turn them into tests. Prose rules got inverted twice.
- **Pre-registration changes are dated amendments,** never silent rewrites.
- **Mutation-test the key guards** (clip, touch direction, DST, write-once). A test that survives removing its guard is useless.
- **An empty API response is not proof of no data** when the market was trading. Confirm it with a second probe before marking the window covered.
- **Check that a rule actually fires on real data,** not only on synthetic tests. A guard or exception that never triggers in production (e.g. A22 after dedup) makes its robustness check meaningless.

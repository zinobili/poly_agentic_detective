"""Step 1 -- data check (research spike, not production code).

Answers, with evidence saved to disk:
  1. Polymarket CLOB `prices-history`: finest fidelity actually returned, how far
     back history goes, gaps, timestamp tz/format, max range per request -- for
     one ACTIVE and one RESOLVED Fed-rate-decision (FOMC) market.
  2. yfinance 1h and 1m bars for TLT/SPY: history depth, index tz, gaps,
     extended-hours or not.
  3. One Plotly chart: Fed market "Yes" probability vs TLT price, shared UTC
     time axis, dual y-axes -> notebooks/step1_data_check.html.

This is a plain script, runnable top to bottom:
    .venv/Scripts/python.exe notebooks/step1_data_check.py

Raw API responses are dumped to data/scratch/step1/ -- NOT data/raw/, which
CLAUDE.md reserves for immutable output of the real ingestion pipeline
(src/poly_actor/ingest/). This spike's dumps are throwaway scratch evidence
for this doc, so they live under data/scratch/ instead (data/ is git-ignored
either way).

Sources and their native timestamp conventions (confirmed empirically below):
  - Polymarket Gamma API (https://gamma-api.polymarket.com): JSON timestamps
    are mostly ISO-8601 strings with trailing "Z" (UTC, e.g. `endDate`,
    `createdAt`), but at least one field (`closedTime` on individual markets)
    uses a *different* format: `"2025-09-17 21:08:44+00"` (space separator,
    no "T", offset without colon/minutes). `pd.to_datetime(x, utc=True)`
    parses both correctly; a hand-rolled strict-ISO8601 parser would not --
    documented here as a step 3 parser requirement.
  - Polymarket CLOB `prices-history` (https://clob.polymarket.com): each point
    is `{"t": <unix seconds, UTC>, "p": <probability 0..1>}`. No tz field --
    epoch seconds are inherently UTC.
    ** LOOK-AHEAD WARNING (see section 2 below): when called with explicit
    startTs/endTs on an ACTIVE (not yet resolved) market, the API has been
    observed to append one extra point stamped at the current wall-clock
    time, after endTs. This is a look-ahead leak if used naively. Always
    clip the parsed result to [start_ts, end_ts] -- see `parse_clob_history`
    and `_self_test_clip_lookahead`. **
  - yfinance (Yahoo Finance): intraday bar timestamps come back as tz-aware
    `America/New_York` (exchange-local), NOT UTC, and are labelled by the
    bar's START time (the 09:30 bar covers 09:30-10:30), not its end. Must be
    `.tz_convert("UTC")`-ed and, for anything that needs an "as of" timestamp
    comparable to Polymarket data, re-stamped to bar END time -- see
    `restamp_to_bar_end` (a step 4 requirement, applied here only for the
    chart). The bar grid is NOT a uniform 7-bars-every-day: regular sessions
    have 7 hourly bars (09:30..15:30), early closes (half days) have only 3
    (09:30, 10:30, 11:30, with the last one running 90 minutes to the 13:00
    close), and some days have fewer bars than either pattern due to real
    missing-bar data gaps (e.g. 2026-01-30, 2026-02-02 in the pulled window).
    `restamp_to_bar_end` uses the real NYSE (XNYS) session close via the
    `exchange_calendars` package for each bar's end stamp, and separately
    reports which days have fewer bars than expected as data gaps.

Constraints honoured: timeouts on every HTTP call, retries with exponential
backoff on 429/5xx, small sleeps between calls, all timestamps converted to
tz-aware UTC before being used in the chart, raw dumps never overwrite
previous runs' evidence of a *different* query (idempotent filenames keyed by
query parameters).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import exchange_calendars as xc
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from plotly.subplots import make_subplots

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "scratch" / "step1"
RAW_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_TIMEOUT_S = 20
MAX_RETRIES = 4
POLITE_SLEEP_S = 0.4

# --- Markets selected for this spike -----------------------------------
# Found via: GET {GAMMA_BASE}/events?tag_slug=fed-rates&closed=false (browsed
# results, see docs/step1_data_check.md) and a direct slug lookup for the
# resolved September 2025 FOMC event.
ACTIVE_EVENT_SLUG = "fed-decision-in-october-20260617190323537"  # Oct 2026 FOMC, open
ACTIVE_SUBMARKET_SLUG = (
    "will-there-be-no-change-in-fed-interest-rates-after-the-october-2026-meeting-20260617190324031"
)

RESOLVED_EVENT_SLUG = "fed-decision-in-september"  # Sep 2025 FOMC, closed
RESOLVED_SUBMARKET_SLUG = (
    "fed-decreases-interest-rates-by-25-bps-after-september-2025-meeting"  # resolved YES
)

TICKERS = ["TLT", "SPY"]


# --------------------------------------------------------------------------
# Thin network helpers (polite: timeout + exponential backoff on 429/5xx)
# --------------------------------------------------------------------------
def _get_with_retries(url: str, params: dict[str, Any]) -> requests.Response:
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:  # network error -> retry
            last_exc = exc
            resp = None
        if resp is not None:
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"{resp.status_code} from {url}")
            else:
                return resp
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _dump_raw(name: str, payload: Any) -> Path:
    """Idempotent scratch dump: same name -> same file, overwritten with the
    latest pull. Lives under data/scratch/step1/, not data/raw/ -- the latter
    is reserved for the real ingestion pipeline's immutable output."""
    path = RAW_DIR / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Gamma API: event/market metadata -> CLOB token ids
# --------------------------------------------------------------------------
def fetch_gamma_event(slug: str) -> dict[str, Any]:
    resp = _get_with_retries(f"{GAMMA_BASE}/events", {"slug": slug})
    resp.raise_for_status()
    events = resp.json()
    if not events:
        raise ValueError(f"no gamma event found for slug={slug!r}")
    _dump_raw(f"gamma_event_{slug}.json", events)
    time.sleep(POLITE_SLEEP_S)
    return events[0]


def find_submarket(event: dict[str, Any], submarket_slug: str) -> dict[str, Any]:
    for m in event["markets"]:
        if m["slug"] == submarket_slug:
            return m
    raise ValueError(f"submarket {submarket_slug!r} not found in event {event['slug']!r}")


def yes_token_id(market: dict[str, Any]) -> str:
    """clobTokenIds is a JSON-encoded list aligned with outcomes; outcomes[0]
    is always "Yes" for these binary FOMC markets (verified by inspection)."""
    outcomes = json.loads(market["outcomes"])
    token_ids = json.loads(market["clobTokenIds"])
    assert outcomes[0] == "Yes", f"unexpected outcome order: {outcomes}"
    return token_ids[0]


# --------------------------------------------------------------------------
# CLOB prices-history
# --------------------------------------------------------------------------
def fetch_prices_history(
    token_id: str,
    *,
    fidelity: int,
    interval: str | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
    dump_name: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"market": token_id, "fidelity": fidelity}
    if interval is not None:
        params["interval"] = interval
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    resp = _get_with_retries(f"{CLOB_BASE}/prices-history", params)
    body = {"status_code": resp.status_code, "params": params}
    try:
        body["json"] = resp.json()
    except ValueError:
        body["text"] = resp.text
    _dump_raw(dump_name, body)
    time.sleep(POLITE_SLEEP_S)
    return body


def parse_clob_history(
    body: dict[str, Any],
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> pd.DataFrame:
    """Pure parse: CLOB prices-history JSON -> tz-aware UTC DataFrame.

    Native format: list of {"t": <unix seconds>, "p": <float 0..1>}.
    `t` is unix epoch seconds with no explicit tz field; epoch seconds are
    UTC by definition, so this is a straight `unit="s", utc=True` parse.

    LOOK-AHEAD GUARD: when the caller requested an explicit `start_ts`/
    `end_ts` window, this function drops any point with `t < start_ts` or
    `t > end_ts`. This matters because the CLOB has been observed (on ACTIVE
    markets; confirmed empirically in this script's section 2) to append one
    extra point stamped at the *current* wall-clock time, after `end_ts` --
    e.g. requesting 2026-07-01..2026-07-15 returned a real last point at
    2026-07-14 23:59 followed by an out-of-window point at 2026-10-01 (the
    time the request was made). Resolved markets did not show this. Callers
    MUST pass the same start_ts/end_ts they requested to get a safe result;
    this is a step 3 ingestion requirement (see docs/step1_data_check.md).
    """
    if body.get("status_code") != 200:
        return pd.DataFrame(columns=["ts_utc", "probability"])
    history = body.get("json", {}).get("history", [])
    if not history:
        return pd.DataFrame(columns=["ts_utc", "probability"])
    df = pd.DataFrame(history)
    if start_ts is not None:
        df = df[df["t"] >= start_ts]
    if end_ts is not None:
        df = df[df["t"] <= end_ts]
    if df.empty:
        return pd.DataFrame(columns=["ts_utc", "probability"])
    df["ts_utc"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df = df.rename(columns={"p": "probability"})[["ts_utc", "probability"]]
    return df.sort_values("ts_utc").reset_index(drop=True)


def _self_test_clip_lookahead() -> None:
    """Inline regression test (pure function, no network) for the look-ahead
    guard in `parse_clob_history`. Run from `main()` before anything else."""
    start_ts, end_ts = 1_000, 2_000
    fake_body = {
        "status_code": 200,
        "json": {
            "history": [
                {"t": 999, "p": 0.1},  # before start_ts -> must be dropped
                {"t": 1000, "p": 0.2},
                {"t": 1500, "p": 0.3},
                {"t": 2000, "p": 0.4},
                {"t": 999_999, "p": 0.635},  # look-ahead leak -> must be dropped
            ]
        },
    }
    df = parse_clob_history(fake_body, start_ts=start_ts, end_ts=end_ts)
    assert list(df["probability"]) == [0.2, 0.3, 0.4], df
    assert df["ts_utc"].max() <= pd.Timestamp(end_ts, unit="s", tz="UTC")
    assert df["ts_utc"].min() >= pd.Timestamp(start_ts, unit="s", tz="UTC")
    # Unclipped parse (no bounds passed) must NOT drop the leaked point --
    # proves the guard is opt-in via start_ts/end_ts, not silent magic.
    df_unclipped = parse_clob_history(fake_body)
    assert len(df_unclipped) == 5
    print("OK: parse_clob_history drops points outside [start_ts, end_ts] (look-ahead guard)")


def describe_gaps(df: pd.DataFrame, ts_col: str = "ts_utc") -> dict[str, Any]:
    """Gap summary using a tolerance relative to the series' own median
    spacing (1.5x) rather than a fixed absolute threshold. A fixed 600s
    threshold flagged ~41% of points on a true ~600s-cadence series as
    "gaps" -- that was polling jitter around the modal spacing, not real
    missing data. Relative tolerance avoids that false-positive artifact."""
    if len(df) < 2:
        return {"n": len(df), "span": None, "median_delta_s": None, "max_delta_s": None}
    deltas = df[ts_col].diff().dropna().dt.total_seconds()
    median = float(deltas.median())
    tolerance = 1.5 * median if median > 0 else 0.0
    return {
        "n": len(df),
        "first": df[ts_col].iloc[0].isoformat(),
        "last": df[ts_col].iloc[-1].isoformat(),
        "span_days": round((df[ts_col].iloc[-1] - df[ts_col].iloc[0]).total_seconds() / 86400, 2),
        "median_delta_s": median,
        "max_delta_s": float(deltas.max()),
        "gap_tolerance_s (1.5x median)": tolerance,
        "n_gaps_gt_tolerance": int((deltas > tolerance).sum()) if tolerance else 0,
    }


# --------------------------------------------------------------------------
# yfinance
# --------------------------------------------------------------------------
def fetch_yf_hourly(ticker: str, period: str = "730d") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1h", auto_adjust=False)
    time.sleep(POLITE_SLEEP_S)
    df.to_csv(RAW_DIR / f"yfinance_{ticker}_1h_{period}.csv")
    return df


def fetch_yf_minute(ticker: str, period: str = "8d") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1m", auto_adjust=False)
    time.sleep(POLITE_SLEEP_S)
    if len(df):
        df.to_csv(RAW_DIR / f"yfinance_{ticker}_1m_{period}.csv")
    return df


def describe_yf(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    idx = df.index
    deltas = idx.to_series().diff().dropna().dt.total_seconds()
    intraday = deltas[deltas < 6 * 3600]  # exclude overnight/weekend jumps
    return {
        "n": len(df),
        "tz": str(idx.tz),
        "first": idx.min().isoformat(),
        "last": idx.max().isoformat(),
        "n_distinct_trading_days": len(set(idx.date)),
        "calendar_span_days": (idx.max() - idx.min()).days,
        "intraday_delta_modes_s": sorted(intraday.value_counts().head(3).index.tolist()),
        "n_overnight_or_weekend_gaps": int((deltas >= 6 * 3600).sum()),
    }


_XNYS = xc.get_calendar("XNYS")
_FULL_SESSION_BARS = 7  # regular ~6.5h session: 09:30..15:30 hourly starts
_HALF_SESSION_BARS = 3  # early close ~3.5h session: 09:30, 10:30, 11:30
# Regular sessions run ~6.5h, early closes ~3.5h -- comfortably separated.
_HALF_SESSION_LEN_THRESHOLD = pd.Timedelta(hours=5)


def _session_open_close_et(date: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Real NYSE (XNYS) session open/close for `date`, in America/New_York,
    via `exchange_calendars` -- NOT hardcoded 09:30/16:00, so early closes
    (e.g. 13:00 on the day before Thanksgiving) come back correctly."""
    session = pd.Timestamp(date)
    open_utc = _XNYS.session_open(session)
    close_utc = _XNYS.session_close(session)
    return open_utc.tz_convert("America/New_York"), close_utc.tz_convert("America/New_York")


def _expected_bar_count(open_et: pd.Timestamp, close_et: pd.Timestamp) -> int:
    """7 bars on a regular session, 3 on an early close -- matches Yahoo's
    observed behavior (early closes get 3 hourly bars with the last one
    running 90 minutes to the close, not a 4th, 30-minute bar)."""
    session_len = close_et - open_et
    return _HALF_SESSION_BARS if session_len <= _HALF_SESSION_LEN_THRESHOLD else _FULL_SESSION_BARS


def restamp_to_bar_end(df: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[dt.date, int, int]]]:
    """yfinance intraday bars are labelled by their START time (the 09:30 bar
    covers 09:30-10:30, ...). This re-stamps the index to bar END time using
    the REAL NYSE session close per day (via `exchange_calendars`), not a
    hardcoded +30min/+60min or a "next bar's start" heuristic:

        end[i] = session_close(date(start[i]))              if bar i is the
                                                              LAST bar seen
                                                              that date
                 min(start[i] + 60min, session_close(...))   otherwise

    Why the last bar of the day needs its OWN rule (session close, even if
    that's more than 60 minutes away) rather than "+60min capped at close":
    on EARLY CLOSE days (e.g. 2025-11-28, 13:00 ET close), the last bar
    starts at 11:30 and must end at the real close, 13:00 -- a 90-minute bar.
    `min(11:30 + 60min, 13:00) = 12:30` is 30 minutes too early; only an
    explicit "last bar -> close" rule gets this right. (An earlier, wrong
    version of this function used a hardcoded +30min for the last bar, which
    is wrong for the same reason, just more so: it would have stamped this
    bar 12:00, 60 minutes early.)

    Why NON-last bars use "next scheduled hour, capped at close" rather than
    "next bar's actual start": on a day with a missing mid-day bar (e.g.
    2026-02-02, which only has bars at 09:30 and 13:30), the 09:30 bar's
    "next bar" is 13:30 -- stamping its end there would leak 3 hours into
    the future. `min(start + 60min, close)` is correct regardless of
    missing bars, because it never looks at what bar (if any) comes next.

    This is a step 4 (alignment) requirement: Polymarket's `t` is an "as of"
    timestamp (when the price was true), so stock bars must be compared using
    their END time too, not their start time, to avoid a subtle look-ahead
    (using a bar's start time would let the 09:30 bar's close price -- known
    only at 10:30, or later on an early close -- look available too early).

    Returns `(restamped_df, gap_days)`. `gap_days` lists `(date, n_bars_seen,
    n_bars_expected)` for every day with FEWER bars than expected after
    accounting for early closes via the XNYS calendar -- these are real
    missing-bar data gaps in the yfinance feed, not an artifact of this
    function, and are reported rather than silently re-stamped as if normal
    (note: because the LAST bar of such a gap day gets stamped to session
    close by the rule above, a gap day's last bar may end up covering an
    unusually long span -- exactly why these days are flagged separately
    rather than trusted at face value).
    """
    out = df.copy()
    starts = out.index
    dates = pd.Index(starts.date)
    unique_dates = dates.unique()
    open_close = {d: _session_open_close_et(d) for d in unique_dates}

    # Index (within `starts`) of the last bar observed for each date.
    last_pos_for_date: dict[dt.date, int] = {}
    for pos, d in enumerate(dates):
        last_pos_for_date[d] = pos  # last write wins -> last occurrence

    ends = []
    for i, (ts, d) in enumerate(zip(starts, dates, strict=True)):
        close_et = open_close[d][1]
        if i == last_pos_for_date[d]:
            ends.append(close_et)
        else:
            ends.append(min(ts + pd.Timedelta(minutes=60), close_et))
    out.index = pd.DatetimeIndex(ends, tz=starts.tz, name="ts_end")

    n_seen = pd.Series(dates).value_counts()
    gap_days: list[tuple[dt.date, int, int]] = []
    for date in unique_dates:
        open_et, close_et = open_close[date]
        n_expected = _expected_bar_count(open_et, close_et)
        if n_seen[date] < n_expected:
            gap_days.append((date, int(n_seen[date]), n_expected))
    gap_days.sort()
    return out, gap_days


def _self_test_restamp_to_bar_end() -> None:
    """Inline regression test (uses `exchange_calendars` for real XNYS
    session times, no yfinance/network) for `restamp_to_bar_end`'s two fixes:
    (a) early closes end at the REAL session close, not a hardcoded +30min,
    (b) a missing mid-day bar does not leak a too-late end stamp via a
    "next bar's start" heuristic. Also checks gap-day detection."""
    tz = "America/New_York"
    idx = pd.DatetimeIndex(
        [
            # Regular day: 2026-09-24, full 09:30-16:00 session, 7 bars.
            "2026-09-24 09:30",
            "2026-09-24 10:30",
            "2026-09-24 11:30",
            "2026-09-24 12:30",
            "2026-09-24 13:30",
            "2026-09-24 14:30",
            "2026-09-24 15:30",
            # Early close: 2025-11-28, 09:30-13:00 session, 3 bars.
            "2025-11-28 09:30",
            "2025-11-28 10:30",
            "2025-11-28 11:30",
            # Regular-session day with a missing mid-day bar: 2026-02-02.
            "2026-02-02 09:30",
            "2026-02-02 13:30",
        ],
        tz=tz,
    )
    df = pd.DataFrame({"Close": range(len(idx))}, index=idx)
    out, gap_days = restamp_to_bar_end(df)

    # (a) early close: last bar (11:30) must end at the REAL close, 13:00 ET
    # -- not the old hardcoded +30min (12:00).
    assert out.index[9] == pd.Timestamp("2025-11-28 13:00", tz=tz), out.index[9]

    # Regular day's last bar (15:30) ends at the 16:00 close.
    assert out.index[6] == pd.Timestamp("2026-09-24 16:00", tz=tz), out.index[6]

    # (b) missing mid-day bar: the 09:30 bar on 2026-02-02 is NOT the day's
    # last bar (13:30 follows it), so it must end at 10:30 (start+60min),
    # NOT at 13:30 (the next bar's start) -- the old "next bar's start" rule
    # would have leaked 3 hours into the future.
    assert out.index[10] == pd.Timestamp("2026-02-02 10:30", tz=tz), out.index[10]
    # The 13:30 bar IS this (gap) day's last observed bar, so per the "last
    # bar -> session close" rule it is stamped to the 16:00 close, same as
    # any other day's last bar -- an unusually long (2h30) bar, which is
    # exactly why this date is also flagged as a gap day below rather than
    # trusted at face value.
    assert out.index[11] == pd.Timestamp("2026-02-02 16:00", tz=tz), out.index[11]

    # (c) gap detection: 2026-02-02 has 2 bars but a regular session expects
    # 7 -> must be flagged. 2026-09-24 (7/7) and 2025-11-28 (3/3) must not.
    gap_dates = {d for d, _, _ in gap_days}
    assert pd.Timestamp("2026-02-02").date() in gap_dates, gap_days
    assert pd.Timestamp("2026-09-24").date() not in gap_dates, gap_days
    assert pd.Timestamp("2025-11-28").date() not in gap_dates, gap_days

    print("OK: restamp_to_bar_end uses real XNYS session close + flags gap days correctly")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    _self_test_clip_lookahead()
    _self_test_restamp_to_bar_end()

    print("=" * 70)
    print("1. Polymarket Gamma: resolve market metadata -> CLOB token ids")
    print("=" * 70)

    active_event = fetch_gamma_event(ACTIVE_EVENT_SLUG)
    active_market = find_submarket(active_event, ACTIVE_SUBMARKET_SLUG)
    active_yes = yes_token_id(active_market)
    print(f"ACTIVE event: {active_event['slug']!r} closed={active_event['closed']}")
    print(f"ACTIVE submarket: {active_market['slug']!r} clobTokenId(Yes)={active_yes}")

    resolved_event = fetch_gamma_event(RESOLVED_EVENT_SLUG)
    resolved_market = find_submarket(resolved_event, RESOLVED_SUBMARKET_SLUG)
    resolved_yes = yes_token_id(resolved_market)
    print(f"RESOLVED event: {resolved_event['slug']!r} closed={resolved_event['closed']}")
    print(
        f"RESOLVED submarket: {resolved_market['slug']!r} "
        f"clobTokenId(Yes)={resolved_yes} outcomePrices={resolved_market['outcomePrices']}"
    )

    print()
    print("=" * 70)
    print("2. CLOB prices-history: fidelity sweep, interval=max")
    print("=" * 70)
    for label, token in [("ACTIVE", active_yes), ("RESOLVED", resolved_yes)]:
        for fidelity in (1, 5, 60, 720):
            body = fetch_prices_history(
                token,
                fidelity=fidelity,
                interval="max",
                dump_name=f"clob_{label.lower()}_max_fid{fidelity}.json",
            )
            df = parse_clob_history(body)
            print(f"{label:8s} interval=max fidelity={fidelity:>3d} -> {describe_gaps(df)}")

    print()
    print("=" * 70)
    print("3. CLOB prices-history: LOOK-AHEAD LEAK repro on ACTIVE market")
    print("=" * 70)
    # Explicit startTs/endTs window well in the past, on the still-open
    # ACTIVE market. Expect: a trailing point stamped at *today*, after
    # end_ts -- a look-ahead leak if not clipped.
    leak_start = int(dt.datetime(2026, 7, 1, tzinfo=dt.UTC).timestamp())
    leak_end = int(dt.datetime(2026, 7, 15, tzinfo=dt.UTC).timestamp())
    for fidelity in (1, 60):
        body = fetch_prices_history(
            active_yes,
            fidelity=fidelity,
            start_ts=leak_start,
            end_ts=leak_end,
            dump_name=f"clob_active_lookahead_repro_fid{fidelity}.json",
        )
        raw_df = parse_clob_history(body)  # unclipped -- shows the leak
        clipped_df = parse_clob_history(body, start_ts=leak_start, end_ts=leak_end)
        leak_points = raw_df[raw_df["ts_utc"] > pd.Timestamp(leak_end, unit="s", tz="UTC")]
        raw_last = raw_df["ts_utc"].iloc[-1] if len(raw_df) else None
        clipped_last = clipped_df["ts_utc"].iloc[-1] if len(clipped_df) else None
        print(
            f"ACTIVE fidelity={fidelity:>3d} window=2026-07-01..07-15: "
            f"unclipped n={len(raw_df)} (last={raw_last}), "
            f"points after end_ts={len(leak_points)}, "
            f"clipped n={len(clipped_df)} (last={clipped_last})"
        )
        if len(leak_points):
            print(f"    LEAK CONFIRMED: {leak_points.to_dict('records')}")

    print()
    print("=" * 70)
    print("4. CLOB prices-history: max-range-per-request probe (fidelity 1 and 60)")
    print("=" * 70)
    # Use the resolved market's known lifetime window so results are
    # reproducible regardless of when this script is re-run.
    resolved_end = dt.datetime(2025, 9, 20, tzinfo=dt.UTC)
    for fidelity in (1, 60):
        for days in (14, 15, 16, 30):
            start_ts = int((resolved_end - dt.timedelta(days=days)).timestamp())
            end_ts = int(resolved_end.timestamp())
            body = fetch_prices_history(
                resolved_yes,
                fidelity=fidelity,
                start_ts=start_ts,
                end_ts=end_ts,
                dump_name=f"clob_resolved_range_probe_{days}d_fid{fidelity}.json",
            )
            print(f"  fidelity={fidelity:>2d} window={days:>2d}d -> status={body['status_code']}")

    print()
    print("=" * 70)
    print("5. CLOB prices-history: fine-grained data across a market's WHOLE life")
    print("=" * 70)
    # (a) Resolved market, EARLY in its life (not just right before
    # resolution) -- proves fine fidelity isn't only available near the end.
    early_start = int(dt.datetime(2025, 6, 1, tzinfo=dt.UTC).timestamp())
    early_end = int(dt.datetime(2025, 6, 14, tzinfo=dt.UTC).timestamp())
    early_body = fetch_prices_history(
        resolved_yes,
        fidelity=1,
        start_ts=early_start,
        end_ts=early_end,
        dump_name="clob_resolved_early_life_14d_fid1.json",
    )
    early_df = parse_clob_history(early_body, start_ts=early_start, end_ts=early_end)
    print(f"RESOLVED early-life (2025-06-01..06-14), fidelity=1 -> {describe_gaps(early_df)}")

    # (b) Active market, a 15-day window well before "now" -- same leak
    # window as section 3, now with the clip applied (the "real" result).
    active_mid_body = fetch_prices_history(
        active_yes,
        fidelity=1,
        start_ts=leak_start,
        end_ts=leak_end,
        dump_name="clob_active_mid_life_14d_fid1.json",
    )
    active_mid_df = parse_clob_history(active_mid_body, start_ts=leak_start, end_ts=leak_end)
    active_mid_gaps = describe_gaps(active_mid_df)
    print(f"ACTIVE mid-life (2026-07-01..07-15), fidelity=1, clipped -> {active_mid_gaps}")

    print()
    print("=" * 70)
    print("6. yfinance: 1h bars, TLT/SPY -- period is TRADING days, not calendar days")
    print("=" * 70)
    yf_hourly: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        df = fetch_yf_hourly(ticker, period="730d")
        yf_hourly[ticker] = df
        print(f"{ticker} 1h period=730d -> {describe_yf(df)}")
    # period=60d sanity check: ~60 trading days should span ~84 calendar days.
    df60 = yf.Ticker("TLT").history(period="60d", interval="1h", auto_adjust=False)
    time.sleep(POLITE_SLEEP_S)
    print(
        f"TLT 1h period=60d -> {describe_yf(df60)}  (expect ~60 trading days / ~84 calendar days)"
    )
    # Explicit start= beyond 730 CALENDAR days should fail -- confirms the
    # cap is calendar days, independent of the trading-day period= shorthand.
    beyond_cap_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=800)
    df_beyond = yf.Ticker("TLT").history(start=beyond_cap_start, interval="1h", auto_adjust=False)
    time.sleep(POLITE_SLEEP_S)
    print(
        f"TLT 1h explicit start=800 calendar days ago -> n={len(df_beyond)} "
        "(expect 0 / yfinance error: 'must be within the last 730 days')"
    )

    print()
    print("=" * 70)
    print("7. yfinance: 1m bars, TLT/SPY (request-window and lookback limits)")
    print("=" * 70)
    for ticker in TICKERS:
        df8 = fetch_yf_minute(ticker, period="8d")
        print(f"{ticker} 1m period=8d -> {describe_yf(df8)}")
    df30 = fetch_yf_minute("TLT", period="30d")
    print(f"TLT 1m period=30d (single request, expected to fail/empty) -> n={len(df30)}")

    # Explicit start/end probe for the 1m lookback window.
    now_utc = dt.datetime.now(dt.UTC)
    for days_back_start in (22, 29, 31):
        start = now_utc - dt.timedelta(days=days_back_start)
        stop = start + dt.timedelta(days=7)
        df = yf.Ticker("TLT").history(start=start, end=stop, interval="1m", auto_adjust=False)
        time.sleep(POLITE_SLEEP_S)
        print(f"TLT 1m window starting {days_back_start}d ago -> n={len(df)}")

    print()
    print("=" * 70)
    print("8. Chart: ACTIVE Fed market Yes probability vs TLT price (UTC, dual axis)")
    print("=" * 70)
    # Hourly probability for the active market, last ~30 days (the deepest
    # history available at fidelity=60 via interval=max, see section 2 above).
    active_hourly_body = fetch_prices_history(
        active_yes,
        fidelity=60,
        interval="max",
        dump_name="clob_active_chart_fid60.json",
    )
    # interval=max has no explicit start_ts/end_ts, so there is nothing to
    # clip against here (the look-ahead guard in section 3 applies to
    # explicit-window requests, not interval=max, which by construction ends
    # "now").
    prob_df = parse_clob_history(active_hourly_body)

    # Re-stamp TLT bars from START time to END time (see restamp_to_bar_end
    # docstring) *before* converting tz, so the local-trading-day grouping is
    # correct, then convert to UTC for the shared axis.
    tlt_df, tlt_gap_days = restamp_to_bar_end(yf_hourly["TLT"])
    tlt_df.index = tlt_df.index.tz_convert("UTC")
    tlt_df = tlt_df.reset_index().rename(columns={"ts_end": "ts_utc", "Close": "close"})
    print("TLT 1h gap days (fewer bars than expected, after early-close adjustment):")
    for date, n_seen, n_expected in tlt_gap_days:
        print(f"  {date}: saw {n_seen} bars, expected {n_expected}")

    # Overlap window: last available day of the shorter series back N days.
    window_start = max(prob_df["ts_utc"].min(), tlt_df["ts_utc"].min())
    window_end = min(prob_df["ts_utc"].max(), tlt_df["ts_utc"].max())
    prob_plot = prob_df[(prob_df["ts_utc"] >= window_start) & (prob_df["ts_utc"] <= window_end)]
    tlt_plot = tlt_df[(tlt_df["ts_utc"] >= window_start) & (tlt_df["ts_utc"] <= window_end)]
    print(f"Chart overlap window: {window_start} -> {window_end}")
    print(
        f"  probability points: {len(prob_plot)} (Polymarket trades ~24/7, hourly "
        f"fidelity -> up to 24/day), TLT points: {len(tlt_plot)} "
        "(regular session only -> ~7 bars/trading day, ~5 trading days/week)"
    )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=prob_plot["ts_utc"],
            y=prob_plot["probability"],
            name=f"Polymarket: {active_market['groupItemTitle']} (Yes)",
            mode="lines",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=tlt_plot["ts_utc"],
            y=tlt_plot["close"],
            name="TLT close (1h bars, end-stamped)",
            mode="lines",
        ),
        secondary_y=True,
    )
    fig.update_layout(
        title=(
            "Step 1 data check: Polymarket FOMC Oct-2026 'No change' Yes probability "
            "vs TLT close, UTC"
        ),
        xaxis_title="UTC time",
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_yaxes(title_text="P(Yes)", range=[0, 1], secondary_y=False)
    fig.update_yaxes(title_text="TLT close (USD)", secondary_y=True)

    out_path = Path(__file__).resolve().parent / "step1_data_check.html"
    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"Chart written to {out_path}")

    print()
    print("Done. See printed stats above + data/scratch/step1/*.json|csv for evidence.")


if __name__ == "__main__":
    main()

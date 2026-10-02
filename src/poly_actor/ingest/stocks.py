"""yfinance 1h bar ingestion.

Source: yfinance `Ticker.history(start=, end=, interval="1h", auto_adjust=False)`.
Native timezone: America/New_York for US equities/ETFs (regular session only, 09:30-16:00;
BTC-USD is UTC, 24/7). Bars are labelled by their START time. The raw files keep that
start-stamped index (the same instants, stored as tz-aware UTC). Re-stamping to bar end
(XNYS session close, early closes) is step 4's job, not done here.
Resolution: 1 hour. Unadjusted prices (auto_adjust=False) so past rows never change when
dividends are paid later (raw is immutable).

Limits handled:
- explicit start=/end= for 1h data may reach back at most 730 CALENDAR days (we use 729).
- yfinance fails silently with an empty frame: an empty frame is a failure whenever the
  window contains an NYSE session (always for BTC-USD).
- Rows whose OHLC are all NaN (e.g. TLT 2026-02-02 09:30) are kept but flagged
  `ohlc_all_nan=True`; raw stays faithful, later steps drop them.
- Only completed ET days with a 1-day lag are ingested (end = ET midnight of YESTERDAY, so the
  last stored day is the day before yesterday): Yahoo revises recent bars, so they are frozen
  only a day later. No still-forming bar is ever stored; same-day re-runs are no-ops.
- Bar-count check (`stock_gap_table`): each XNYS session should have 7 hourly bars (3 on early
  closes: yfinance omits the 12:30 bar), BTC-USD 24 per UTC day. Short days are reported, never
  fatal. Known upstream holes: all equities 2026-01-30 11:30 ET .. 2026-02-02 13:30 ET; BTC-USD
  2025-10-28 and 2025-11-29.

Raw layout (add-only): data/raw/stocks/<ticker>/<start_ts>_<end_ts>.parquet and
data/raw/stocks/_manifest.jsonl.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from poly_actor.config import RAW_DIR
from poly_actor.ingest.common import (
    DAY,
    IngestError,
    Interval,
    Manifest,
    base_record,
    failed_record,
    iso,
    sha256_hex,
    subtract_intervals,
    tile,
    to_epoch,
    utcnow,
    write_parquet_once,
)
from poly_actor.pairs import ET

RAW_SUBDIR = "stocks"
MAX_LOOKBACK_DAYS = 729  # yfinance cap is 730 calendar days
CHUNK_DAYS = 180
OHLC = ["open", "high", "low", "close"]


class EmptyFrameError(IngestError):
    """yfinance returned no rows where rows were expected (silent failure mode)."""


def parse_bars(df: pd.DataFrame, start_ts: int, end_ts: int) -> pd.DataFrame:
    """yfinance history frame -> columns ts (UTC, bar START), open, high, low, close,
    volume, ohlc_all_nan. Clipped to start_ts <= ts < end_ts, de-duplicated on ts, sorted.
    May return zero rows; the caller decides whether that is a failure."""
    cols = {c.lower(): c for c in df.columns}
    for need in (*OHLC, "volume"):
        if need not in cols:
            raise ValueError(f"yfinance frame missing column {need!r}")
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        raise ValueError("yfinance index is naive; refusing to guess its timezone")
    out = pd.DataFrame({"ts": idx.tz_convert("UTC")})
    for c in (*OHLC, "volume"):
        out[c] = df[cols[c]].to_numpy(dtype="float64")
    out["ohlc_all_nan"] = out[OHLC].isna().all(axis=1)
    t = (out["ts"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)  # epoch seconds
    out = out[(t >= start_ts) & (t < end_ts)]
    out = out.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)
    return out


def fetch_bars(
    ticker: str,
    start_ts: int,
    end_ts: int,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Thin network call: the raw yfinance frame for [start, end). Retries on exceptions
    or empty frames with short backoff; the caller checks row counts."""
    import yfinance as yf

    start = datetime.fromtimestamp(start_ts, UTC)
    end = datetime.fromtimestamp(end_ts, UTC)
    last: Exception | None = None
    df = pd.DataFrame()
    for attempt in range(3):
        try:
            df = yf.Ticker(ticker).history(
                start=start, end=end, interval="1h", auto_adjust=False, actions=False
            )
            if len(df):
                return df
        except Exception as exc:  # yfinance raises assorted types
            last = exc
        if attempt < 2:  # no pointless sleep after the last attempt
            sleep(2.0 * 2**attempt)
    if last:
        raise IngestError(f"yfinance error for {ticker}: {last!r}")
    return df


def et_midnight_epoch(d) -> int:
    """00:00 America/New_York on date d -> epoch seconds."""
    return to_epoch(datetime(d.year, d.month, d.day, tzinfo=ET))


LAG_DAYS = 1  # freeze a bar only once its ET day is a full day old (Yahoo revisions)


def target_interval(window_start_ts: int, asof: datetime) -> Interval:
    """[max(window start, asof - 729d) floored to ET midnight, ET midnight of yesterday).
    Yesterday's midnight = end of the previous completed ET day minus the 1-day lag."""
    today = asof.astimezone(ET).date()
    end = et_midnight_epoch(today - timedelta(days=LAG_DAYS))
    cap = et_midnight_epoch(today - timedelta(days=MAX_LOOKBACK_DAYS))
    start_day = datetime.fromtimestamp(max(window_start_ts, cap), ET).date()
    return (et_midnight_epoch(start_day), end)


def expects_rows(ticker: str, start_ts: int, end_ts: int) -> bool:
    """BTC-USD trades 24/7; equities need at least one XNYS session in the window."""
    if ticker.endswith("-USD"):
        return True
    import exchange_calendars as xcals

    cal = xcals.get_calendar("XNYS")
    s = datetime.fromtimestamp(start_ts, ET).date()
    e = datetime.fromtimestamp(end_ts - 1, ET).date()
    return len(cal.sessions_in_range(pd.Timestamp(s), pd.Timestamp(e))) > 0


def expected_bars(early: bool) -> int:
    return 3 if early else 7


def stock_gap_table(bars: pd.DataFrame, end_ts: int | None = None) -> pd.DataFrame:
    """Days with fewer bars than expected. `bars` has columns ticker, ts (tz-aware).

    Equities: every XNYS session from the ticker's first bar's ET date through the date of
    `end_ts - 1` (default: last bar) expects 7 bars, 3 on early closes. BTC-USD: every UTC day
    strictly between its first and last (partial) days expects 24.
    Returns columns ticker, date, kind, expected, actual, missing (missing > 0 only)."""
    import exchange_calendars as xcals

    cols = ["ticker", "date", "kind", "expected", "actual", "missing"]
    if bars.empty:
        return pd.DataFrame(columns=cols)
    cal = xcals.get_calendar("XNYS")
    early = {d.date() for d in cal.early_closes}
    rows: list[list] = []
    for tk, g in bars.groupby("ticker"):
        ts = pd.DatetimeIndex(g["ts"]).tz_convert("UTC")
        if tk.endswith("-USD"):
            days = pd.Series(ts.date).value_counts()
            lo, hi = ts.min().date(), ts.max().date()
            for d in pd.date_range(lo, hi, freq="D").date:
                if d in (lo, hi):
                    continue
                n = int(days.get(d, 0))
                if n < 24:
                    rows.append([tk, d, "utc_day", 24, n, 24 - n])
            continue
        et = ts.tz_convert(ET)
        days = pd.Series(et.date).value_counts()
        lo = et.min().date()
        hi = (
            datetime.fromtimestamp(end_ts - 1, ET).date() if end_ts is not None else et.max().date()
        )
        for sess in cal.sessions_in_range(pd.Timestamp(lo), pd.Timestamp(hi)):
            d = sess.date()
            exp = expected_bars(d in early)
            n = int(days.get(d, 0))
            if n < exp:
                rows.append([tk, d, "xnys_session", exp, n, exp - n])
    return pd.DataFrame(rows, columns=cols)


@dataclass
class StockStats:
    calls: int = 0
    planned_calls: int = 0
    rows: int = 0
    nan_rows: int = 0
    failures: list[dict] = field(default_factory=list)


def manifest_for(raw_dir: Path = RAW_DIR) -> Manifest:
    return Manifest(raw_dir / RAW_SUBDIR / "_manifest.jsonl")


def run_stocks(
    tickers: list[str],
    window_start_ts: int,
    *,
    raw_dir: Path = RAW_DIR,
    fetch: Callable[[str, int, int], pd.DataFrame] = fetch_bars,
    dry_run: bool = False,
    pause: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    asof: datetime | None = None,
    now: Callable[[], Any] = utcnow,
    log: Callable[[str], None] = lambda s: None,
) -> StockStats:
    asof = asof or now()
    target = target_interval(window_start_ts, asof)
    manifest = manifest_for(raw_dir)
    cov: dict[str, list[Interval]] = {}
    for r in manifest.read():
        if r.get("status") == "ok":
            cov.setdefault(r["ticker"], []).append((r["start_ts"], r["end_ts"]))
    stats = StockStats()
    for tk in tickers:
        wins: list[Interval] = []
        for s, e in subtract_intervals([target], cov.get(tk, [])):
            wins.extend(tile(s, e, CHUNK_DAYS * DAY))
        stats.planned_calls += len(wins)
        if dry_run:
            continue
        for s, e in wins:
            if stats.calls:
                sleep(pause)
            stats.calls += 1
            rec = base_record(
                now, source="yfinance", ticker=tk, interval="1h", start_ts=s, end_ts=e
            )
            try:
                raw = fetch(tk, s, e)
                df = parse_bars(raw, s, e)
                if len(df) == 0 and expects_rows(tk, s, e):
                    raise EmptyFrameError(f"empty frame for {tk} {iso(s)}..{iso(e)}")
            except (IngestError, ValueError) as exc:
                rec = failed_record(rec, exc)
                manifest.append(rec)
                stats.failures.append(rec)
                log(f"FAIL {tk} {iso(s)}: {exc}")
                break
            path = raw_dir / RAW_SUBDIR / tk / f"{s}_{e}.parquet"
            wrote = write_parquet_once(df, path) if len(df) else False
            n_nan = int(df["ohlc_all_nan"].sum()) if len(df) else 0
            rec.update(
                status="ok",
                n_rows=len(df),
                n_nan_rows=n_nan,
                sha256=sha256_hex(raw.to_csv().encode()),
                file=str(path.relative_to(raw_dir)).replace("\\", "/") if len(df) else None,
                file_existed=bool(len(df)) and not wrote,
            )
            manifest.append(rec)
            cov.setdefault(tk, []).append((s, e))
            stats.rows += len(df)
            stats.nan_rows += n_nan
            log(f"{tk} {iso(s)}..{iso(e)} rows={len(df)} nan={n_nan}")
    return stats

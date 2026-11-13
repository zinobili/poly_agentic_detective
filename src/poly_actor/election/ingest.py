"""Election-study ingestion: Polymarket CLOB specs and yfinance bars, add-only raw files.

Polymarket reuses `poly_actor.ingest.polymarket` (tiling, clipping to [start, end), manifest,
empty-window handling). Raw lands in data/raw/election/polymarket/<token>/fid=<f>/.

yfinance (one file per ticker/interval/window) lands in
data/raw/election/yf/<interval>/<ticker>/<start_ts>_<end_ts>.parquet with manifest
data/raw/election/yf/_manifest.jsonl. Native timezone America/New_York (futures and vol indices
included); resolution 1d (stamped ET midnight, auto_adjust=True), 1h (start-stamped, unadjusted,
regular session for equities), 5m futures (start-stamped). Stored timestamps are tz-aware UTC and
still bar-START stamps: bar-end stamping is `panel.py`'s job.

Pure functions: `polymarket_specs`, `yf_tasks`. Network: `fetch_yf` (thin, retries on exceptions and
on silent empty frames). Idempotent: coverage comes from the manifests, so a re-run fetches
only missing windows (zero calls once everything is covered).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from poly_actor.election.config import RAW_ELECTION, ElectionConfig
from poly_actor.ingest import polymarket, stocks
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
    utcnow,
    write_parquet_once,
)

YF_SUBDIR = "yf"
CLOSE_PAD_S = 3600  # CLOB points keep arriving a few seconds after Gamma's closedTime
CHUNK_DAYS = {"1d": 4000, "1h": 180, "5m": 30}


def polymarket_specs(cfg: ElectionConfig) -> list[polymarket.TokenSpec]:
    """Specs for the 4 election tokens (fid 60 + fid 10 whole life, fid 1 event window) and the 7
    moratorium tokens (fid 60 from creation to study end)."""
    specs: list[polymarket.TokenSpec] = []
    for name, m in cfg.signals.items():
        end = (m.closed_s or cfg.data_end_s) + CLOSE_PAD_S
        life = (m.created_s, m.closed_s or cfg.data_end_s)
        whole = [(cfg.pm_start_s, end)]
        for fid in (60, 10):
            specs.append(polymarket.TokenSpec(m.token_id, fid, whole, {name}, "election", life))
        lo, hi = cfg.fid1_window
        specs.append(
            polymarket.TokenSpec(m.token_id, 1, [(lo, min(hi, end))], {name}, "election", life)
        )
    for name, m in cfg.moratorium.items():
        life = (m.created_s, cfg.data_end_s)
        iv = [(m.created_s, cfg.data_end_s)]
        specs.append(polymarket.TokenSpec(m.token_id, 60, iv, {name}, "moratorium", life))
    return specs


@dataclass(frozen=True)
class YfTask:
    ticker: str
    interval: str  # "1d" | "1h" | "5m"
    start_s: int
    end_s: int
    auto_adjust: bool


def yf_tasks(cfg: ElectionConfig) -> list[YfTask]:
    """Everything yfinance has to deliver (see the step 8 data table)."""
    out: list[YfTask] = []
    for tk in cfg.equity_tickers:
        out.append(YfTask(tk, "1d", cfg.data_start_s, cfg.data_end_s, True))
        out.append(YfTask(tk, "1h", cfg.data_start_s, cfg.data_end_s, False))
    for tk in cfg.futures:
        out.append(YfTask(tk, "5m", *cfg.fut5m_window, False))
        out.append(YfTask(tk, "1h", cfg.data_start_s, cfg.data_end_s, False))
    for tk in cfg.vol_indices:
        out.append(YfTask(tk, "1d", cfg.vol_start_s, cfg.data_end_s, True))
    return out


YF_ATTEMPTS = 4  # one more than milestone 1: 5m and 1d pulls hit more silent empty frames


def fetch_yf(
    task: YfTask,
    start_s: int,
    end_s: int,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Thin network call for one window: `stocks.fetch_bars` (the single retry/backoff loop)
    at this task's interval and adjustment. The caller checks row counts."""
    return stocks.fetch_bars(
        task.ticker,
        start_s,
        end_s,
        sleep,
        interval=task.interval,
        auto_adjust=task.auto_adjust,
        attempts=YF_ATTEMPTS,
    )


@dataclass
class YfStats:
    planned_calls: int = 0
    calls: int = 0
    rows: int = 0
    failures: list[dict] = field(default_factory=list)


def yf_manifest(raw_dir: Path = RAW_ELECTION) -> Manifest:
    return Manifest(raw_dir / YF_SUBDIR / "_manifest.jsonl")


def yf_raw_path(raw_dir: Path, task: YfTask, s: int, e: int) -> Path:
    return raw_dir / YF_SUBDIR / task.interval / task.ticker / f"{s}_{e}.parquet"


def plan_yf(tasks: list[YfTask], records: list[dict]) -> list[tuple[YfTask, list[Interval]]]:
    """Missing windows per task (covered = manifest status 'ok'), tiled by interval."""
    cov: dict[tuple[str, str], list[Interval]] = {}
    for r in records:
        if r.get("status") == "ok":
            cov.setdefault((r["ticker"], r["interval"]), []).append((r["start_ts"], r["end_ts"]))
    plans = []
    for t in tasks:
        wins: list[Interval] = []
        for s, e in subtract_intervals([(t.start_s, t.end_s)], cov.get((t.ticker, t.interval), [])):
            wins.extend(tile(s, e, CHUNK_DAYS[t.interval] * DAY))
        if wins:
            plans.append((t, wins))
    return plans


def run_yf(
    tasks: list[YfTask],
    *,
    raw_dir: Path = RAW_ELECTION,
    fetch: Callable[[YfTask, int, int], pd.DataFrame] = fetch_yf,
    dry_run: bool = False,
    pause: float = 0.3,
    workers: int = 1,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], Any] = utcnow,
    log: Callable[[str], None] = lambda s: None,
) -> YfStats:
    """Fetch the missing windows of every task. A failed window is logged (status=failed), not
    covered, and abandons that task's remaining windows; other tasks continue."""
    manifest = yf_manifest(raw_dir)
    plans = plan_yf(tasks, manifest.read())
    stats = YfStats(planned_calls=sum(len(w) for _, w in plans))
    if dry_run:
        return stats
    lock = threading.Lock()

    def one_task(task: YfTask, wins: list[Interval]) -> None:
        for i, (s, e) in enumerate(wins):
            if i:
                sleep(pause)
            rec = base_record(
                now, source="yfinance", ticker=task.ticker, interval=task.interval,
                start_ts=s, end_ts=e,
            )  # fmt: skip
            with lock:
                stats.calls += 1
            try:
                raw = fetch(task, s, e)
                df = stocks.parse_bars(raw, s, e)
                if len(df) == 0 and stocks.expects_rows(task.ticker, s, e):
                    raise stocks.EmptyFrameError(f"empty frame {task.ticker} {iso(s)}..{iso(e)}")
            except (IngestError, ValueError) as exc:
                with lock:
                    manifest.append(failed_record(rec, exc))
                    stats.failures.append(rec)
                log(f"FAIL {task.ticker} {task.interval} {iso(s)}: {exc}")
                return
            path = yf_raw_path(raw_dir, task, s, e)
            wrote = write_parquet_once(df, path) if len(df) else False
            rec.update(
                status="ok", n_rows=len(df), sha256=sha256_hex(raw.to_csv().encode()),
                file=str(path.relative_to(raw_dir)) if len(df) else None,
                file_existed=bool(len(df)) and not wrote,
            )  # fmt: skip
            with lock:
                manifest.append(rec)
                stats.rows += len(df)
            log(f"{task.ticker} {task.interval} {iso(s)}..{iso(e)} rows={len(df)}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for fut in [pool.submit(one_task, t, w) for t, w in plans]:
            fut.result()
    return stats


def read_yf_bars(raw_dir: Path, ticker: str, interval: str) -> pd.DataFrame:
    """All stored bars of one ticker/interval (columns of `stocks.parse_bars`), sorted and
    de-duplicated on ts. Empty frame when nothing is stored."""
    files = sorted((raw_dir / YF_SUBDIR / interval / ticker).glob("*.parquet"))
    if not files:
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "ohlc_all_nan"]
        )
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)


def read_clob_points(raw_dir: Path, token_id: str) -> pd.DataFrame:
    """All stored CLOB points of one token: columns t (epoch s), p, fidelity."""
    frames = []
    for d in sorted((raw_dir / polymarket.RAW_SUBDIR / token_id).glob("fid=*")):
        fid = int(d.name.split("=")[1])
        for f in sorted(d.glob("*.parquet")):
            df = pd.read_parquet(f, columns=["t", "p"])
            df["fidelity"] = fid
            frames.append(df)
    if not frames:
        return pd.DataFrame({"t": [], "p": [], "fidelity": []}).astype(
            {"t": "int64", "p": "float64", "fidelity": "int64"}
        )
    return pd.concat(frames, ignore_index=True)

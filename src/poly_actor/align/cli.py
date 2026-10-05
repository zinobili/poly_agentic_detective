"""CLI: python -m poly_actor.align run [--pairs a,b] | report

`run` builds data/clean/panel_<pair>.parquet and data/clean/align_summary.json from data/raw.
`report` prints the summary (sizes and flag rates) from the existing panels.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from poly_actor.align import pipeline, report
from poly_actor.config import CLEAN_DIR

SUMMARY_NAME = "align_summary.json"
LOCK_TIMEOUT_S = 30.0


def _summary_path(clean_dir: Path) -> Path:
    """Location of the merged per-pair summary."""
    return clean_dir / SUMMARY_NAME


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    """Build the chosen pairs' panels and merge their summaries into align_summary.json."""
    cfg = pipeline.load_config()
    known = pipeline.pair_ids(cfg)
    chosen = args.pairs.split(",") if args.pairs else known
    unknown = sorted(set(chosen) - set(known))
    if unknown:
        _err(f"unknown pair(s): {unknown}; known: {known}")
        return 2
    clean_dir = Path(args.clean_dir)
    con = pipeline.connect_raw()
    summaries: dict[str, dict] = {}
    for pair_id in chosen:
        t0 = time.perf_counter()
        panel, diag = pipeline.run_pair(cfg, pair_id, con, clean_dir)
        summaries[pair_id] = {**report.summarize(panel), **diag}
        print(f"{pair_id}: {len(panel)} rows in {time.perf_counter() - t0:.0f}s", flush=True)
    _merge_summary(clean_dir, summaries)
    print(report.format_report(summaries))
    return 0


@contextmanager
def _summary_lock(clean_dir: Path, timeout_s: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Exclusive lock file so two concurrent runs cannot lose each other's summary entries."""
    clean_dir.mkdir(parents=True, exist_ok=True)
    lock = clean_dir / (SUMMARY_NAME + ".lock")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock} held over {timeout_s:.0f}s; remove if stale") from None
            time.sleep(0.2)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _merge_summary(clean_dir: Path, new: dict[str, dict]) -> None:
    """Read-modify-write of the summary under the lock."""
    with _summary_lock(clean_dir):
        existing = _read_summary(clean_dir)
        existing.update(new)
        _write_summary(clean_dir, existing)


def _write_summary(clean_dir: Path, summary: dict) -> None:
    """Temp file plus rename, like the panels: a crash never leaves a half-written summary."""
    path = _summary_path(clean_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, path)


def _read_summary(clean_dir: Path) -> dict:
    path = _summary_path(clean_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt summary file {path}: {exc}") from exc


def cmd_report(args: argparse.Namespace) -> int:
    """Print panel sizes and flag rates from the existing panels."""
    clean_dir = Path(args.clean_dir)
    summaries: dict[str, dict] = {}
    for path in sorted(clean_dir.glob("panel_*.parquet")):
        pair_id = path.stem.removeprefix("panel_")
        summaries[pair_id] = report.summarize(pd.read_parquet(path))
    if not summaries:
        _err(f"no panels in {clean_dir}; run `python -m poly_actor.align run` first")
        return 2
    print(report.format_report(summaries))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m poly_actor.align`."""
    parser = argparse.ArgumentParser(prog="poly_actor.align", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="build the per-pair hourly panels from data/raw")
    run.add_argument("--pairs", help="comma-separated pair ids (default: all)")
    run.add_argument("--clean-dir", default=str(CLEAN_DIR), help="output directory")
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report", help="print panel sizes and flag rates")
    rep.add_argument("--clean-dir", default=str(CLEAN_DIR), help="directory with panels")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)

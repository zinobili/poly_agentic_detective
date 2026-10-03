"""CLI: python -m poly_actor.align run [--pairs a,b] | report

`run` builds data/clean/panel_<pair>.parquet and data/clean/align_summary.json from data/raw.
`report` prints the summary (sizes and flag rates) from the existing panels.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd

from poly_actor.align import pipeline, report
from poly_actor.config import CLEAN_DIR

SUMMARY_NAME = "align_summary.json"


def _summary_path(clean_dir: Path) -> Path:
    return clean_dir / SUMMARY_NAME


def cmd_run(args: argparse.Namespace) -> int:
    cfg = pipeline.load_config()
    known = pipeline.pair_ids(cfg)
    chosen = args.pairs.split(",") if args.pairs else known
    unknown = sorted(set(chosen) - set(known))
    if unknown:
        print(f"unknown pair(s): {unknown}; known: {known}")
        return 2
    clean_dir = Path(args.clean_dir)
    con = pipeline.connect_raw()
    summaries: dict[str, dict] = {}
    for pair_id in chosen:
        t0 = time.time()
        panel, diag = pipeline.run_pair(cfg, pair_id, con, clean_dir, args.strict_asof)
        key = f"{pair_id}__strict" if args.strict_asof else pair_id
        summaries[key] = {**report.summarize(panel), **diag}
        print(f"{pair_id}: {len(panel)} rows in {time.time() - t0:.0f}s", flush=True)
    existing = _read_summary(clean_dir)
    existing.update(summaries)
    _write_summary(clean_dir, existing)
    print(report.format_report(summaries))
    return 0


def _write_summary(clean_dir: Path, summary: dict) -> None:
    """Temp file plus rename, like the panels: a crash never leaves a half-written summary."""
    path = _summary_path(clean_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, path)


def _read_summary(clean_dir: Path) -> dict:
    path = _summary_path(clean_dir)
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def cmd_report(args: argparse.Namespace) -> int:
    clean_dir = Path(args.clean_dir)
    summaries: dict[str, dict] = {}
    for path in sorted(clean_dir.glob("panel_*.parquet")):
        pair_id = path.stem.removeprefix("panel_")
        summaries[pair_id] = report.summarize(pd.read_parquet(path))
    if not summaries:
        print(f"no panels in {clean_dir}; run `python -m poly_actor.align run` first")
        return 2
    print(report.format_report(summaries))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poly_actor.align", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="build the per-pair hourly panels from data/raw")
    run.add_argument("--pairs", help="comma-separated pair ids (default: all)")
    run.add_argument(
        "--strict-asof",
        action="store_true",
        help="tolerance 0 (no observation stamped after the instant); writes panel_<pair>_strict",
    )
    run.add_argument("--clean-dir", default=str(CLEAN_DIR), help="output directory")
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report", help="print panel sizes and flag rates")
    rep.add_argument("--clean-dir", default=str(CLEAN_DIR), help="directory with panels")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)

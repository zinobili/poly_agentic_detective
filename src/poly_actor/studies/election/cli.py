"""CLI: python -m poly_actor.studies.election <command>

Commands: ingest [--workers N] [--dry-run] [--only pm|yf] | panel | analyse | publish | report
"""

from __future__ import annotations

import argparse

from poly_actor.core.ingest import polymarket
from poly_actor.core.ingest.common import IngestError, ingest_lock
from poly_actor.studies.election import ingest as ing
from poly_actor.studies.election.config import (
    CLEAN_ELECTION,
    RAW_ELECTION,
    ElectionConfig,
    load_config,
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.dry_run:
        return _ingest(args, cfg)
    try:
        with ingest_lock(RAW_ELECTION):
            return _ingest(args, cfg)
    except IngestError as exc:
        _log(str(exc))
        return 3


def _ingest(args: argparse.Namespace, cfg: ElectionConfig) -> int:
    fails = 0
    if args.only in (None, "pm"):
        st = polymarket.run_polymarket(
            ing.polymarket_specs(cfg), raw_dir=RAW_ELECTION, dry_run=args.dry_run,
            pause=args.pause, log=_log, workers=args.workers,
        )  # fmt: skip
        _log(
            f"polymarket: planned calls={st.planned_calls} calls={st.calls} rows={st.rows} "
            f"failures={len(st.failures)} empty_pending={st.empty_pending}"
        )
        fails += len(st.failures)
    if args.only in (None, "yf"):
        ys = ing.run_yf(
            ing.yf_tasks(cfg), raw_dir=RAW_ELECTION, dry_run=args.dry_run,
            pause=args.pause, workers=args.workers, log=_log,
        )  # fmt: skip
        _log(
            f"yfinance: planned calls={ys.planned_calls} calls={ys.calls} rows={ys.rows} "
            f"failures={len(ys.failures)}"
        )
        fails += len(ys.failures)
    return 1 if fails else 0


def cmd_panel(args: argparse.Namespace) -> int:
    from poly_actor.studies.election.panel import build_all

    cov = build_all(load_config(), RAW_ELECTION, CLEAN_ELECTION)
    _log(f"wrote {len(cov['tables'])} tables + coverage.json to {CLEAN_ELECTION}")
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    from poly_actor.studies.election.analysis import analyse

    out = CLEAN_ELECTION / "results"
    res = analyse(load_config(), CLEAN_ELECTION, out)
    _log(res["headline"]["sentence"])
    _log(f"wrote {out / 'results.json'} and {len(res['series'])} series")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from poly_actor.config import ROOT
    from poly_actor.studies.election.analysis import publish

    files = publish(CLEAN_ELECTION / "results", ROOT / "reports" / "election")
    _log(f"published {len(files)} files to reports/election/")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from poly_actor.studies.election import findings
    from poly_actor.studies.election.report_load import bundle_dir

    try:
        out = findings.write_report(bundle_dir())
    except findings.ReportInputError as exc:
        _log(f"{exc}; run `analyse` and `publish` first")
        return 2
    _log(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="poly_actor.studies.election")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="pull raw data (idempotent, incremental)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", choices=["pm", "yf"])
    p.add_argument("--pause", type=float, default=0.25)
    p.set_defaults(fn=cmd_ingest)
    q = sub.add_parser("panel", help="build clean parquet panels + coverage.json")
    q.set_defaults(fn=cmd_panel)
    a = sub.add_parser("analyse", help="run the pre-registered analysis -> results/")
    a.set_defaults(fn=cmd_analyse)
    b = sub.add_parser("publish", help="copy results/ to reports/election/")
    b.set_defaults(fn=cmd_publish)
    r = sub.add_parser("report", help="reports/election/ -> docs/studies/election/findings.md")
    r.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)

"""CLI: python -m poly_actor.ingest run [--pairs a,b] [--dry-run] [--min-gap-hours H] | report"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime

import yaml

from poly_actor.config import CONFIG_DIR, DATA_DIR, RAW_DIR
from poly_actor.ingest import polymarket, stocks, targets
from poly_actor.ingest.common import IngestError, ingest_lock, utcnow

SCRATCH = DATA_DIR / "scratch" / "step3"


def _load_cfg(path=None) -> dict:
    with open(path or CONFIG_DIR / "pairs.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _log(msg: str) -> None:
    print(msg, flush=True)


def cmd_run(args) -> int:
    if args.dry_run:
        return _run(args)
    try:
        with ingest_lock(RAW_DIR):
            return _run(args)
    except IngestError as exc:
        _log(str(exc))
        return 3


def _write_scratch(df, name: str) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    df.to_csv(SCRATCH / name, index=False)


def _run(args) -> int:
    cfg = _load_cfg()
    pairs = args.pairs.split(",") if args.pairs else None
    unknown = set(pairs or []) - set(targets.pair_ids(cfg))
    if unknown:
        _log(f"unknown pair(s): {sorted(unknown)}; known: {targets.pair_ids(cfg)}")
        return 2
    asof: datetime = (
        datetime.fromisoformat(args.asof.replace("Z", "+00:00")) if args.asof else utcnow()
    )
    if asof.tzinfo is None:
        _log("--asof must be tz-aware (e.g. 2026-10-01T12:00:00Z)")
        return 2
    t0 = time.time()
    specs = targets.build_token_specs(cfg, int(asof.timestamp()), pairs)
    tickers = targets.stock_tickers(cfg, pairs)
    wstart = targets.window_start(cfg)
    kw = {"raw_dir": RAW_DIR, "dry_run": args.dry_run, "pause": args.pause, "log": _log}

    do_pm = args.only in (None, "polymarket")
    do_st = args.only in (None, "stocks")
    pm = polymarket.run_polymarket(specs, **kw, workers=args.workers) if do_pm else None
    min_gap = int(args.min_gap_hours * 3600)
    backfill = do_pm and not args.no_backfill
    st = (
        stocks.run_stocks(tickers, wstart, asof=asof, **{**kw, "pause": max(args.pause, 0.5)})
        if do_st
        else None
    )
    bf = None
    bf_specs: list[polymarket.TokenSpec] = []
    if backfill:  # after the life pass, so its fresh data is visible to the gap finder
        bf_specs = polymarket.backfill_specs(RAW_DIR, specs, min_gap)
        bf = polymarket.run_polymarket(bf_specs, **kw, workers=args.workers)

    if args.dry_run:
        _log(f"DRY RUN (no network). asof={asof.isoformat()}")
        if pm:
            by_pair: dict[str, int] = defaultdict(int)
            by_fid: dict[int, int] = defaultdict(int)
            for sp in specs:
                n = pm.planned_by_key.get((sp.token_id, sp.fidelity), 0)
                by_fid[sp.fidelity] += n
                for p in sp.pairs:
                    by_pair[p] += n  # token shared by several pairs counts in each
            _log(f"polymarket: {len(specs)} (token, fidelity) specs, {pm.planned_calls} calls")
            for p, n in sorted(by_pair.items()):
                _log(f"  pair {p}: {n}")
            for f, n in sorted(by_fid.items()):
                _log(f"  fidelity {f}: {n}")
        if bf:
            ngaps = sum(len(sp.intervals) for sp in bf_specs)
            _log(
                f"backfill (fid {polymarket.BACKFILL_FID}, gaps > {args.min_gap_hours:g}h, from "
                f"data on disk): {len(bf_specs)} tokens, {ngaps} gaps, {bf.planned_calls} calls"
            )
        if st:
            _log(f"stocks: {len(tickers)} tickers {tickers}, {st.planned_calls} calls")
        total = sum(x.planned_calls for x in (pm, bf, st) if x)
        mins = total * (args.pause + 0.6) / 60 / max(args.workers, 1)
        _log(f"TOTAL planned calls: {total}  (~{mins:.0f} min with {args.workers} workers)")
        return 0

    parts = [x for x in (pm, bf) if x]
    fails = [f for x in (*parts, st) if x for f in x.failures]
    _log(
        f"done in {time.time() - t0:.0f}s. polymarket calls={pm.calls if pm else 0} "
        f"rows={pm.rows if pm else 0}; backfill calls={bf.calls if bf else 0} "
        f"rows={bf.rows if bf else 0}; stocks calls={st.calls if st else 0} "
        f"rows={st.rows if st else 0}; empty_pending="
        f"{sum(x.empty_pending for x in parts)} empty_confirmed="
        f"{sum(x.empty_confirmed for x in parts)}; failures={len(fails)}"
    )
    for f in fails:
        _log(f"  failed: {f.get('token_id') or f.get('ticker')} {f['error']}")
    _write_gap_files(specs, min_gap, wstart, asof)
    return 1 if fails else 0


def _write_gap_files(specs, min_gap: int, wstart: int, asof: datetime) -> None:
    """gap_inventory.csv (Polymarket) and stock_gaps.csv; both are summaries, never fatal."""
    inv = polymarket.gap_inventory(RAW_DIR, {sp.token_id for sp in specs}, min_gap)
    _write_scratch(inv, "gap_inventory.csv")
    _write_scratch(_stock_gaps(wstart, asof), "stock_gaps.csv")


def _stock_gaps(wstart: int, asof: datetime):
    import duckdb

    from poly_actor.store.raw_views import create_raw_views

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    create_raw_views(con, RAW_DIR)
    bars = con.execute("SELECT ticker, ts FROM raw_stock_bars").df()
    con.close()
    _, end = stocks.target_interval(wstart, asof)
    return stocks.stock_gap_table(bars, end)


def cmd_report(args) -> int:
    import duckdb

    from poly_actor.store.raw_views import create_raw_views

    cfg = _load_cfg()
    specs = targets.build_token_specs(cfg, int(utcnow().timestamp()))
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    create_raw_views(con, RAW_DIR)
    pair_of: dict[str, set[str]] = defaultdict(set)
    for sp in specs:
        for p in sp.pairs:
            pair_of[sp.token_id].add(p)
    df = con.execute(
        "SELECT token_id, fidelity, count(*) n, min(ts) lo, max(ts) hi "
        "FROM raw_polymarket_prices GROUP BY ALL"
    ).df()
    rows: dict[tuple[str, int], list] = defaultdict(lambda: [0, 0, None, None])
    for r in df.itertuples():
        for p in pair_of.get(r.token_id, {"?"}):
            a = rows[(p, r.fidelity)]
            a[0] += 1
            a[1] += r.n
            a[2] = r.lo if a[2] is None else min(a[2], r.lo)
            a[3] = r.hi if a[3] is None else max(a[3], r.hi)
    _log("pair, fidelity, tokens_with_data, rows, first_ts, last_ts")
    for (p, f), (nt, n, lo, hi) in sorted(rows.items()):
        _log(f"{p}, {f}, {nt}, {n}, {lo}, {hi}")
    ntok: dict[str, set[str]] = defaultdict(set)
    for sp in specs:
        if sp.fidelity == 60:
            for p in sp.pairs:
                ntok[p].add(sp.token_id)
    for p, s in sorted(ntok.items()):
        _log(f"planned tokens {p}: {len(s)}")
    _report_gaps(specs)
    _log("ticker, rows, nan_rows, first_ts, last_ts")
    sdf = con.execute(
        "SELECT ticker, count(*), count(*) FILTER (WHERE ohlc_all_nan), min(ts), max(ts) "
        "FROM raw_stock_bars GROUP BY ALL ORDER BY 1"
    ).fetchall()
    for r in sdf:
        _log(", ".join(str(x) for x in r))
    _report_stock_gaps()
    return 0


def _report_gaps(specs) -> None:
    inv = polymarket.gap_inventory(RAW_DIR, {sp.token_id for sp in specs})
    _write_scratch(inv, "gap_inventory.csv")
    _log(f"gap inventory (interior gaps > 3h in fid 60+1; fid-10 backfill): {len(inv)} gaps")
    if len(inv):
        _log(f"  by status: {inv['status'].value_counts().to_dict()}")
        _log(
            f"  tokens={inv['token_id'].nunique()} gap_hours={inv['gap_hours'].sum():.0f} "
            f"filled_points={int(inv['filled_points'].sum())}"
        )
        bad = inv[inv["status"] != "filled"]
        _log(
            f"  remaining unfilled/partial: {len(bad)} gaps, "
            f"{bad['largest_remaining_gap_hours'].sum():.0f}h (largest-remaining sum)"
        )
    recs = polymarket.manifest_for(RAW_DIR).read()
    counts: dict[str, int] = defaultdict(int)
    for r in recs:
        counts[r.get("status", "?")] += 1
    _log(f"  manifest statuses: {dict(counts)}")


def _report_stock_gaps() -> None:
    cfg = _load_cfg()
    gaps = _stock_gaps(targets.window_start(cfg), utcnow())
    _write_scratch(gaps, "stock_gaps.csv")
    _log(f"stock short days: {len(gaps)} (see data/scratch/step3/stock_gaps.csv)")
    if len(gaps):
        for tk, g in gaps.groupby("ticker"):
            _log(f"  {tk}: {len(g)} short days, {int(g['missing'].sum())} bars missing")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m poly_actor.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch missing price data (idempotent, incremental)")
    r.add_argument("--pairs", help="comma-separated pair ids (default: all)")
    r.add_argument("--dry-run", action="store_true", help="plan only; no network, no writes")
    r.add_argument("--only", choices=["polymarket", "stocks"])
    r.add_argument("--asof", help="pin 'now' (tz-aware ISO) for reproducible planning")
    r.add_argument("--no-backfill", action="store_true", help="skip the fidelity-10 gap pass")
    r.add_argument(
        "--min-gap-hours", type=float, default=3.0, help="backfill gaps longer than this"
    )
    r.add_argument("--pause", type=float, default=0.25, help="seconds between calls (per worker)")
    r.add_argument(
        "--workers",
        type=int,
        default=4,
        help="concurrent Polymarket workers, one token per worker (1 = sequential)",
    )
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="row counts and coverage from the raw files")
    rp.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

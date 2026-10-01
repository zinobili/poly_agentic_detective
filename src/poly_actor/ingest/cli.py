"""CLI: python -m poly_actor.ingest run [--pairs a,b] [--dry-run] | report"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime

import yaml

from poly_actor.config import CONFIG_DIR, RAW_DIR
from poly_actor.ingest import polymarket, stocks, targets
from poly_actor.ingest.common import utcnow


def _load_cfg(path=None) -> dict:
    with open(path or CONFIG_DIR / "pairs.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _log(msg: str) -> None:
    print(msg, flush=True)


def cmd_run(args) -> int:
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
    pm = polymarket.run_polymarket(specs, **kw) if do_pm else None
    st = (
        stocks.run_stocks(tickers, wstart, asof=asof, **{**kw, "pause": max(args.pause, 0.5)})
        if do_st
        else None
    )

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
        if st:
            _log(f"stocks: {len(tickers)} tickers {tickers}, {st.planned_calls} calls")
        total = (pm.planned_calls if pm else 0) + (st.planned_calls if st else 0)
        _log(f"TOTAL planned calls: {total}  (~{total * (args.pause + 0.6) / 60:.0f} min)")
        return 0

    fails = (pm.failures if pm else []) + (st.failures if st else [])
    _log(
        f"done in {time.time() - t0:.0f}s. polymarket calls={pm.calls if pm else 0} "
        f"rows={pm.rows if pm else 0}; stocks calls={st.calls if st else 0} "
        f"rows={st.rows if st else 0}; failures={len(fails)}"
    )
    for f in fails:
        _log(f"  failed: {f.get('token_id') or f.get('ticker')} {f['error']}")
    return 1 if fails else 0


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
    _log("ticker, rows, nan_rows, first_ts, last_ts")
    sdf = con.execute(
        "SELECT ticker, count(*), count(*) FILTER (WHERE ohlc_all_nan), min(ts), max(ts) "
        "FROM raw_stock_bars GROUP BY ALL ORDER BY 1"
    ).fetchall()
    for r in sdf:
        _log(", ".join(str(x) for x in r))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m poly_actor.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch missing price data (idempotent, incremental)")
    r.add_argument("--pairs", help="comma-separated pair ids (default: all)")
    r.add_argument("--dry-run", action="store_true", help="plan only; no network, no writes")
    r.add_argument("--only", choices=["polymarket", "stocks"])
    r.add_argument("--asof", help="pin 'now' (tz-aware ISO) for reproducible planning")
    r.add_argument("--pause", type=float, default=0.25, help="seconds between calls")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="row counts and coverage from the raw files")
    rp.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

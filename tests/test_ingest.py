"""Offline tests for step 3 ingestion (fixtures only; the conftest blocks the network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import requests
import yaml

from poly_actor.ingest import polymarket as pm
from poly_actor.ingest import stocks as st
from poly_actor.ingest import targets
from poly_actor.ingest.common import (
    DAY,
    HttpStatusError,
    IngestError,
    Manifest,
    request_json_with_retry,
    sha256_hex,
    subtract_intervals,
    tile,
    to_epoch,
)
from poly_actor.pairs import BtcRung, load_btc_rungs, select_ladder
from poly_actor.store.raw_views import create_raw_views

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]

START = to_epoch("2026-09-10T00:00:00Z")
END = to_epoch("2026-09-12T00:00:00Z")
RES_START = to_epoch("2024-11-06T00:00:00Z")
RES_END = to_epoch("2024-11-08T00:00:00Z")


def _body(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# ---------------------------------------------------------------- parse / clip / dedup


def test_active_market_live_point_is_dropped():
    body = _body("clob_active_with_live_point.json")
    live_t = body["history"][-1]["t"]
    assert live_t > END + 10 * DAY  # fixture really contains the appended "now" point
    df = pm.parse_prices_history(body, START, END)
    assert len(df) == len(body["history"]) - 1
    assert df["t"].max() < END and df["t"].min() >= START
    assert live_t not in set(df["t"])
    assert str(df["ts"].dt.tz) == "UTC"


def test_resolved_market_parses_fully_and_is_half_open():
    body = _body("clob_resolved.json")
    df = pm.parse_prices_history(body, RES_START, RES_END)
    assert len(df) == len(body["history"])
    t0 = int(df["t"].iloc[0])
    clipped = pm.parse_prices_history(body, t0 + 1, RES_END)  # start-exclusive of first point
    assert len(clipped) == len(df) - 1
    last = int(df["t"].iloc[-1])
    assert last not in set(pm.parse_prices_history(body, RES_START, last)["t"])  # end exclusive


def test_dedup_on_t_and_sorted():
    body = {"history": [{"t": 20, "p": 0.2}, {"t": 10, "p": 0.1}, {"t": 10, "p": 0.9}]}
    df = pm.parse_prices_history(body, 0, 100)
    assert df["t"].tolist() == [10, 20]
    assert df["p"].tolist() == [0.1, 0.2]  # first occurrence wins


def test_parse_rejects_garbage_and_handles_empty():
    with pytest.raises(ValueError):
        pm.parse_prices_history({"error": "x"}, 0, 1)
    assert len(pm.parse_prices_history({"history": []}, 0, 1)) == 0


# ---------------------------------------------------------------- tiling


def test_tile_back_to_back_and_within_15_days():
    s, e = 1_000_000, 1_000_000 + 40 * DAY + 5
    wins = tile(s, e, pm.TILE)
    assert wins[0][0] == s and wins[-1][1] == e
    assert all(a[1] == b[0] for a, b in zip(wins, wins[1:], strict=False))
    # the request is padded by BOUNDARY_PAD: it must still be <= 15 days
    assert all(w[1] - (w[0] - pm.BOUNDARY_PAD) <= 15 * DAY for w in wins)


def test_plan_windows_only_missing():
    target = [(0, 10 * DAY)]
    assert pm.plan_windows(target, [(0, 10 * DAY)]) == []
    assert pm.plan_windows(target, [(0, 4 * DAY)]) == [(4 * DAY, 10 * DAY)]
    assert subtract_intervals([(0, 10)], [(2, 4), (6, 8)]) == [(0, 2), (4, 6), (8, 10)]


# ---------------------------------------------------------------- retry / backoff


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._p = payload if payload is not None else {"history": []}
        self.content = json.dumps(self._p).encode()
        self.text = "x"
        self.headers = headers or {}

    def json(self):
        return self._p


def test_retry_backoff_on_429_and_5xx_then_success():
    seq = [_Resp(429), _Resp(503), _Resp(500), _Resp(200, {"history": [{"t": 1, "p": 0.5}]})]
    sleeps: list[float] = []
    calls = []

    def get(url, params, timeout):
        calls.append(params)
        return seq[len(calls) - 1]

    body, raw = request_json_with_retry(get, "u", {}, sleep=sleeps.append)
    assert body["history"][0]["t"] == 1 and len(calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]  # exponential
    assert sha256_hex(raw) == sha256_hex(json.dumps(body).encode())


def test_retry_honours_retry_after_and_timeouts_and_gives_up():
    sleeps: list[float] = []
    seq = [_Resp(429, headers={"Retry-After": "7"}), requests.Timeout("t"), _Resp(200)]

    def get(url, params, timeout):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    request_json_with_retry(get, "u", {}, sleep=sleeps.append)
    assert sleeps == [7.0, 2.0]

    with pytest.raises(IngestError):
        request_json_with_retry(
            lambda *a, **k: _Resp(500), "u", {}, max_retries=2, sleep=lambda s: 0
        )


def test_4xx_is_not_retried():
    n = []

    def get(url, params, timeout):
        n.append(1)
        return _Resp(400)

    with pytest.raises(HttpStatusError):
        request_json_with_retry(get, "u", {}, sleep=lambda s: 0)
    assert len(n) == 1


def test_fetch_prices_history_rejects_long_window_and_uses_params():
    with pytest.raises(ValueError):
        pm.fetch_prices_history("tok", 0, 16 * DAY, 60)
    seen = {}

    def get(url, params, timeout):
        seen.update(params)
        return _Resp(200, {"history": []})

    res = pm.fetch_prices_history("tok", 100, 200, 60, get=get, sleep=lambda s: 0)
    assert seen == {"market": "tok", "startTs": 100, "endTs": 200, "fidelity": 60}
    assert res.body == {"history": []}


# ---------------------------------------------------------------- polymarket run: idempotent


def _fake_fetch_factory(body, log):
    def fake(token_id, s, e, fidelity):
        log.append((token_id, s, e, fidelity))
        raw = json.dumps(body).encode()
        return pm.FetchResult(body, sha256_hex(raw), len(raw))

    return fake


def test_polymarket_run_is_idempotent_and_manifested(tmp_path):
    body = _body("clob_active_with_live_point.json")
    log: list = []
    spec = pm.TokenSpec("tok1", 60, [(START, END)])
    now = lambda: datetime(2026, 10, 1, tzinfo=UTC)  # noqa: E731
    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda s: 0, now=now)
    s1 = pm.run_polymarket([spec], fetch=_fake_fetch_factory(body, log), **kw)
    assert s1.calls == 1 and s1.rows == len(body["history"]) - 1 and not s1.failures
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    before = {f: (tmp_path / f).read_bytes() for f in files}
    assert files == [f"polymarket/tok1/fid=60/{START}_{END}.parquet"]

    s2 = pm.run_polymarket([spec], fetch=_fake_fetch_factory(body, log), **kw)
    assert s2.calls == 0 and len(log) == 1  # no new network calls
    after = {f: (tmp_path / f).read_bytes() for f in files}
    assert before == after

    rec = Manifest(tmp_path / "polymarket" / "_manifest.jsonl").read()
    assert len(rec) == 1
    r = rec[0]
    assert (r["token_id"], r["fidelity"], r["start_ts"], r["end_ts"]) == ("tok1", 60, START, END)
    assert r["status"] == "ok" and r["n_rows"] == len(body["history"]) - 1
    assert r["n_dropped_outside_window"] == 1
    assert r["fetched_at"] == "2026-10-01T00:00:00Z"
    assert r["sha256"] == sha256_hex(json.dumps(body).encode()) and len(r["sha256"]) == 64

    # incremental: extend the target by one day -> exactly one new call for the new day only
    spec2 = pm.TokenSpec("tok1", 60, [(START, END + DAY)])
    s3 = pm.run_polymarket([spec2], fetch=_fake_fetch_factory(body, log), **kw)
    assert s3.calls == 1 and log[-1][1] == END - pm.BOUNDARY_PAD
    assert log[-1][2] == END + DAY  # starts at the covered end (minus the boundary pad)


def test_polymarket_failure_not_marked_covered(tmp_path):
    def boom(*a, **k):
        raise HttpStatusError(400, "u", "bad")

    spec = pm.TokenSpec("tokX", 60, [(START, END)])
    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda s: 0)
    s = pm.run_polymarket([spec], fetch=boom, **kw)
    assert len(s.failures) == 1 and not list(tmp_path.rglob("*.parquet"))
    rec = Manifest(tmp_path / "polymarket" / "_manifest.jsonl").read()
    assert rec[0]["status"] == "failed"
    # a re-run retries the failed window
    log: list = []
    ok = pm.run_polymarket([spec], fetch=_fake_fetch_factory({"history": []}, log), **kw)
    assert ok.calls == 1 and not ok.failures


def test_polymarket_dry_run_makes_no_calls_or_files(tmp_path):
    def boom(*a, **k):
        raise AssertionError("network used in dry run")

    spec = pm.TokenSpec("t", 60, [(0, 40 * DAY)])
    s = pm.run_polymarket([spec], raw_dir=tmp_path, fetch=boom, dry_run=True)
    assert s.planned_calls == 3 and s.calls == 0
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- stocks


def _yf_frame() -> pd.DataFrame:
    df = pd.read_csv(FIX / "yf_tlt_1h.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


S_START = to_epoch("2026-01-30T05:00:00Z")
S_END = to_epoch("2026-02-04T05:00:00Z")


def test_parse_bars_utc_start_stamped_and_nan_flag():
    raw = _yf_frame()
    df = st.parse_bars(raw, S_START, S_END)
    assert len(df) == len(raw) == 13
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["ts"].iloc[0] == pd.Timestamp("2026-01-30 14:30", tz="UTC")  # 09:30 ET start stamp
    nan_rows = df[df["ohlc_all_nan"]]
    assert len(nan_rows) == 1
    assert nan_rows["ts"].iloc[0] == pd.Timestamp("2026-02-02 14:30", tz="UTC")
    assert not df.loc[~df["ohlc_all_nan"], "close"].isna().any()


def test_parse_bars_clips_half_open_and_rejects_naive():
    raw = _yf_frame()
    cut = to_epoch("2026-02-02T19:00:00Z")
    df = st.parse_bars(raw, S_START, cut)
    assert df["ts"].max() < pd.Timestamp(cut, unit="s", tz="UTC")
    naive = raw.copy()
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError):
        st.parse_bars(naive, S_START, S_END)


def test_empty_yfinance_frame_is_a_failure_and_not_covered(tmp_path):
    empty = pd.DataFrame(
        {c: [] for c in ["Open", "High", "Low", "Close", "Volume"]},
        index=pd.DatetimeIndex([], tz="America/New_York"),
    )
    asof = datetime(2026, 2, 5, 12, tzinfo=UTC)
    ws = to_epoch("2026-01-30T05:00:00Z")
    s = st.run_stocks(
        ["TLT"], ws, raw_dir=tmp_path, fetch=lambda *a: empty, sleep=lambda x: 0, asof=asof
    )
    assert len(s.failures) == 1 and "empty frame" in s.failures[0]["error"]
    assert not list(tmp_path.rglob("*.parquet"))
    rec = Manifest(tmp_path / "stocks" / "_manifest.jsonl").read()
    assert [r["status"] for r in rec] == ["failed"]


def test_stocks_run_idempotent_with_nan_counted(tmp_path):
    calls: list = []
    raw = _yf_frame()

    def fetch(tk, s, e):
        calls.append((tk, s, e))
        return raw

    asof = datetime(2026, 2, 4, 12, tzinfo=UTC)  # ET midnight 2026-02-04 = S_END
    ws = S_START
    kw = dict(raw_dir=tmp_path, fetch=fetch, sleep=lambda x: 0, asof=asof)
    s1 = st.run_stocks(["TLT"], ws, **kw)
    assert s1.calls == 1 and s1.rows == 13 and s1.nan_rows == 1 and not s1.failures
    snap = {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    assert len(snap) == 1
    s2 = st.run_stocks(["TLT"], ws, **kw)
    assert s2.calls == 0 and len(calls) == 1
    assert snap == {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    r = Manifest(tmp_path / "stocks" / "_manifest.jsonl").read()[0]
    assert r["n_rows"] == 13 and r["n_nan_rows"] == 1 and len(r["sha256"]) == 64


def test_empty_weekend_window_is_not_an_error(tmp_path):
    empty = pd.DataFrame(
        {c: [] for c in ["Open", "High", "Low", "Close", "Volume"]},
        index=pd.DatetimeIndex([], tz="America/New_York"),
    )
    sat = to_epoch("2026-01-31T05:00:00Z")
    mon = to_epoch("2026-02-02T05:00:00Z")
    assert not st.expects_rows("TLT", sat, mon)
    assert st.expects_rows("BTC-USD", sat, mon)
    assert st.expects_rows("TLT", sat, mon + DAY)
    assert len(empty) == 0


def test_target_interval_respects_730_day_cap():
    asof = datetime(2026, 10, 1, 12, tzinfo=UTC)
    s, e = st.target_interval(to_epoch("2020-01-01T00:00:00Z"), asof)
    assert (e - s) // DAY <= 730
    s2, _ = st.target_interval(to_epoch("2026-09-01T00:00:00Z"), asof)
    assert s2 > s


# ---------------------------------------------------------------- DuckDB view


def test_duckdb_views_dedup_and_empty(tmp_path):
    con = duckdb.connect()
    create_raw_views(con, tmp_path)
    assert con.execute("select count(*) from raw_polymarket_prices").fetchone()[0] == 0
    assert con.execute("select count(*) from raw_stock_bars").fetchone()[0] == 0

    body = _body("clob_resolved.json")
    pm.run_polymarket(
        [pm.TokenSpec("tokR", 60, [(RES_START, RES_END)])],
        raw_dir=tmp_path,
        fetch=_fake_fetch_factory(body, []),
        pause=0,
        sleep=lambda s: 0,
    )
    # overlapping duplicate file with the same points must not double count
    df = pm.parse_prices_history(body, RES_START, RES_END)
    df.to_parquet(tmp_path / "polymarket" / "tokR" / "fid=60" / "dup.parquet", index=False)
    st_raw = _yf_frame()
    st.run_stocks(
        ["TLT"],
        S_START,
        raw_dir=tmp_path,
        fetch=lambda *a: st_raw,
        sleep=lambda x: 0,
        asof=datetime(2026, 2, 4, 12, tzinfo=UTC),
    )
    create_raw_views(con, tmp_path)
    n, tok, fid = con.execute(
        "select count(*), min(token_id), min(fidelity) from raw_polymarket_prices"
    ).fetchone()
    assert (n, tok, fid) == (len(body["history"]), "tokR", 60)
    assert con.execute("select count(*) from raw_stock_bars").fetchone()[0] == 13
    assert con.execute("select count(*) from raw_manifest_polymarket").fetchone()[0] == 1


# ---------------------------------------------------------------- targets / pairs.yaml


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((ROOT / "config" / "pairs.yaml").read_text(encoding="utf-8"))


def test_targets_cover_all_token_kinds_and_skip_inactive(cfg):
    asof = to_epoch("2026-10-01T12:00:00Z")
    specs = targets.build_token_specs(cfg, asof)
    life = {s.token_id for s in specs if s.fidelity == 60}
    event = {s.token_id for s in specs if s.fidelity == 1}
    assert event <= life
    btc = next(p for p in cfg["pairs"] if p["id"] == "bitcoin_monthly_ladder")
    inactive = {r["token_id_yes"] for m in btc["markets"] for r in m["inactive_excluded"]}
    assert inactive and not inactive & life
    rec = next(p for p in cfg["pairs"] if p["id"] == "us_recession")
    assert {m["token_id_yes"] for m in rec["markets"]} <= life
    fed = next(p for p in cfg["pairs"] if p["id"] == "fed_decision")
    assert {o["token_id_yes"] for o in fed["markets"][0]["outcomes"].values()} <= life
    # no look-ahead in the plan: every interval ends at or before asof (hour floor)
    assert all(e <= asof for s in specs for (_, e) in s.intervals)
    # every event window is the +-24h window (<= 15d) and fidelity 1
    for s in specs:
        if s.fidelity == 1:
            assert all(e - b <= 3 * DAY for b, e in s.intervals)


def test_stock_tickers_include_btc_and_placebo_but_not_spreads(cfg):
    t = targets.stock_tickers(cfg)
    assert {"TLT", "SPY", "XLF", "IWM", "QQQ", "IBIT", "COIN", "MSTR", "BTC-USD", "XLU"} == set(t)


def test_load_btc_rungs_maps_direction_and_select_ladder_runs(cfg):
    btc = next(p for p in cfg["pairs"] if p["id"] == "bitcoin_monthly_ladder")
    month = next(m for m in btc["markets"] if m["month"] == "2024-11")
    rungs = load_btc_rungs(month)
    assert rungs and all(isinstance(r, BtcRung) for r in rungs)
    assert {r.ladder for r in rungs} == {"up", "dip"}  # 'reach' became 'up'
    ups = [r for r in rungs if r.ladder == "up"]
    assert len(ups) >= 14
    assert all(r.created.tzinfo is not None for r in rungs)
    assert sum(r.inactive for r in rungs) == len(month["inactive_excluded"]) == 1
    assert any(r.partial_reasons for r in rungs)  # the 82500 partial-window rung
    t = datetime(2024, 11, 10, 12, tzinfo=UTC)
    quotes = {r.slug: 0.3 for r in rungs}
    pts = select_ladder(rungs, "up", t, quotes)
    assert pts and [p.strike for p in pts] == sorted(p.strike for p in pts)
    assert len({p.strike for p in pts}) == len(pts)  # one per strike
    # 72500 reach resolved Yes on 2024-11-06 -> touched at t, P = 1, no quote consulted
    touched = {p.strike: p for p in pts if p.source == "touched"}
    assert touched[72500.0].p == 1.0
    assert all(p.p == 0.3 for p in pts if p.source != "touched")
    dips = select_ladder(rungs, "dip", t, quotes)
    assert dips and all(isinstance(p.strike, float) for p in dips)

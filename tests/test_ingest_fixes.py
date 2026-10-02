"""Offline tests for the step 3 fixes: empty-window handling, fid-10 gap backfill, manifest
robustness, lock file, stock bar-count check. No network (the conftest blocks it)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from poly_actor.ingest import polymarket as pm
from poly_actor.ingest import stocks as st
from poly_actor.ingest import targets
from poly_actor.ingest.common import (
    DAY,
    IngestError,
    Manifest,
    ingest_lock,
    to_epoch,
    write_parquet_once,
)

ROOT = Path(__file__).resolve().parents[1]
START = to_epoch("2026-09-10T00:00:00Z")


def NOW():  # noqa: N802
    return datetime(2026, 10, 1, tzinfo=UTC)


def _fake_fetch(body, log):
    def fake(token_id, s, e, fidelity):
        log.append((token_id, s, e, fidelity))
        return pm.FetchResult(body, "0" * 64, 2)

    return fake


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((ROOT / "config" / "pairs.yaml").read_text(encoding="utf-8"))


def test_write_parquet_once_never_overwrites(tmp_path):
    path = tmp_path / "a" / "x.parquet"
    assert write_parquet_once(pd.DataFrame({"t": [1, 2]}), path) is True
    before = path.read_bytes()
    assert write_parquet_once(pd.DataFrame({"t": [9, 9, 9]}), path) is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("extra", [1, 0, -60])
def test_windows_around_15_days_are_legal_requests(tmp_path, extra):
    """15d+1s (just over the limit), exactly 15d and a hair under all yield legal requests."""
    seen: list = []

    def fake(token_id, s, e, fidelity):
        seen.append((s, e))
        assert e - s <= 15 * DAY
        return pm.FetchResult({"history": []}, "0" * 64, 2)

    span = (0, 15 * DAY + extra)
    pm.run_polymarket(
        [pm.TokenSpec("tk", 60, [span])], raw_dir=tmp_path, fetch=fake, pause=0, sleep=lambda s: 0
    )
    assert len(seen) == (2 if extra >= 0 else 1)
    assert seen[0][0] == -60 and seen[-1][1] == span[1]  # literal 60 s pad on the first request


def test_empty_200_recent_is_not_covered_and_retried(tmp_path):
    e = int(NOW().timestamp()) - 3600  # ends within 48h of now
    s = e - 10 * 3600
    spec = pm.TokenSpec("tk", 60, [(s, e)], life=(s - DAY, e + DAY))
    log: list = []
    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda x: 0, now=NOW)
    r1 = pm.run_polymarket([spec], fetch=_fake_fetch({"history": []}, log), **kw)
    assert r1.empty_pending == 1 and r1.empty_confirmed == 0 and len(log) == 1  # no probe yet
    m = Manifest(tmp_path / "polymarket" / "_manifest.jsonl")
    assert [r["status"] for r in m.read()] == ["empty"]
    assert m.covered(token_id="tk", fidelity=60) == []
    r2 = pm.run_polymarket([spec], fetch=_fake_fetch({"history": []}, log), **kw)
    assert r2.calls == 1  # retried
    body = {"history": [{"t": s + 100, "p": 0.4}]}  # once data appears it is stored and covered
    r3 = pm.run_polymarket([spec], fetch=_fake_fetch(body, log), **kw)
    assert r3.rows == 1 and m.covered(token_id="tk", fidelity=60) == [(s, e)]


def test_empty_200_older_is_probed_at_fid1_then_confirmed(tmp_path):
    s, e = START, START + 10 * 3600  # weeks before NOW
    spec = pm.TokenSpec("tk", 60, [(s, e)], life=(s - DAY, e + DAY))
    log: list = []
    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda x: 0, now=NOW)
    r1 = pm.run_polymarket([spec], fetch=_fake_fetch({"history": []}, log), **kw)
    assert [x[3] for x in log] == [60, 1]  # original, then exactly one fid-1 probe
    assert r1.probe_calls == 1 and r1.empty_confirmed == 1 and not r1.failures
    m = Manifest(tmp_path / "polymarket" / "_manifest.jsonl")
    assert [(r["fidelity"], r["status"]) for r in m.read()] == [
        (60, "empty"),
        (1, "ok"),
        (60, "empty_confirmed"),
    ]
    assert m.covered(token_id="tk", fidelity=60) == [(s, e)]
    r2 = pm.run_polymarket([spec], fetch=_fake_fetch({"history": []}, log), **kw)
    assert r2.calls == 0 and len(log) == 2  # confirmed-empty is not retried


def test_empty_probe_that_finds_data_stores_it_under_fid1(tmp_path):
    s, e = START, START + 10 * 3600
    spec = pm.TokenSpec("tk", 60, [(s, e)], life=(s - DAY, e + DAY))

    def fake(token_id, a, b, fidelity):
        body = {"history": [{"t": s + 60, "p": 0.3}, {"t": s + 120, "p": 0.31}]}
        return pm.FetchResult(body if fidelity == 1 else {"history": []}, "0" * 64, 5)

    r = pm.run_polymarket([spec], raw_dir=tmp_path, fetch=fake, pause=0, sleep=lambda x: 0, now=NOW)
    assert r.probe_rows == 2
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet")]
    assert files == [f"polymarket/tk/fid=1/{s}_{e}.parquet"]


def test_empty_outside_life_is_ok_and_legacy_zero_row_ok_is_refetched(tmp_path):
    s, e = START, START + 10 * 3600
    outside = pm.TokenSpec("tk", 60, [(s, e)], life=(e + DAY, e + 2 * DAY))
    log: list = []
    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda x: 0, now=NOW)
    pm.run_polymarket([outside], fetch=_fake_fetch({"history": []}, log), **kw)
    m = Manifest(tmp_path / "polymarket" / "_manifest.jsonl")
    assert [r["status"] for r in m.read()] == ["ok"]
    assert pm.run_polymarket([outside], fetch=_fake_fetch({}, log), **kw).calls == 0
    # the same legacy ok / 0-row record, but the token's life overlaps it: re-fetched
    inside = pm.TokenSpec("tk", 60, [(s, e)], life=(s - DAY, e + DAY))
    r = pm.run_polymarket([inside], fetch=_fake_fetch({"history": []}, log), **kw)
    assert r.calls >= 1 and r.empty_confirmed == 1


def test_manifest_skips_torn_final_line_but_not_interior_corruption(tmp_path, caplog):
    path = tmp_path / "m.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n{"a": 3, "tr', encoding="utf-8")
    m = Manifest(path)
    assert [r["a"] for r in m.read()] == [1, 2]
    assert "malformed" in caplog.text
    path.write_text('{"a": 1}\n{oops\n{"a": 3}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        m.read()


def test_ingest_lock_is_exclusive_and_removed(tmp_path):
    with ingest_lock(tmp_path) as lock:
        assert lock.exists()
        with pytest.raises(IngestError), ingest_lock(tmp_path):
            pass
        assert lock.exists()  # the failed contender did not remove the holder's lock
    assert not lock.exists()
    with pytest.raises(RuntimeError), ingest_lock(tmp_path):  # removed even when the body raises
        raise RuntimeError("boom")
    assert not (tmp_path / ".ingest.lock").exists()


def test_last_window_ends_ten_minutes_before_asof_floored_to_hour(cfg):
    asof = to_epoch("2026-10-01T12:05:00Z")  # 12:05 - 10 min = 11:55 -> floor 11:00
    ends = {e for s in targets.build_token_specs(cfg, asof) for (_, e) in s.intervals}
    assert max(ends) <= to_epoch("2026-10-01T11:00:00Z")
    asof2 = to_epoch("2026-10-01T12:30:00Z")  # 12:20 -> 12:00
    ends2 = {e for s in targets.build_token_specs(cfg, asof2) for (_, e) in s.intervals}
    assert max(ends2) <= to_epoch("2026-10-01T12:00:00Z")


def test_specs_carry_token_life(cfg):
    specs = targets.build_token_specs(cfg, to_epoch("2026-10-01T12:00:00Z"))
    assert all(s.life is not None and s.life[0] < s.life[1] for s in specs)


# ---------------------------------------------------------------- gap backfill


def _write_pts(raw, tok, fid, ts):
    d = raw / "polymarket" / tok / f"fid={fid}"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"t": ts, "p": [0.5] * len(ts)})
    df.insert(1, "ts", pd.to_datetime(df["t"], unit="s", utc=True))
    df.to_parquet(d / f"{ts[0]}_{ts[-1] + 1}.parquet", index=False)


def test_find_gaps_interior_only_and_threshold(tmp_path):
    base = 1_800_000_000
    hrs = [0, 1, 2, 3, 4, 8, 9, 10, 13, 14]  # gaps: 4->8 (4h) and 10->13 (3h: not > 3h)
    _write_pts(tmp_path, "tk", 60, [base + h * 3600 for h in hrs])
    gaps = pm.find_gaps(tmp_path, ["tk", "other"])
    assert gaps == {"tk": [(base + 4 * 3600 + 1, base + 8 * 3600)]}


def test_backfill_fid10_idempotent_and_inventory(tmp_path):
    base = 1_800_000_000
    life = (base - DAY, base + 10 * DAY)
    _write_pts(tmp_path, "tk", 60, [base + h * 3600 for h in (0, 1, 2, 9, 10)])  # gap 2h->9h
    spec = pm.TokenSpec("tk", 60, [(base, base + 11 * 3600)], pairs={"p"}, life=life)
    log: list = []

    def fake(token_id, s, e, fidelity):
        log.append((s, e, fidelity))
        pts = [{"t": base + 2 * 3600 + k * 600, "p": 0.5} for k in range(1, 42)]  # every 10 min
        return pm.FetchResult({"history": pts}, "0" * 64, 9)

    kw = dict(raw_dir=tmp_path, pause=0, sleep=lambda x: 0, now=NOW)
    bf = pm.backfill_specs(tmp_path, [spec])
    assert [(b.token_id, b.fidelity) for b in bf] == [("tk", 10)]
    r1 = pm.run_polymarket(bf, fetch=fake, **kw)
    assert r1.calls == 1 and r1.rows == 41 and log[0][2] == 10
    assert (tmp_path / "polymarket" / "tk" / "fid=10").exists()
    # idempotent: the gap list is stable (fid=10 excluded) and the manifest covers it
    r2 = pm.run_polymarket(pm.backfill_specs(tmp_path, [spec]), fetch=fake, **kw)
    assert r2.calls == 0 and len(log) == 1
    inv = pm.gap_inventory(tmp_path, ["tk"])
    assert len(inv) == 1
    assert inv.iloc[0]["filled_points"] == 41 and inv.iloc[0]["status"] == "filled"
    # a gap nothing filled is reported as unfilled
    _write_pts(tmp_path, "tk2", 60, [base, base + 10 * 3600])
    assert pm.gap_inventory(tmp_path, ["tk2"]).iloc[0]["status"] == "unfilled"


# ---------------------------------------------------------------- stocks


def _bars(ticker, et_days_hours):
    ts = []
    for d, hrs in et_days_hours:
        for h in hrs:
            ts.append(pd.Timestamp(f"{d} {h}", tz="America/New_York").tz_convert("UTC"))
    return pd.DataFrame({"ticker": ticker, "ts": ts})


def test_stock_gap_table_flags_short_days_and_respects_early_close():
    full = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    # Wed 11-26 full, Thu 11-27 holiday, Fri 11-28 early close (3 bars ok), Mon 12-01 short
    b = _bars("SPY", [("2025-11-26", full), ("2025-11-28", full[:3]), ("2025-12-01", full[:5])])
    gaps = st.stock_gap_table(b, to_epoch("2025-12-02T05:00:00Z"))
    assert gaps[["date", "expected", "actual", "missing"]].values.tolist() == [
        [date(2025, 12, 1), 7, 5, 2]
    ]
    gaps2 = st.stock_gap_table(b, to_epoch("2025-12-03T05:00:00Z"))  # Tue 12-02 fully missing
    assert gaps2["actual"].tolist() == [5, 0]


def test_stock_gap_table_btc_utc_days_skip_partial_edges():
    ts = pd.date_range("2025-11-28 06:00", "2025-12-01 06:00", freq="h", tz="UTC")
    ts = ts[ts != pd.Timestamp("2025-11-29 05:00", tz="UTC")]
    g = st.stock_gap_table(pd.DataFrame({"ticker": "BTC-USD", "ts": ts}))
    assert g["date"].tolist() == [date(2025, 11, 29)] and g["missing"].tolist() == [1]


def test_stock_target_end_has_one_day_lag():
    asof = datetime(2026, 2, 5, 12, tzinfo=UTC)
    _, end = st.target_interval(to_epoch("2026-01-01T00:00:00Z"), asof)
    assert end == to_epoch("2026-02-04T05:00:00Z")  # ET midnight of yesterday, not today


def test_fetch_bars_does_not_sleep_after_last_attempt(monkeypatch):
    import yfinance

    class Boom:
        def __init__(self, tk):
            pass

        def history(self, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr(yfinance, "Ticker", Boom)
    sleeps: list[float] = []
    with pytest.raises(IngestError):
        st.fetch_bars("TLT", 0, DAY, sleep=sleeps.append)
    assert sleeps == [2.0, 4.0]  # 3 attempts, 2 sleeps (none after the last)


# ---------------------------------------------------------------- torn manifest line + appends


def test_torn_final_line_survives_later_appends(tmp_path):
    import json

    import pytest

    from poly_actor.ingest.common import Manifest

    p = tmp_path / "_manifest.jsonl"
    good = {"token_id": "a", "status": "ok"}
    p.write_text(json.dumps(good) + "\n" + '{"token_id": "b", "sta', encoding="utf-8")  # crash
    m = Manifest(p)
    assert m.read() == [good]  # torn final line skipped
    m.append({"token_id": "c", "status": "ok"})
    m.append({"token_id": "d", "status": "ok"})
    assert [r["token_id"] for r in m.read()] == ["a", "c", "d"]  # nothing lost, no crash
    # a malformed line that is NOT a repaired torn tail is still real corruption
    q = tmp_path / "bad.jsonl"
    q.write_text('{"x": 1}\nnot json\n{"y": 2}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        Manifest(q).read()

"""Election study: config structure, ingest specs, idempotence, clip and retry (offline)."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from poly_actor.election import ingest as ing
from poly_actor.election.config import AI_SUBS, SIGNALS, ElectionConfig, load_config
from poly_actor.ingest import polymarket
from poly_actor.ingest.common import IngestError, Manifest

FIX = Path(__file__).parent / "fixtures" / "election"


@pytest.fixture(scope="module")
def cfg() -> ElectionConfig:
    return load_config()


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.parquet"))
    }


# ----------------------------------------------------------------------------- config


def test_universe_is_29_plus_29_with_4_sub_baskets(cfg):
    ai, pl = cfg.basket("ai"), cfg.basket("placebo")
    assert len(ai) == 29 and len(pl) == 29
    assert not set(ai) & set(pl)
    assert {s.sub for s in cfg.universe if s.basket == "ai"} == set(AI_SUBS)
    sizes = {sub: sum(s.sub == sub for s in cfg.universe if s.basket == "ai") for sub in AI_SUBS}
    assert sizes == {"semis": 8, "hyperscalers": 6, "power_infra": 8, "software": 7}


def test_every_name_has_a_rationale_and_crwv_is_listed(cfg):
    assert all(len(s.why) >= 8 for s in cfg.universe)
    assert "CRWV" in cfg.basket("ai") and "BRK-B" in cfg.basket("placebo")


def test_duplicate_or_missing_names_are_rejected(cfg):
    raw = json.loads(json.dumps(cfg.raw))
    raw["universe"][-1]["ticker"] = raw["universe"][0]["ticker"]
    with pytest.raises(ValueError):
        ElectionConfig(raw).validate()
    raw = json.loads(json.dumps(cfg.raw))
    raw["universe"][0]["why"] = " "
    with pytest.raises(ValueError):
        ElectionConfig(raw).validate()


def test_signals_and_moratorium_tokens(cfg):
    assert set(cfg.signals) == set(SIGNALS)
    assert cfg.signals["p_sen"].event_id == 32224 and cfg.signals["p_rr"].event_id == 32228
    assert len(cfg.moratorium) == 7
    toks = [m.token_id for m in (*cfg.signals.values(), *cfg.moratorium.values())]
    assert len(set(toks)) == 11
    assert all("December 31, 2027" in m.question for m in cfg.moratorium.values())
    assert all(m.closed_s is None for m in cfg.moratorium.values())


def test_h3_window_uses_est_after_the_dst_switch(cfg):
    lo, hi = cfg.h3_window  # 2026-11-03 18:00 ET (EST, UTC-5) -> 2026-11-04 09:30 ET
    assert pd.Timestamp(lo, unit="s", tz="UTC") == pd.Timestamp("2026-11-03T23:00:00Z")
    assert pd.Timestamp(hi, unit="s", tz="UTC") == pd.Timestamp("2026-11-04T14:30:00Z")


# ----------------------------------------------------------------------------- specs


def test_polymarket_specs_shape(cfg):
    specs = ing.polymarket_specs(cfg)
    assert len(specs) == 4 * 3 + 7
    sen = [s for s in specs if s.pairs == {"p_sen"}]
    assert sorted(s.fidelity for s in sen) == [1, 10, 60]
    fid1 = next(s for s in sen if s.fidelity == 1)
    lo, hi = cfg.fid1_window
    assert fid1.intervals == [(lo, min(hi, cfg.signals["p_sen"].closed_s + ing.CLOSE_PAD_S))]
    whole = next(s for s in sen if s.fidelity == 60)
    assert whole.intervals[0][0] == cfg.pm_start_s
    assert whole.intervals[0][1] == cfg.signals["p_sen"].closed_s + ing.CLOSE_PAD_S
    mor = [s for s in specs if s.label == "moratorium"]
    assert {s.fidelity for s in mor} == {60}
    assert all(s.intervals[0][1] == cfg.data_end_s for s in mor)


def test_yf_tasks_cover_the_data_table(cfg):
    tasks = ing.yf_tasks(cfg)
    by = {(t.ticker, t.interval): t for t in tasks}
    assert len(cfg.equity_tickers) == 64
    assert all((tk, "1d") in by and (tk, "1h") in by for tk in cfg.equity_tickers)
    assert by[("RSP", "1d")].auto_adjust and not by[("RSP", "1h")].auto_adjust
    assert {k[0] for k in by if k[1] == "5m"} == {"NQ=F", "ES=F", "RTY=F"}
    assert all((tk, "1h") in by for tk in cfg.futures)
    assert by[("^VIX", "1d")].start_s == cfg.vol_start_s


# ----------------------------------------------------------------------------- clip


def test_clob_point_after_endts_is_clipped():
    """Live-price trap: a point stamped after endTs must never survive."""
    body = json.loads((FIX / "clob_sen_fid1_close_3nov.json").read_text())
    last = body["history"][-1]["t"]
    cut = last - 600
    df = polymarket.parse_prices_history(body, body["history"][0]["t"], cut)
    assert len(df) and df["t"].max() < cut
    body2 = {
        "history": [
            {"t": 100, "p": 0.5},
            {"t": 200, "p": 0.6},
            {"t": 300, "p": 0.9},
            {"t": 301, "p": 0.99},
        ]
    }
    assert polymarket.parse_prices_history(body2, 100, 300)["t"].tolist() == [100, 200]


# ----------------------------------------------------------------------------- idempotence


def fake_clob(token_id, s, e, fid):
    """Deterministic points inside [s, e] plus one live point after e (the trap)."""
    pts = [{"t": t, "p": 0.5} for t in range(s - s % 3600 + 3600 + 7, e, 3600 * 5)]
    pts.append({"t": e + 99, "p": 0.77})
    body = {"history": pts}
    return polymarket.FetchResult(body, "sha", len(pts))


def test_second_polymarket_run_makes_zero_calls_and_identical_files(cfg, tmp_path):
    specs = [s for s in ing.polymarket_specs(cfg) if s.pairs & {"p_sen", "p_house"}]
    kw = {"raw_dir": tmp_path, "fetch": fake_clob, "pause": 0, "sleep": lambda s: None}
    first = polymarket.run_polymarket(specs, **kw, workers=3)
    assert first.calls > 0 and not first.failures
    h1 = tree_hashes(tmp_path)
    second = polymarket.run_polymarket(specs, **kw, workers=3)
    assert second.calls == 0 and second.planned_calls == 0
    assert tree_hashes(tmp_path) == h1
    pts = ing.read_clob_points(tmp_path, cfg.signals["p_sen"].token_id)
    assert (pts["t"] < cfg.signals["p_sen"].closed_s + ing.CLOSE_PAD_S).all()  # live point gone


def fake_yf(task, s, e):
    idx = pd.date_range(pd.Timestamp(s, unit="s", tz="UTC"), periods=3, freq="h")
    return pd.DataFrame(
        {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10.0}, index=idx
    )


def test_second_yf_run_makes_zero_calls_and_identical_files(cfg, tmp_path):
    tasks = [t for t in ing.yf_tasks(cfg) if t.ticker in ("RSP", "NQ=F", "^VIX")]
    kw = {"raw_dir": tmp_path, "fetch": fake_yf, "pause": 0, "sleep": lambda s: None}
    first = ing.run_yf(tasks, **kw, workers=3)
    assert first.calls == first.planned_calls > 0 and not first.failures
    h1 = tree_hashes(tmp_path)
    second = ing.run_yf(tasks, **kw, workers=3)
    assert second.calls == 0 and tree_hashes(tmp_path) == h1
    assert ing.run_yf(tasks, **kw, dry_run=True).planned_calls == 0


def test_empty_yf_frame_is_a_recorded_failure_not_coverage(cfg, tmp_path):
    tasks = [t for t in ing.yf_tasks(cfg) if t.ticker == "RSP" and t.interval == "1d"]
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    empty.index = pd.DatetimeIndex([], tz="UTC")
    st = ing.run_yf(tasks, raw_dir=tmp_path, fetch=lambda t, s, e: empty, sleep=lambda s: None)
    assert len(st.failures) == 1
    assert ing.run_yf(tasks, raw_dir=tmp_path, dry_run=True).planned_calls == 1  # retried later
    assert [r["status"] for r in Manifest(tmp_path / "yf" / "_manifest.jsonl").read()] == ["failed"]


def test_fetch_yf_retries_silent_empty_frames_with_backoff(monkeypatch):
    calls, sleeps = [], []
    empty = pd.DataFrame()
    good = fake_yf(None, 0, 0)

    class FakeTicker:
        def __init__(self, tk):
            pass

        def history(self, **kw):
            calls.append(kw["interval"])
            return empty if len(calls) < 3 else good

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    task = ing.YfTask("RSP", "1h", 0, 10, False)
    out = ing.fetch_yf(task, 0, 10, sleep=sleeps.append)
    assert len(out) == 3 and len(calls) == 3 and sleeps == [2.0, 4.0]


def test_fetch_yf_gives_up_after_errors(monkeypatch):
    class Boom:
        def __init__(self, tk):
            pass

        def history(self, **kw):
            raise RuntimeError("429")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Boom))
    with pytest.raises(IngestError):
        ing.fetch_yf(ing.YfTask("RSP", "1d", 0, 10, True), 0, 10, sleep=lambda s: None)

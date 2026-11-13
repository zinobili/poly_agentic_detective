"""`analyse` end to end on synthetic panels (planted effects and pure noise), plus the
no-look-ahead rules of H2 and the data rules of H1. Offline."""

from __future__ import annotations

import json

import numpy as np
import pytest

from election_synth import make_panels
from poly_actor.election import analysis as an
from poly_actor.election import stats as st
from poly_actor.election.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def planted(cfg, tmp_path_factory):
    """AI names carry a cross-sectionally varying beta (mean 0.06), placebo none; on the event
    day every AI name also gets an extra b_i x 0.245 (H2 has something to find)."""
    d = tmp_path_factory.mktemp("planted")
    b = np.linspace(0.0, 0.12, 29)
    make_panels(
        cfg,
        d / "clean",
        seed=1,
        b_ai=b,
        b_pl=0.0,
        noise=0.004,
        h_gain=0.3,
        h_lag=1,
        n_gain=0.2,
        n_lag=0,
        event_xs=0.245,
    )
    res = an.analyse(cfg, d / "clean", d / "out", today="2026-11-13")
    return d, res


@pytest.fixture(scope="module")
def noise(cfg, tmp_path_factory):
    d = tmp_path_factory.mktemp("noise")
    make_panels(cfg, d / "clean", seed=2)
    return d, an.analyse(cfg, d / "clean", d / "out", today="2026-11-13")


def test_planted_ai_beta_gives_ai_verdict(planted):
    _, res = planted
    h1 = res["h1"]
    assert h1["ai"]["b10_pct"] == pytest.approx(0.6, abs=3 * h1["ai"]["se10_pct"])
    assert h1["ai"]["p_perm"] < 0.01 and h1["diff"]["p_perm"] < 0.10
    assert abs(h1["placebo"]["b10_pct"]) < 3 * h1["placebo"]["se10_pct"]
    assert res["headline"]["h1_verdict"] == st.H1_AI
    assert res["headline"]["h2_verdict"] == st.H2_YES


def test_planted_h4_and_h3_and_h5(planted):
    _, res = planted
    assert res["h4"]["verdict"] == "odds first"
    nq = {r["lag"]: r for r in res["h3"]["instruments"]["NQ"]["rows"]}
    assert max(nq, key=lambda k: abs(nq[k]["t"])) == 0
    assert res["h5"]["wald_equal"]["p"] > 0.0  # computed, finite


def test_noise_finds_nothing(noise):
    _, res = noise
    hd = res["headline"]
    assert hd["h1_verdict"] in (st.H1_BOUNDED, st.H1_NOISY)
    assert hd["h2_verdict"] == st.H2_NO
    assert res["h4"]["verdict"] == "no detectable ordering"


def test_event_dp_uses_resolved_price(planted):
    _, res = planted
    assert res["h2"]["event_dp_sen"] == pytest.approx(0.9995 - 0.745)


def test_every_exploratory_block_is_labelled(planted):
    _, res = planted
    assert all(v["label"] == "exploratory" for v in res["exploratory"].values())


def test_results_contract_and_series_exist(planted):
    d, res = planted
    for k in (
        "meta",
        "headline",
        "h1",
        "h2",
        "h2b",
        "h3",
        "h4",
        "h5",
        "exploratory",
        "robustness",
        "coverage",
        "checklist",
    ):
        assert k in res
    for rel in res["series"].values():
        assert (d / "out" / rel).exists()
    names = [r["name"] for r in res["robustness"]]
    assert any("SPY" in n for n in names) and any("logit" in n for n in names)
    assert sum(n.startswith("E4") for n in names) == 3


def test_analyse_twice_is_byte_identical(cfg, planted):
    d, _ = planted
    an.analyse(cfg, d / "clean", d / "out2", today="2026-11-13")
    a = (d / "out" / "results.json").read_bytes()
    assert a == (d / "out2" / "results.json").read_bytes()
    for f in (d / "out" / "series").iterdir():
        assert f.read_bytes() == (d / "out2" / "series" / f.name).read_bytes()


def test_publish_copies_bundle(planted, tmp_path):
    d, _ = planted
    files = an.publish(d / "out", tmp_path / "reports" / "election")
    assert "results.json" in files and any(f.startswith("series/") for f in files)
    json.loads((tmp_path / "reports" / "election" / "results.json").read_text())


# ---------------------------------------------------------------- look-ahead and data rules


def _frame(d):
    p = an.load_panels(d / "clean")
    return p, an.daily_frame(p["daily"], p["odds_daily"])


def test_h2_estimation_ends_2026_10_30_and_later_rows_never_enter(cfg, planted):
    d, _ = planted
    p, D = _frame(d)
    names = cfg.basket("ai")
    E = an.h2_estimation(D, cfg, names)
    assert E.index[-1] == "2026-10-30" and (E.index < "2026-11-02").all()
    B0 = st.per_stock_betas(E[names].to_numpy(), E["dp"].to_numpy(), E[["RSP", "TLT"]].to_numpy())
    D2 = D.copy()
    late = D2.index >= "2026-11-02"
    D2.loc[late, names] = 5.0  # poison everything from election week on
    D2.loc[late, "dp_p_sen"] = 0.5
    E2 = an.h2_estimation(D2, cfg, names)
    B2 = st.per_stock_betas(
        E2[names].to_numpy(), E2["dp"].to_numpy(), E2[["RSP", "TLT"]].to_numpy()
    )
    np.testing.assert_array_equal(B0, B2)


def test_h2b_days_estimate_strictly_before_t(planted):
    _, res = planted
    for g in ("ai", "placebo"):
        for day in res["h2b"][g]["days"]:
            assert day["last_est"] < day["date"]
            assert day["date"] <= "2026-11-02"


def test_missing_dp_day_is_dropped_not_zero_filled(cfg, planted):
    d, _ = planted
    _, D = _frame(d)
    S = an.window(D, *cfg.pre_sample).copy()
    victim = "2026-03-02"
    S.loc[victim, "dp_p_sen"] = np.nan
    h1, *_ = an.run_h1(S, cfg)
    assert victim in h1["dropped_sessions_missing_dp"]
    h1b, *_ = an.run_h1(an.window(D, *cfg.pre_sample), cfg)
    assert h1["ai"]["n"] == h1b["ai"]["n"] - 1
    # thin start: first sessions have no odds and drop out
    assert "2025-07-14" in h1b["dropped_sessions_missing_dp"]
    assert h1b["ai"]["first"] > "2025-07-18"


def test_pre_sample_never_reaches_election_day(planted):
    _, res = planted
    assert res["h1"]["ai"]["last"] == "2026-11-02"

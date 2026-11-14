"""Election panels: as-of, close/bar-end stamping, missing rules, coverage (offline, fixtures)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from poly_actor.core.ingest import stocks
from poly_actor.core.ingest.common import to_epoch
from poly_actor.core.timegrid.grid import load_sessions
from poly_actor.studies.election import panel
from poly_actor.studies.election.config import SIGNALS, load_config
from poly_actor.studies.election.coverage import odds_stats

FIX = Path(__file__).parent / "fixtures"
HOUR = 3600


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def points(*stamps: tuple[int, float], fid: int = 10) -> pd.DataFrame:
    return pd.DataFrame({"t": [s for s, _ in stamps], "p": [p for _, p in stamps], "fidelity": fid})


def book(stamps, max_age, key="p_sen", fid=None):
    return panel.build_book({key: points(*stamps)}, max_age, fid)


def sess(*rows) -> pd.DataFrame:
    """(date, open_s, close_s, early) rows."""
    return pd.DataFrame(rows, columns=["session", "open_s", "close_s", "early"])


def sessions_for(start: str, end: str) -> pd.DataFrame:
    s = load_sessions(to_epoch(start), to_epoch(end))
    return s[(s["close_s"] > to_epoch(start)) & (s["open_s"] < to_epoch(end))].reset_index(
        drop=True
    )


def fixture_bars(name: str) -> pd.DataFrame:
    raw = pd.read_csv(FIX / name, index_col=0, parse_dates=True)
    return stocks.parse_bars(raw, 0, 10**11)


# ---------------------------------------------------------------- rule: no look-ahead as-of


def test_daily_odds_use_last_point_at_or_before_close_never_later():
    close = to_epoch("2025-03-03T21:00:00Z")
    b = book([(close - 120, 0.40), (close + 5, 0.90)], 6 * HOUR)
    out = panel.build_odds_daily(
        b, ["p_sen"], sess((date(2025, 3, 3), close - 23400, close, False))
    )
    assert out["p"].iloc[0] == 0.40 and out["age_s"].iloc[0] == 120


def test_point_exactly_at_the_instant_is_used():
    close = to_epoch("2025-03-03T21:00:00Z")
    b = book([(close - 700, 0.30), (close, 0.35)], 6 * HOUR)
    out = panel.build_odds_daily(
        b, ["p_sen"], sess((date(2025, 3, 3), close - 23400, close, False))
    )
    assert out["p"].iloc[0] == 0.35 and out["age_s"].iloc[0] == 0


def test_stale_reading_is_missing_and_dp_missing_for_that_session_and_the_next():
    c = [to_epoch(f"2025-03-0{d}T21:00:00Z") for d in (3, 4, 5, 6)]
    rows = [(date(2025, 3, 3 + i), c[i] - 23400, c[i], False) for i in range(4)]
    stamps = [(c[0] - 60, 0.50), (c[1] - 7 * HOUR, 0.52), (c[2] - 90, 0.60), (c[3] - 90, 0.65)]
    out = panel.build_odds_daily(book(stamps, 6 * HOUR), ["p_sen"], sess(*rows))
    # the 7 h old reading of session 2 is missing; session 3's 0.52 point is also > 6 h old.
    assert out["p"].tolist()[0] == 0.50
    assert np.isnan(out["p"].iloc[1]) and np.isnan(out["dp"].iloc[1])
    assert out["p"].iloc[2] == 0.60 and np.isnan(out["dp"].iloc[2])
    assert out["dp"].iloc[3] == pytest.approx(0.05)


def test_early_close_session_reads_odds_as_of_1800_utc():
    s = sessions_for("2025-11-26T00:00:00Z", "2025-11-30T00:00:00Z")
    row = s[s["session"] == date(2025, 11, 28)].iloc[0]
    assert row["early"] and row["close_s"] == to_epoch("2025-11-28T18:00:00Z")
    c = row["close_s"]
    b = book([(c - 300, 0.34), (c + 5, 0.50), (to_epoch("2025-11-28T20:59:00Z"), 0.60)], 6 * HOUR)
    out = panel.build_odds_daily(b, ["p_sen"], s)
    r = out[out["session"] == date(2025, 11, 28)].iloc[0]
    assert r["p"] == 0.34 and r["age_s"] == 300
    assert r["close_ts"] == pd.Timestamp("2025-11-28T18:00:00Z")
    nov26 = out[out["session"] == date(2025, 11, 26)].iloc[0]
    assert nov26["close_ts"] == pd.Timestamp("2025-11-26T21:00:00Z")


def test_hourly_odds_cap_is_30_minutes_and_dp_resets_each_session():
    e = [to_epoch("2025-03-03T15:30:00Z"), to_epoch("2025-03-03T16:30:00Z")]
    s = sessions_for("2025-03-03T00:00:00Z", "2025-03-04T00:00:00Z")
    ends = panel.bar_table(s)["end_s"].to_numpy()
    stamps = [(ends[0] - 29 * 60, 0.40), (ends[1] - 31 * 60, 0.45), (ends[2] - 10, 0.50)]
    out = panel.build_odds_hourly(book(stamps, 1800), ["p_sen"], s).sort_values("bar_end_ts")
    p = out["p"].tolist()
    assert p[0] == 0.40 and np.isnan(p[1]) and p[2] == 0.50
    assert np.isnan(out["dp"].iloc[0])  # first bar of the session: no previous bar end
    assert np.isnan(out["dp"].iloc[1]) and np.isnan(out["dp"].iloc[2])  # previous was missing
    assert e[0] == ends[0]  # 10:30 ET on 3 Mar 2025 (EST) = 15:30 UTC
    out2 = panel.build_odds_hourly(
        book([(ends[3] - 5, 0.1), (ends[4] - 5, 0.3)], 1800), ["p_sen"], s
    )
    assert out2["dp"].dropna().iloc[0] == pytest.approx(0.2)


# ---------------------------------------------------------------- rule: bar end stamps / DST


def test_hourly_bars_are_stamped_at_end_on_both_sides_of_both_dst_switches():
    bars = {"NVDA": fixture_bars("yf_nvda_1h.csv")}
    s = sessions_for("2025-10-29T00:00:00Z", "2026-03-13T00:00:00Z")
    hourly, unmatched = panel.build_hourly(bars, s)
    assert len(unmatched) == 0
    h = hourly.set_index("bar_end_ts")

    def ends(day):
        return sorted(
            t.strftime("%H:%M") for t in hourly.loc[hourly["session"] == day, "bar_end_ts"]
        )

    full_edt = ["14:30", "15:30", "16:30", "17:30", "18:30", "19:30", "20:00"]
    full_est = ["15:30", "16:30", "17:30", "18:30", "19:30", "20:30", "21:00"]
    assert ends(date(2025, 10, 31)) == full_edt  # EDT: the 15:30 ET bar ends 16:00 ET = 20:00 UTC
    assert ends(date(2025, 11, 3)) == full_est  # EST after the 2 Nov switch: 21:00 UTC
    assert ends(date(2026, 3, 6)) == full_est  # EST before the 8 Mar switch
    assert ends(date(2026, 3, 9)) == full_edt  # EDT after it
    assert ends(date(2025, 11, 28)) == [
        "15:30",
        "16:30",
        "18:00",
    ]  # early close: 11:30 bar -> 13:00 ET
    assert h.index.tz is not None and str(h.index.tz) == "UTC"


def test_hourly_return_is_within_bar_and_missing_bar_is_not_filled():
    bars = fixture_bars("yf_nvda_1h.csv")
    s = sessions_for("2025-10-29T00:00:00Z", "2025-11-06T00:00:00Z")
    first = bars.iloc[0]
    hourly, _ = panel.build_hourly({"NVDA": bars}, s)
    r = hourly.iloc[0]
    assert r["ret"] == pytest.approx(np.log(first["close"] / first["open"]))
    dropped = bars.drop(index=2).reset_index(drop=True)
    h2, _ = panel.build_hourly({"NVDA": dropped}, s)
    assert len(h2) == len(hourly) - 1


def test_off_grid_bar_goes_to_unmatched_not_shifted():
    bars = fixture_bars("yf_nvda_1h.csv").iloc[:7].copy()
    bars["ts"] = bars["ts"] + pd.Timedelta(minutes=7)
    s = sessions_for("2025-10-29T00:00:00Z", "2025-11-06T00:00:00Z")
    hourly, unmatched = panel.build_hourly({"NVDA": bars}, s)
    assert len(hourly) == 0 and len(unmatched) == 7


# ---------------------------------------------------------------- rule: futures night


def test_futures_5m_bar_stamped_1900_et_ends_at_1905_et_and_odds_stop_at_that_instant(cfg):
    fut = {"NQ=F": fixture_bars("yf_nqf_5m.csv")}
    bar = fut["NQ=F"]
    assert bar["ts"].iloc[2] == pd.Timestamp("2026-11-04T00:00:00Z")  # 19:00 ET (EST)
    end = to_epoch("2026-11-04T00:05:00Z")  # 19:05 ET
    b = book([(end - 340, 0.60), (end, 0.62), (end + 1, 0.99)], 600, fid=None)
    out = panel.build_night(fut, b, ["p_sen"], cfg)
    row = out[out["bar_end_ts"] == pd.Timestamp("2026-11-04T00:05:00Z")].iloc[0]
    assert row["p_sen"] == 0.62 and row["age_p_sen"] == 0
    assert row["bar_start_ts"] == pd.Timestamp("2026-11-04T00:00:00Z")
    prev = out[out["bar_end_ts"] == pd.Timestamp("2026-11-04T00:00:00Z")].iloc[0]
    assert prev["p_sen"] == 0.60 and row["dp_sen"] == pytest.approx(0.02)
    stale = book([(end - 601, 0.6)], 600)
    miss = panel.build_night(fut, stale, ["p_sen"], cfg)
    assert np.isnan(miss.loc[miss["bar_end_ts"] == row["bar_end_ts"], "p_sen"].iloc[0])


def test_night_book_with_fid1_only_ignores_other_fidelities():
    d = pd.concat([points((100, 0.1), fid=60), points((200, 0.2), fid=1)])
    b = panel.build_book({"p_sen": d}, 600, fid=1)
    assert b.asof("p_sen", np.array([250])).p[0] == 0.2
    assert np.isnan(b.asof("p_sen", np.array([150])).p[0])


# ---------------------------------------------------------------- daily stock panel


def test_daily_missing_session_is_not_forward_filled_and_next_return_is_missing():
    s = sessions_for("2025-03-03T00:00:00Z", "2025-03-08T00:00:00Z")  # 5 sessions
    days = [d for d in s["session"]]
    ts = pd.DatetimeIndex([pd.Timestamp(d, tz="America/New_York") for d in days]).tz_convert("UTC")
    full = pd.DataFrame({"ts": ts, "close": [100.0, 101.0, 102.0, 103.0, 104.0]})
    gap = full.drop(index=2)
    out = panel.build_daily({"AAA": full, "CRWV": gap}, s)
    a = out[out["ticker"] == "AAA"]
    assert a["ret"].iloc[1] == pytest.approx(np.log(101 / 100)) and a["ret"].isna().sum() == 1
    g = out[out["ticker"] == "CRWV"]
    assert g["missing"].tolist() == [False, False, True, False, False]
    assert g["ret"].isna().tolist() == [True, False, True, True, False]
    assert (a["close_ts"] == pd.Timestamp("2025-03-03T21:00:00Z")).iloc[0]


def test_daily_close_ts_is_real_close_on_early_close_and_dst_days():
    s = sessions_for("2025-11-26T00:00:00Z", "2025-12-02T00:00:00Z")
    raw = pd.read_csv(FIX / "yf_nvda_1d.csv", index_col=0, parse_dates=True)
    bars = stocks.parse_bars(raw, 0, 10**11)
    out = panel.build_daily({"NVDA": bars}, s)
    assert out["missing"].sum() == 0
    by = out.set_index("session")["close_ts"]
    assert by[date(2025, 11, 28)] == pd.Timestamp("2025-11-28T18:00:00Z")
    assert by[date(2025, 11, 26)] == pd.Timestamp("2025-11-26T21:00:00Z")
    nv = out.set_index("session")["ret"]
    assert nv[date(2025, 11, 28)] == pytest.approx(
        np.log(bars["close"].iloc[3] / bars["close"].iloc[2])
    )


def test_real_clob_fixture_close_reading_never_uses_later_points():
    import json

    body = json.loads((FIX / "clob_sen_fid1_close_3nov.json").read_text())
    df = pd.DataFrame(body["history"])
    close = to_epoch("2026-11-03T21:00:00Z")
    assert (df["t"] > close).any() and (df["t"] <= close).any()
    d = df.assign(fidelity=1)
    out = panel.build_odds_daily(
        panel.build_book({"p_sen": d}, 6 * HOUR),
        ["p_sen"],
        sess((date(2026, 11, 3), 0, close, False)),
    )
    last = df[df["t"] <= close].iloc[-1]
    assert out["p"].iloc[0] == last["p"] and out["age_s"].iloc[0] == close - last["t"]


# ---------------------------------------------------------------- moratorium, vol, coverage


def test_moratorium_mean_and_dp():
    c = [to_epoch(f"2026-10-0{d}T20:00:00Z") for d in (5, 6)]
    rows = [(date(2026, 10, 5 + i), c[i] - 23400, c[i], False) for i in range(2)]
    d = {
        "ohio": points((c[0] - 60, 0.10), (c[1] - 60, 0.20), fid=60),
        "texas": points(
            (c[0] - 60, 0.30), fid=60
        ),  # stale (> 6 h) on day 2? no: 24 h old -> missing
    }
    b = panel.build_book(d, 6 * HOUR)
    out = panel.build_moratorium(b, ["ohio", "texas"], sess(*rows))
    assert out["mean_p"].tolist() == [pytest.approx(0.2), pytest.approx(0.20)]
    assert out["n_states"].tolist() == [2, 1]
    assert np.isnan(out["mean_dp"].iloc[0]) and np.isnan(out["p_texas"].iloc[1])
    assert out["mean_dp"].iloc[1] == pytest.approx(0.10)  # only ohio has a same-state pair


def test_vol_daily_keys_by_et_date():
    ts = pd.DatetimeIndex([pd.Timestamp("2026-11-03", tz="America/New_York")]).tz_convert("UTC")
    out = panel.build_vol({"^VIX": pd.DataFrame({"ts": ts, "close": [18.5]})})
    assert out["date"].iloc[0] == date(2026, 11, 3) and out["close"].iloc[0] == 18.5


def test_coverage_in_life_share_and_ticker_gaps(cfg):
    s = sessions_for("2025-03-03T00:00:00Z", "2025-03-08T00:00:00Z")
    daily = panel.build_daily(
        {"X": pd.DataFrame({"ts": pd.DatetimeIndex([]).tz_localize("UTC"), "close": []})}, s
    )
    assert daily["missing"].all()
    od = pd.DataFrame(
        {
            "signal": ["p_sen"] * 4,
            "close_ts": pd.to_datetime(
                ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"], utc=True
            ),
            "p": [np.nan, 0.5, np.nan, 0.4],
            "age_s": [np.nan, 100.0, np.nan, 300.0],
        }
    )
    life = {"p_sen": (to_epoch("2025-01-15T00:00:00Z"), to_epoch("2025-03-15T00:00:00Z"))}
    st = odds_stats(od, "close_ts", life)
    assert st["all"]["missing_share"] == 0.5
    assert st["in_life"]["rows"] == 2 and st["in_life"]["missing_share"] == 0.5
    assert st["in_life"]["median_s"] == 100.0
    from poly_actor.studies.election.coverage import ticker_sessions

    assert ticker_sessions(daily, s)["X"]["missing_sessions"] == [str(d) for d in s["session"]]


def test_build_all_writes_every_table_from_a_small_raw_tree(cfg, tmp_path):
    """End to end on a tiny synthetic raw tree: tables exist, tz-aware, coverage.json written."""
    from poly_actor.studies.election import ingest as ing

    raw, clean = tmp_path / "raw", tmp_path / "clean"
    sig = cfg.signals["p_sen"]
    d = raw / "polymarket" / sig.token_id / "fid=10"
    d.mkdir(parents=True)
    t = np.arange(to_epoch("2025-07-14T00:00:00Z"), to_epoch("2025-07-20T00:00:00Z"), 600)
    pd.DataFrame({"t": t, "ts": pd.to_datetime(t, unit="s", utc=True), "p": 0.4}).to_parquet(
        d / "a.parquet"
    )
    for tk in cfg.equity_tickers:
        for iv in ("1d", "1h"):
            (raw / "yf" / iv / tk).mkdir(parents=True, exist_ok=True)
    cov = panel.build_all(cfg, raw, clean)
    assert (clean / "coverage.json").exists()
    for name in cov["tables"]:
        assert (clean / f"{name}.parquet").exists() or name == "night_5m"
    od = pd.read_parquet(clean / "odds_daily.parquet")
    assert str(od["close_ts"].dt.tz) == "UTC"
    assert od[od["signal"] == "p_sen"]["p"].notna().any()
    assert set(od["signal"]) == set(SIGNALS)
    assert ing.read_clob_points(raw, sig.token_id)["fidelity"].eq(10).all()

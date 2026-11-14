"""Step 10: the election presentation and the generated findings (rules-as-examples table of
docs/handoff/step10.md). Offline, on `tests/fixtures/election/bundle/`: the published bundle
with the per-ticker coverage dropped and the long chart series thinned."""

import copy
import json
import os
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from poly_actor.election import charts, findings
from poly_actor.election import report_text as text
from poly_actor.election.cli import main as cli_main
from poly_actor.election.report_load import (
    BUNDLE_DIR,
    BUNDLE_DIR_ENV,
    bundle_signature,
    load_bundle,
)

FIXTURE = Path(__file__).parent / "fixtures" / "election" / "bundle"
APP = Path(__file__).parents[1] / "src" / "poly_actor" / "election" / "app.py"
CLAIM_WORDS = re.compile(r"beta of|predict|\blead|first", re.IGNORECASE)
EXPLORATORY_KEYS = ("e2_term", "e2_moves", "e1", "e3", "e5")

NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
LOOSE_NUMBER = re.compile(r"\d+(?:\.\d+)?")
HEX = re.compile(r"`[0-9a-f]{7,64}`")
INDEX_NAMES = re.compile(r"S&P 500|Nasdaq-100|Russell 2000")  # names, not numbers


@pytest.fixture(scope="module")
def bundle():
    b = load_bundle(FIXTURE)
    assert b is not None
    return b


@pytest.fixture
def res(bundle):
    return copy.deepcopy(bundle.results)


def _as_ai_beta(res: dict, b10: float = 0.8) -> dict:
    """The fixture re-labelled as a pass of H1 with a positive beta."""
    res["headline"]["h1_verdict"] = text.H1_AI
    res["headline"]["h1_confidence"] = "Medium"
    res["h1"]["ai"]["b10_pct"] = b10
    res["h1"]["ai"]["ci10_pct"] = [b10 - 0.3, b10 + 0.3]
    return res


# ---------------------------------------------------------------- rules as examples


def test_too_noisy_headline_card_and_no_claim_in_any_chart_title(bundle, res):
    """Row 1: H1 'Too noisy to tell' -> headline and card say so; no title makes a claim."""
    assert text.verdicts(res) == (text.H1_NOISY, text.H2_NO)
    assert text.headline(res).startswith("Too noisy to tell")
    card = text.cards(res)[0]
    assert card.verdict == "Too noisy to tell" and card.confidence.word == "Low"
    titles = {k: ct.title for k, ct in text.chart_texts(res, bundle.series).items()}
    assert len(titles) == 14 and not any(ct == "" for ct in titles.values())
    assert {k: t for k, t in titles.items() if CLAIM_WORDS.search(t)} == {}


def test_ai_beta_title_gives_direction_and_size_from_the_bundle(res):
    """Row 2: 'AI carried a partisan beta', b > 0 -> rose, with the size per 10 points."""
    title = text.h1_title(_as_ai_beta(res, 0.8))
    assert title.startswith("AI names rose about 0.80% for every +10 points of Democratic Senate")
    assert text.h1_title(_as_ai_beta(res, -1.25)).startswith("AI names fell about 1.25%")
    assert "Too noisy" not in title and text.headline(res).startswith("AI stocks carried")


def test_title_never_says_more_than_the_verdict(res):
    """A positive, tight estimate still gets the null title while the verdict is a null."""
    res["h1"]["ai"]["b10_pct"] = 0.8
    assert text.h1_title(res).startswith("Too noisy to tell")
    res["headline"]["h1_verdict"] = text.H1_BOUNDED
    assert text.h1_title(res).startswith("No partisan sensitivity detected")
    res["headline"]["h1_verdict"] = text.H1_SHARED
    assert "but so did the non-AI basket" in text.h1_title(res)


def test_h2_null_says_no_visible_link_and_valid_result(res):
    """Row 3."""
    ct = text.h2_chart(res)
    assert ct.title.startswith("No visible link")
    assert "That's a valid result" in ct.so_what
    res["headline"]["h2_verdict"] = text.H2_YES
    assert text.h2_chart(res).title.startswith("Names with higher pre-election betas did better")


def test_negative_h2_correlation_is_mentioned_once_as_exploratory(bundle, res):
    """The two-sided p of the wrong-tail correlation appears once, labelled, never as a title."""
    note = text.h2_exploratory_note(res)
    two = text.pval(text.primary_h2(res)["p_two"])
    assert note.startswith("Exploratory, not a finding") and two in note
    cts = text.chart_texts(res, bundle.series)
    everything = " ".join(
        [text.headline(res), *(f"{c.title} {c.so_what} {c.expert}" for c in cts.values())]
        + [c.finding for c in text.cards(res)]
        + [body for _, body in text.what_it_means(res)]
        + [f"{a} {b}" for k in ("H1", "H2") for a, b in text.checklist_lines(res, k)]
    )
    assert two not in everything and "two-sided" not in cts["h2"].expert
    md = findings.render(res, "0" * 12)
    assert md.count(f"two-sided p = {two}") == 1
    res["h2"]["groups"]["ai"]["windows"]["close3_close4"]["rho"] = 0.2
    assert text.h2_exploratory_note(res) is None


def test_exploratory_blocks_are_tagged_and_stay_out_of_the_headline(bundle, res):
    """Row 4."""
    cts = text.chart_texts(res, bundle.series)
    assert all(cts[k].tag == text.EXPLORATORY for k in EXPLORATORY_KEYS)
    assert all(cts[k].so_what.startswith("Exploratory.") for k in EXPLORATORY_KEYS)
    assert [k for k, c in cts.items() if c.tag == text.EXPLORATORY] == list(EXPLORATORY_KEYS)
    before = (text.headline(res), text.cards(res), text.what_it_means(res))
    res["exploratory"] = {}
    res["robustness"] = []
    assert (text.headline(res), text.cards(res), text.what_it_means(res)) == before


def test_h3_always_carries_the_descriptive_label(bundle, res):
    """Row 5."""
    label = "Descriptive only: one night, and the futures path was seen before the plan was frozen"
    assert text.H3_LABEL == label
    for instruments in (res["h3"]["instruments"], {"NQ": {"n_bars": 1, "rows": []}}):
        res["h3"]["instruments"] = instruments
        cts = text.chart_texts(res, bundle.series)
        for key in ("h3_night", "h3_lags"):
            assert label in cts[key].so_what and cts[key].tag == text.DESCRIPTIVE


def test_h4_title_follows_the_ordering_verdict(res):
    assert text.h4_title(res).endswith("every bar sits in the noise zone")
    res["h4"]["rows"][2]["beyond_band"] = True
    assert "only isolated bars" in text.h4_title(res)
    res["h4"]["verdict"] = "odds first"
    res["h4"]["rows"][4]["t"] = 9.0  # lag +1
    assert text.h4_title(res) == "Senate odds tended to move about 1 hour before AI stocks"


def test_missing_parts_say_not_in_the_results(bundle, res):
    del res["h4"], res["exploratory"]["e3"]
    res["h1"]["ai"]["mde10_pct"] = None
    cts = text.chart_texts(res, {})
    assert cts["h4"].missing and cts["e3"].missing and cts["odds"].missing
    assert cts["h4"].title == "Not in the results"
    assert not cts["h1"].missing and "not in the results" in text.h1_finding(res)
    assert charts.h4_figure(res) is None and charts.odds_figure(None, res) is None
    assert findings.render(res, "0" * 12).count("Not in the results.") >= 1


# ---------------------------------------------------------------- findings report


def _json_numbers(node, out: set[float]) -> set[float]:
    """Every number in the results tree, in its strings and in its keys (absolute values).

    Keys count because design constants live there (`ci90`, `MDE80`, `band_max_abs_t_95`)."""
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(float(t) for t in LOOSE_NUMBER.findall(str(k)))
            _json_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _json_numbers(v, out)
    elif isinstance(node, bool) or node is None:
        pass
    elif isinstance(node, int | float):
        out.add(abs(float(node)))
    elif isinstance(node, str):
        out.update(float(t) for t in LOOSE_NUMBER.findall(node))
    return out


def untraced_numbers(md: str, results: dict) -> list[str]:
    """Number tokens of the report that neither equal nor round from a results value (as it is,
    or x100 for a share or probability printed as percent or points)."""
    values = _json_numbers(results, set())
    values |= {100 * v for v in values if v <= 1}
    by_dec = {d: {float(f"{v:.{d}f}") for v in values} for d in range(0, 5)}
    body = INDEX_NAMES.sub("", HEX.sub("", md))
    body = re.sub(r"^#+ \d+\. ", "", body, flags=re.MULTILINE)  # section numbers
    body = re.sub(r"(?<=\d),(?=\d{3})", "", body)  # thousands separators
    missing = []
    for tok in sorted(set(NUMBER.findall(body))):
        dec = len(tok.split(".")[1]) if "." in tok else 0
        if float(tok) not in by_dec[min(dec, 4)]:
            missing.append(tok)
    return missing


def test_every_number_in_the_findings_traces_to_the_results(bundle):
    """Row 6."""
    md = findings.render(bundle.results, findings.fingerprint(FIXTURE / "results.json"))
    assert len(NUMBER.findall(md)) > 100, "the report must contain numbers to trace"
    assert untraced_numbers(md, bundle.results) == []


def test_the_tracer_catches_an_invented_number(bundle):
    """Mutation check of the row-6 test."""
    md = findings.render(bundle.results, "0" * 12) + "\nAn edge of 123.457% per trade.\n"
    assert untraced_numbers(md, bundle.results) == ["123.457"]


def test_page_text_numbers_trace_too(bundle):
    """The page's own wording (titles built from chart series excepted) holds to the same rule."""
    res = bundle.results
    cts = text.chart_texts(res, bundle.series)
    series_built = {"odds", "returns", "e1"}
    page = "\n".join(
        f"{c.title} {c.how_to_read} {c.so_what} {c.expert}"
        for k, c in cts.items()
        if k not in series_built
    )
    page += "\n".join(i for _, items in text.methods(res) for i in items)
    page += text.setup_text(res) + text.DISCLOSURE + " ".join(text.does_not_show(res))
    assert untraced_numbers(page, res) == []


def test_template_has_digits_only_in_section_numbers_and_ids():
    source = findings.TEMPLATE_PATH.read_text(encoding="utf-8")
    body = re.sub(r"\{\{\w+\}\}", "", source)  # slot names
    body = re.sub(r"^## \d+\. ", "## ", body, flags=re.MULTILINE)
    body = re.sub(r"\bH\d\w?\b", "", body)
    assert re.findall(r"\d", body) == []
    assert re.findall(r"\d", "## 3. H1\nA beta of 0.5%") != []  # the rule can fail


def test_findings_follow_the_verdicts_and_are_deterministic(bundle, res, tmp_path):
    md = findings.render(bundle.results, "0" * 12)
    assert f"**{text.headline(bundle.results)}.**" in md.split("## 2.")[0]
    assert md.count(text.H3_LABEL) >= 2 and "## 8. Exploratory" in md
    assert "{{" not in md and md.endswith(text.FOOTER + "\n")
    a = findings.write_report(FIXTURE, tmp_path / "a.md")
    b = findings.write_report(FIXTURE, tmp_path / "b.md")
    assert a.read_bytes() == b.read_bytes() and b"\r" not in a.read_bytes()
    assert "AI stocks carried a partisan beta" in findings.render(_as_ai_beta(res), "0" * 12)
    with pytest.raises(KeyError):
        findings.fill("{{nope}}", {})
    with pytest.raises(findings.ReportInputError):
        findings.write_report(tmp_path / "absent", tmp_path / "c.md")


def test_cli_report_writes_the_findings(monkeypatch, tmp_path, capsys):
    out = tmp_path / "findings.md"
    monkeypatch.setattr(findings, "FINDINGS_PATH", out)
    monkeypatch.setenv(BUNDLE_DIR_ENV, str(FIXTURE))
    assert cli_main(["report"]) == 0
    assert out.read_text(encoding="utf-8").startswith("# The partisan beta of AI: findings")
    monkeypatch.setenv(BUNDLE_DIR_ENV, str(tmp_path / "absent"))
    assert cli_main(["report"]) == 2
    assert "run `analyse` and `publish` first" in capsys.readouterr().out


@pytest.mark.skipif(not (BUNDLE_DIR / "results.json").is_file(), reason="no published bundle")
def test_committed_findings_match_the_published_bundle():
    real = load_bundle(BUNDLE_DIR)
    md = findings.render(real.results, findings.fingerprint(BUNDLE_DIR / "results.json"))
    assert untraced_numbers(md, real.results) == []
    assert findings.FINDINGS_PATH.read_text(encoding="utf-8") == md, "re-run `election report`"


# ---------------------------------------------------------------- figures


def _figures(bundle, theme):
    r, s = bundle.results, bundle.series
    return {
        "odds": charts.odds_figure(s["odds_daily"], r, theme),
        "returns": charts.returns_figure(s["cum_log_returns"], r, theme),
        "h1": charts.h1_figure(r, theme),
        "h5": charts.h5_figure(r, theme),
        "h2": charts.h2_figure(r, theme),
        "h2b": charts.h2b_figure(r, theme),
        "h3_night": charts.night_figure(s["h3_night"], theme),
        "h3_lags": charts.h3_lag_figure(r, theme),
        "h4": charts.h4_figure(r, theme),
        "e2_term": charts.e2_term_figure(s["e2_vol"], theme),
        "e2_moves": charts.e2_moves_figure(r, theme),
        "e1": charts.e1_figure(s["e1_rolling"], theme),
        "e3": charts.e3_figure(s["e3_scatter"], theme),
        "e5": charts.e5_figure(s["e5_car"], theme),
    }


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_figure_builds_with_one_y_axis_per_panel(bundle, theme):
    figs = _figures(bundle, theme)
    assert all(f is not None and len(f.data) > 0 for f in figs.values())
    for name, fig in figs.items():
        layout = fig.to_plotly_json()["layout"]
        overlaid = [k for k, v in layout.items() if k.startswith("yaxis") and "overlaying" in v]
        assert overlaid == [], name
    assert charts.palette("dark") != charts.palette("light")


def test_figures_plot_the_bundle_values(bundle):
    figs, r = _figures(bundle, "light"), bundle.results
    dot = figs["h1"].data[1]
    assert dot.x[0] == r["h1"]["ai"]["b10_pct"] and dot.y[0] == "AI basket"
    assert figs["h1"].data[0].base[0] == -r["h1"]["ai"]["mde10_pct"]
    ai = [t for t in figs["h2"].data if t.name in text.SUB_LABELS.values()]
    assert sum(len(t.x) for t in ai) == r["h2"]["groups"]["ai"]["windows"]["close3_close4"]["n"]
    assert len({t.marker.symbol for t in ai}) == 4  # identity is not colour alone
    assert len(figs["h2b"].data[0].y) == r["h2b"]["ai"]["n"]
    night = figs["h3_night"]
    assert {t.yaxis for t in night.data} == {"y", "y2"} and night.layout.xaxis.matches == "x2"
    assert str(night.data[2].x[0]).startswith("2026-11-03T18:05")  # 23:05 UTC shown as ET
    assert list(figs["h4"].data[0].y) == [row["t"] for row in r["h4"]["rows"]]


def test_figures_are_none_without_their_inputs():
    assert charts.h1_figure({}) is None and charts.h2_figure({}) is None
    assert charts.night_figure(None) is None and charts.e2_moves_figure({}) is None
    assert charts.e1_figure(None) is None and charts.h3_lag_figure({}) is None


# ---------------------------------------------------------------- the page


def _walk(node):
    yield node
    for child in getattr(node, "children", {}).values():
        yield from _walk(child)


def page_text(at: AppTest) -> str:
    protos = "\n".join(str(el.proto) for el in _walk(at.main) if hasattr(el, "proto"))
    return protos.replace("\\'", "'")


def run_app(monkeypatch, folder: Path) -> AppTest:
    monkeypatch.setenv(BUNDLE_DIR_ENV, str(folder))
    at = AppTest.from_file(str(APP), default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_page_renders_every_section_on_the_fixture(monkeypatch):
    at = run_app(monkeypatch, FIXTURE)
    body = page_text(at)
    assert at.title[0].value.startswith("Too noisy to tell")
    for heading in ("H1 ·", "H5 ·", "H2 ·", "H3 ·", "H4 ·", "For the derivatives desk"):
        assert any(h.value.startswith(heading) for h in at.header), heading
    assert text.H3_LABEL in body and "That's a valid result" in body
    assert body.count(">Exploratory</span>") >= 7  # two sections + five blocks
    assert "How this was done" in body and text.FOOTER in body
    assert "not in the results" not in body.lower()
    assert body.count("0.047") == 1  # the wrong-tail two-sided p: once, in the exploratory note


def test_page_survives_a_bundle_with_parts_missing(monkeypatch, tmp_path, res):
    del res["h4"], res["exploratory"]["e2"]
    res["series"].pop("odds_daily")
    (tmp_path / "results.json").write_text(json.dumps(res), encoding="utf-8")
    body = page_text(run_app(monkeypatch, tmp_path))
    assert body.count("not in the results") >= 3


def test_missing_bundle_shows_one_clear_message(monkeypatch, tmp_path):
    """Row 7."""
    at = run_app(monkeypatch, tmp_path / "absent")
    assert len(at.info) == 1 and "python -m poly_actor.election analyse" in at.info[0].value
    assert at.title[0].value == "The partisan beta of AI" and not at.header
    (tmp_path / "results.json").write_text("{not json", encoding="utf-8")
    assert load_bundle(tmp_path) is None


@pytest.mark.skipif(not (BUNDLE_DIR / "results.json").is_file(), reason="no published bundle")
def test_page_renders_on_the_published_bundle(monkeypatch):
    """Row 8, offline: the real bundle renders with no exception and nothing missing."""
    body = page_text(run_app(monkeypatch, BUNDLE_DIR))
    assert "not in the results" not in body.lower()


def _write_bundle(folder: Path, results: object) -> None:
    (folder / "results.json").write_text(json.dumps(results), encoding="utf-8")


def test_load_bundle_rejects_non_object_json_with_a_warning(tmp_path, caplog):
    _write_bundle(tmp_path, [1, 2, 3])
    with caplog.at_level("WARNING"):
        assert load_bundle(tmp_path) is None
    assert "not a JSON object" in caplog.text


def test_load_bundle_invalid_json_warns(tmp_path, caplog):
    (tmp_path / "results.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert load_bundle(tmp_path) is None
    assert "unreadable bundle" in caplog.text


def test_load_bundle_skips_missing_and_unreadable_series_with_warnings(tmp_path, caplog):
    (tmp_path / "series").mkdir()
    (tmp_path / "series" / "good.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "series" / "bad.csv").write_bytes(b"")  # pandas: EmptyDataError (a ValueError)
    _write_bundle(
        tmp_path,
        {"series": {"good": "series/good.csv", "bad": "series/bad.csv", "gone": "series/x.csv"}},
    )
    with caplog.at_level("WARNING"):
        got = load_bundle(tmp_path)
    assert got is not None and list(got.series) == ["good"]
    assert "unreadable series" in caplog.text and "is missing" in caplog.text


def test_bundle_signature_changes_on_rewrite_and_is_empty_without_folder(tmp_path):
    assert bundle_signature(tmp_path / "absent") == ()
    _write_bundle(tmp_path, {})
    before = bundle_signature(tmp_path)
    path = tmp_path / "results.json"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert bundle_signature(tmp_path) != before


def test_guarded_block_logs_the_cause_when_inputs_are_missing(bundle, caplog):
    res = copy.deepcopy(bundle.results)
    del res["h4"]
    with caplog.at_level("WARNING"):
        block = text.h4_chart(res)
    assert block.missing and "not rendered from the bundle" in caplog.text


# ---------------------------------------------------------------- validator round 1


def test_findings_never_call_present_data_missing(bundle):
    """r1 major 1: a block whose data is in the bundle is stated, also without chart series."""
    md = findings.render(bundle.results, "0" * 12)
    assert "not in the results" not in md.lower()
    cts = text.chart_texts(bundle.results, {})
    present = [k for k in cts if k not in ("odds", "returns")]  # those two are series-only
    assert [k for k in present if cts[k].missing] == []
    e1 = bundle.results["exploratory"]["e1"]
    assert text.pct(e1["last30_minus_before_b10_pct"]) in md.split("E1 · ")[1].split("###")[0]


def test_e1_title_and_so_what_agree(bundle, res):
    """r1 minor: the title states the post-hoc shift; it never says the estimate was stable."""
    with_series = text.e1_chart(res, bundle.series["e1_rolling"])
    alone = text.e1_chart(res)
    assert with_series.title == alone.title and "not stable" in alone.title
    assert "5.6% per 10 points lower" in alone.title and "after the fact" in alone.title
    assert "on both sides of zero" in with_series.so_what and "ranged" not in alone.so_what
    assert "not chosen in advance" in alone.so_what
    res["exploratory"]["e1"]["last30_minus_before_b10_pct"] = 2.0
    assert "2.0% per 10 points higher" in text.e1_chart(res).title


def test_e5_title_is_sign_aware(res):
    """r1 minor: -4.49 overall and +1.11 after the event day is a reversal, not a narrowing."""
    title = text.e5_chart(res).title
    assert "trailed" in title and "ran the other way (+1.1%)" in title
    assert "narrowed" not in title
    res["exploratory"]["e5"]["car_top_minus_bottom_ex_event_day_pct"] = -2.0
    assert "kept going the same way after the event day (−2.0%)" in text.e5_chart(res).title
    res["exploratory"]["e5"]["car_top_minus_bottom_pct"] = 3.0
    assert "beat" in text.e5_chart(res).title and "ran the other way" in text.e5_chart(res).title


def test_methods_and_amendments_claim_only_what_was_done(bundle):
    """r1 major 2 and minors: no surprise construction is claimed; A1 to A3 are all named."""
    res = bundle.results
    prose = " ".join(i for _, items in text.methods(res) for i in items)
    assert "urprise" not in prose and "A fixed event window on abnormal returns" in prose
    notes = text.amendments(res)
    assert [n[:2] for n in notes] == ["A1", "A2", "A3"] and "(A1, A2, A3)" in text.DISCLOSURE
    assert "opening level" in notes[2] and untraced_numbers(" ".join(notes), res) == []
    meaning = " ".join(f"{a} {b}" for a, b in text.what_it_means(res))
    assert text.points(res["h2"]["event_dp_sen"]) not in meaning  # MDE not set beside the move
    everything = meaning + text.WHY_IT_MATTERS + text.e2_moves_chart(res).so_what
    for phrase in ("wasted premium", "simply noisier", "did not describe"):
        assert phrase not in everything
    md = findings.render(res, "0" * 12)
    assert md.count("- A3, from the independent validation") == 1

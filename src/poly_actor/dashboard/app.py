"""Streamlit layout only. All wording is in text.py, figures in charts.py, data in load.py.

Run: ``streamlit run src/poly_actor/dashboard/app.py``. Reads ``data/clean/`` (or the folder in
the POLY_ACTOR_CLEAN_DIR environment variable); never touches the network or writes files.

Streamlit executes this file top to bottom on every rerun, so ``main()`` is called at module
level (there is no ``__main__`` guard under ``streamlit run``). Tests drive it through
``streamlit.testing.v1.AppTest`` instead of importing it.
"""

from __future__ import annotations

import html
import os
import zlib
from pathlib import Path

import pandas as pd
import streamlit as st

from poly_actor.config import CLEAN_DIR
from poly_actor.dashboard import charts, text
from poly_actor.dashboard.contract import PairResults
from poly_actor.dashboard.load import (
    PairSpec,
    load_all_results,
    load_pair_specs,
    load_panel,
    panel_coverage,
    results_signature,
)

CLEAN_DIR_ENV = "POLY_ACTOR_CLEAN_DIR"
SELECTED = "selected_pair"
SCROLL_FLAG = "scroll_to_evidence"

CSS = """
<style>
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.8rem;
  font-weight:600;background:#e5e7eb;color:#374151}
.badge.lead{background:#dbeafe;color:#1e40af}
.badge.same{background:#fef3c7;color:#92400e}
.badge.none{background:#e5e7eb;color:#374151}
.meter i{display:inline-block;width:18px;height:6px;margin-right:3px;border-radius:3px;
  background:#e5e7eb}
.meter i.on{background:#2563eb}
.tech{font-family:ui-monospace,Consolas,monospace;font-size:.75rem;color:#6b7280;
  margin:-6px 0 8px 1.4rem}
.chip{display:inline-block;margin:0 6px 6px 0;padding:3px 10px;border:1px solid #d1d5db;
  border-radius:999px;font-size:.85rem}
.st-key-pair_nav{position:sticky;top:2.9rem;z-index:99;background:#fff;padding:6px 0;
  border-bottom:1px solid #e5e7eb}
</style>
"""

_BADGE_CLASS = {
    "Polymarket moves first": "lead",
    "Moves at the same time": "same",
    "No head start": "none",
    "No extra information": "none",
}


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _badge(results: PairResults | None) -> str:
    label = text.badge_label(results)
    cls = _BADGE_CLASS.get(label, "")
    return f'<span class="badge {cls}">{_esc(label)}</span>'


def _meter(results: PairResults | None) -> str:
    view = text.confidence_view(results.confidence if results else None)
    bars = "".join(f'<i class="{"on" if i < view.filled else ""}"></i>' for i in range(3))
    return f'<span class="meter">{bars}</span> Confidence: <b>{_esc(view.word)}</b>'


@st.cache_data(show_spinner=False)
def _specs() -> tuple[PairSpec, ...]:
    return load_pair_specs()


@st.cache_data(show_spinner=False)
def _panel(clean_dir: str, pair_id: str) -> pd.DataFrame | None:
    return load_panel(Path(clean_dir), pair_id)


@st.cache_data(show_spinner=False)
def _results(clean_dir: str, signature: tuple) -> text.Results:
    """Results JSON, re-read only when a results file changes (signature = names + mtimes)."""
    return load_all_results(Path(clean_dir), _specs())


def _open_pair(pair_id: str) -> None:
    st.session_state[SELECTED] = pair_id
    st.session_state[SCROLL_FLAG] = True


def _render_top(specs: tuple[PairSpec, ...], results: text.Results) -> None:
    note = text.banner(results)
    if note:
        st.warning(note)
    st.caption("Signal Lab · the answer so far")
    st.title(text.headline(results))
    st.write(text.tally(results))
    st.subheader("One card per bet")
    cols = st.columns(len(specs))
    for i, (col, spec) in enumerate(zip(cols, specs, strict=True)):
        res = results[spec.pair_id]
        info = text.pair_info(spec.pair_id)
        with col, st.container(border=True):
            st.markdown(f"**{info.name}**")
            st.caption(info.question)
            st.markdown(_badge(res), unsafe_allow_html=True)
            st.write(text.finding(spec.pair_id, res, spec.tickers[0]))
            st.markdown(_meter(res), unsafe_allow_html=True)
            st.caption(text.confidence_view(res.confidence if res else None).reason)
            st.button(
                "See the evidence →", key=f"open_{i}", on_click=_open_pair, args=(spec.pair_id,)
            )


def _render_rules() -> None:
    st.subheader("What counts as evidence")
    st.write(
        "We only call something a lead when it passes all of these. Otherwise the verdict is "
        '"no head start", which is a real answer and not a failure.'
    )
    counts, not_counts, null = st.columns(3)
    with counts, st.container(border=True):
        st.markdown("**Counts**")
        st.markdown("\n".join(f"- {t}" for t in text.COUNTS))
    with not_counts, st.container(border=True):
        st.markdown("**Doesn't count**")
        st.markdown("\n".join(f"- {t}" for t in text.DOES_NOT_COUNT))
    with null, st.container(border=True):
        st.markdown('**"No head start" is a result too**')
        st.write(text.NULL_RESULT)


def _render_verdict(pair_id: str, res: PairResults | None, ticker: str) -> None:
    info = text.pair_info(pair_id)
    with st.container(border=True):
        st.caption(info.name)
        st.header(text.finding(pair_id, res, ticker))
        view = text.confidence_view(res.confidence if res else None)
        st.markdown(_badge(res) + " &nbsp; " + _meter(res), unsafe_allow_html=True)
        st.write(f"**So what.** {text.so_what(res, ticker)}")
        if res is not None and res.verdict_reason:
            st.caption(f"Why this verdict: {res.verdict_reason}")
        st.markdown(f"**How sure are we? {_esc(view.word)}**")
        st.write(view.reason)
        for plain, technical in text.checklist_lines(res):
            st.write(plain)
            if technical:
                st.markdown(f'<div class="tech">{_esc(technical)}</div>', unsafe_allow_html=True)


def _not_shown(state: str) -> None:
    computed = state == "not_computed"
    st.subheader("Not computed for this stock" if computed else text.NOT_RUN)
    st.info(text.not_computed_note() if computed else text.not_run_chart_note())


def _render_chart1(pair_id: str, res: PairResults | None, ticker: str) -> None:
    xc = text.xcorr_for(res, ticker)
    state = text.chart1_state(res, ticker)
    with st.container(border=True):
        st.caption("1 · Who moves first?")
        if state == "not_in_plan":
            st.subheader(text.NOT_IN_PLAN)
            st.info(text.NOT_IN_PLAN_NOTE)
            return
        if state != "chart":
            _not_shown(state)
            return
        st.subheader(text.xcorr_title(pair_id, xc, text.is_preview(res)))
        st.write(f"**How to read.** {text.xcorr_how_to_read(xc.residualised is not None)}")
        if xc.residualised is not None:
            st.markdown("**After taking out Bitcoin's own price**")
            st.plotly_chart(charts.xcorr_figure(xc.residualised), width="stretch")
            st.markdown("**Raw link**")
        st.plotly_chart(charts.xcorr_figure(xc), width="stretch")
        st.write(f"**So what.** {text.xcorr_so_what(xc)}")
        note = text.stocks_first_note(res)
        if note:
            st.caption(note)
        with st.expander("For experts"):
            st.write(text.xcorr_expert(xc))


def _render_chart2(pair_id: str, res: PairResults | None, ticker: str) -> None:
    es = text.event_study_for(res, ticker)
    state = text.chart2_state(res, ticker)
    with st.container(border=True):
        st.caption(f"2 · What happens around {text.pair_info(pair_id).events}?")
        if state != "chart":
            _not_shown(state)
            return
        st.subheader(text.event_study_title(pair_id, es, text.is_preview(res)))
        st.write(f"**How to read.** {text.event_study_how_to_read(es)}")
        st.plotly_chart(charts.event_study_figure(es), width="stretch")
        st.write(f"**So what.** {text.event_study_so_what(es)}")
        with st.expander("For experts"):
            st.write(text.event_study_expert(es, res.n_events, res.params.get("ci_level")))


def _render_chart3(pair_id: str, panel: pd.DataFrame | None, ticker: str) -> None:
    with st.container(border=True):
        st.caption("3 · The raw data, for context")
        if panel is None or f"ret_{ticker}" not in panel.columns:
            st.subheader("No aligned price data for this stock")
            return
        st.subheader(f"Polymarket's estimate and {text.ticker_label(ticker)}, side by side")
        st.write(
            "**How to read.** Top: the Polymarket crowd's estimate. Bottom: the stock. They share "
            "the same timeline, so you can look straight down from a jump in one to the other. "
            "Breaks in a line are hours with no data, such as nights and weekends for stocks."
        )
        st.plotly_chart(charts.raw_data_figure(panel, pair_id, ticker), width="stretch")
        st.write(
            "**So what.** Use this chart to sanity-check, not to judge. Lines that look alike "
            "can't tell you who moved first. Charts 1 and 2 do that job."
        )


def _render_evidence(spec: PairSpec, res: PairResults | None, panel: pd.DataFrame | None) -> None:
    st.markdown('<div id="evidence"></div>', unsafe_allow_html=True)
    _render_verdict(spec.pair_id, res, spec.tickers[0])
    ticker = st.radio(
        "Compare against",
        spec.tickers,
        horizontal=True,
        format_func=text.ticker_chip,
        key=f"ticker_{zlib.crc32(spec.pair_id.encode())}",
    )
    cov = panel_coverage(panel) if panel is not None else None
    if cov:
        st.caption(
            text.coverage_line(cov.first, cov.last, cov.both_trading_rows, cov.median_quote_age_s)
        )
    _render_chart1(spec.pair_id, res, ticker)
    _render_chart2(spec.pair_id, res, ticker)
    _render_chart3(spec.pair_id, panel, ticker)


def _scroll_to_evidence() -> None:
    st.html(
        "<script>const e=document.getElementById('evidence');if(e){e.scrollIntoView();}</script>",
        unsafe_allow_javascript=True,
    )


def main() -> None:
    st.set_page_config(page_title="Signal Lab", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    clean_dir = Path(os.environ.get(CLEAN_DIR_ENV, CLEAN_DIR))
    specs = _specs()
    results = _results(str(clean_dir), results_signature(clean_dir))
    by_id = {s.pair_id: s for s in specs}

    _render_top(specs, results)
    _render_rules()

    st.subheader("Pair evidence")
    with st.container(key="pair_nav"):
        st.radio(
            "Switch pair",
            list(by_id),
            key=SELECTED,
            horizontal=True,
            label_visibility="collapsed",
            format_func=lambda pid: text.tab_label(pid, results[pid]),
        )
    pair_id = st.session_state[SELECTED]
    _render_evidence(by_id[pair_id], results[pair_id], _panel(str(clean_dir), pair_id))
    if st.session_state.pop(SCROLL_FLAG, False):
        _scroll_to_evidence()

    with st.expander("Plain words used here, and the technical terms behind them"):
        for term, plain, technical in text.glossary(text.params_of(results)):
            st.markdown(f"**{term}.** {plain} *({technical})*")
    st.caption(text.FOOTER)


main()

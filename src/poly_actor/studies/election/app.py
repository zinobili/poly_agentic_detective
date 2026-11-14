"""Streamlit layout of the election study ("the partisan beta of AI"). Layout only: every word is
in report_text.py, every figure in charts.py, loading in report_load.py.

Run: ``streamlit run src/poly_actor/studies/election/app.py``. Reads the published bundle in
``reports/election/`` (or the folder in the POLY_ACTOR_ELECTION_BUNDLE environment variable);
never touches the network, writes nothing and computes no statistics.

Streamlit executes this file top to bottom on every rerun, so ``main()`` is called at module
level. Tests drive it through ``streamlit.testing.v1.AppTest``.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from poly_actor.core.ui import style
from poly_actor.studies.election import charts
from poly_actor.studies.election import report_text as text
from poly_actor.studies.election.report_load import (
    BUILD_COMMAND,
    Bundle,
    bundle_dir,
    bundle_signature,
    load_bundle,
)

PAGE_TITLE = "The partisan beta of AI"

EXTRA_CSS = """
<style>
.tag{display:inline-block;padding:1px 9px;border-radius:999px;font-size:.75rem;font-weight:600;
  border:1px solid #b45309;color:#b45309;margin-left:6px;vertical-align:middle}
.tag.desc{border-color:#6b7280;color:#6b7280}
.kicker{font-size:.85rem;color:#6b7280;font-weight:600;letter-spacing:.02em}
.techline{font-family:ui-monospace,Consolas,monospace;font-size:.78rem;color:#6b7280;
  margin:-4px 0 10px 0}
.badge.null{background:#e5e7eb;color:#374151}
</style>
"""

_BADGE_CLASS = {
    text.H1_AI: "lead",
    text.H2_YES: "lead",
    text.H1_SHARED: "same",
}
SECTIONS = (
    ("answer", "The answer"),
    ("setup", "The set-up"),
    ("h1", "H1 Partisan beta"),
    ("h5", "H5 Which part"),
    ("h2", "H2 Election night"),
    ("h3", "H3 Minute by minute"),
    ("h4", "H4 Who moved first"),
    ("derivatives", "Derivatives desk"),
    ("exploratory", "Other exploratory"),
    ("method", "How this was done"),
)


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


def _tag(tag: str | None) -> str:
    if not tag:
        return ""
    cls = "tag desc" if tag == text.DESCRIPTIVE else "tag"
    return f'<span class="{cls}">{_esc(tag)}</span>'


def _badge(verdict: str) -> str:
    return f'<span class="badge {_BADGE_CLASS.get(verdict, "none")}">{_esc(verdict)}</span>'


def _meter(conf: text.Confidence) -> str:
    bars = "".join(f'<i class="{"on" if i < conf.filled else ""}"></i>' for i in range(3))
    return f'<span class="meter">{bars}</span> Confidence: <b>{_esc(conf.word)}</b>'


def _tech(line: str) -> None:
    st.markdown(f'<div class="tech">{_esc(line)}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _bundle(folder: str, signature: tuple) -> Bundle | None:
    """The bundle, re-read only when one of its files changes (signature = names + mtimes)."""
    return load_bundle(Path(folder))


def _section(key: str, title: str, tag: str | None = None) -> None:
    st.header(title, anchor=key, divider="gray")
    if tag:
        st.markdown(_tag(tag), unsafe_allow_html=True)


def _table(rows: list[dict[str, str]]) -> None:
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info(text.MISSING.capitalize() + ".")


def _chart(
    ct: text.ChartText,
    fig: go.Figure | None,
    key: str,
    extra: Callable[[], None] | None = None,
) -> None:
    """One chart block: kicker, action title, how to read, figure, so what, for experts."""
    with st.container(border=True):
        st.markdown(
            f'<span class="kicker">{_esc(ct.kicker)}</span>{_tag(ct.tag)}', unsafe_allow_html=True
        )
        if ct.missing:
            st.subheader(ct.title, anchor=False)
            st.info("This block's inputs are " + text.MISSING + ".")
            return
        st.subheader(ct.title, anchor=False)
        st.write(f"**How to read.** {ct.how_to_read}")
        if fig is None:
            st.info("The chart data is " + text.MISSING + ".")
        else:
            st.plotly_chart(fig, width="stretch", key=f"fig_{key}")
        st.write(f"**So what.** {ct.so_what}")
        if extra is not None:
            extra()
        with st.expander("For experts"):
            st.write(ct.expert)


def _checklist(res: text.Results, key: str) -> None:
    for plain, technical in text.checklist_lines(res, key):
        st.write(plain)
        if technical:
            _tech(technical)


def _render_answer(res: text.Results) -> None:
    st.caption("Signal Lab · election study · the 2026 US midterm")
    st.title(text.headline(res), anchor="answer")
    st.markdown(
        f'<div class="techline">{_esc(text.headline_technical(res))}</div>',
        unsafe_allow_html=True,
    )
    st.write(text.QUESTION)
    st.caption(f"{text.WHY_IT_MATTERS} {text.data_line(res)}")
    st.markdown(
        "Jump to: " + " · ".join(f"[{label}](#{key})" for key, label in SECTIONS[1:]),
    )
    for col, card in zip(st.columns(2), text.cards(res), strict=True):
        with col, st.container(border=True):
            st.markdown(f"**{card.key} · {card.question}**")
            st.markdown(_badge(card.verdict), unsafe_allow_html=True)
            st.write(card.finding)
            st.markdown(_meter(card.confidence), unsafe_allow_html=True)
            st.caption(card.confidence.reason)
            _checklist(res, card.key)
    with st.container(border=True):
        st.markdown("**What this means for an AI book going into an election**")
        for lead, body in text.what_it_means(res):
            st.markdown(f"- **{lead}** {body}")
        st.caption(
            "A null is a result too: it tells you what the data could and could not see. "
            "Everything tagged exploratory or descriptive below is context, not evidence."
        )


def _render_setup(b: Bundle, cts: dict[str, text.ChartText], theme: str | None) -> None:
    _section("setup", "The set-up: what happened")
    st.write(text.setup_text(b.results))
    _chart(cts["odds"], charts.odds_figure(b.series.get("odds_daily"), b.results, theme), "odds")
    _chart(
        cts["returns"],
        charts.returns_figure(b.series.get("cum_log_returns"), b.results, theme),
        "returns",
    )


def _render_h1(res: text.Results, cts: dict[str, text.ChartText], theme: str | None) -> None:
    _section("h1", "H1 · Was there a partisan beta?")
    _chart(cts["h1"], charts.h1_figure(res, theme), "h1", lambda: st.info(text.mde_plain(res)))
    with st.container(border=True):
        st.markdown('<span class="kicker">H1 · Does the answer survive other choices?</span>',
                    unsafe_allow_html=True)  # fmt: skip
        st.write(text.robustness_note(res))
        _table(text.robustness_table(res))
        st.caption(
            "Rows marked Exploratory (E4) swap in a different odds series. They were not part "
            "of the primary test and are not corrected for the number of rows."
        )


def _render_h2(res: text.Results, cts: dict[str, text.ChartText], theme: str | None) -> None:
    _section("h2", "H2 · Did the betas predict election night?")

    def extra() -> None:
        note = text.h2_exploratory_note(res)
        if note:
            st.warning(note)

    _chart(cts["h2"], charts.h2_figure(res, theme), "h2", extra)
    _chart(cts["h2b"], charts.h2b_figure(res, theme), "h2b")
    with st.container(border=True):
        st.markdown('<span class="kicker">H2 · Other windows and the non-AI names</span>',
                    unsafe_allow_html=True)  # fmt: skip
        st.write(
            "The same test on the two secondary windows, on the non-AI names and on both groups "
            "pooled. The p-value shown is the pre-registered one-sided test."
        )
        _table(text.h2_windows_table(res))


def _render_exploratory(b: Bundle, cts: dict[str, text.ChartText], theme: str | None) -> None:
    res, s = b.results, b.series
    _section("derivatives", "For the derivatives desk", text.EXPLORATORY)
    st.write(
        "Nothing in this section was a pre-registered test. It shows how index volatility was "
        "priced around this election and three earlier ones, and whether the sensitivity in H1 "
        "was stable through the year."
    )
    _chart(cts["e2_moves"], charts.e2_moves_figure(res, theme), "e2_moves")
    _chart(cts["e2_term"], charts.e2_term_figure(s.get("e2_vol"), theme), "e2_term")
    _chart(cts["e1"], charts.e1_figure(s.get("e1_rolling"), theme), "e1")
    _section("exploratory", "Other exploratory looks", text.EXPLORATORY)
    _chart(cts["e3"], charts.e3_figure(s.get("e3_scatter"), theme), "e3")
    _chart(cts["e5"], charts.e5_figure(s.get("e5_car"), theme), "e5")


def _render_method(res: text.Results) -> None:
    _section("method", "How this was done")
    blocks = text.methods(res)
    for i in range(0, len(blocks), 2):
        for col, (heading, items) in zip(st.columns(2), blocks[i : i + 2], strict=False):
            with col, st.container(border=True):
                st.markdown(f"**{heading}**")
                st.markdown("\n".join(f"- {item}" for item in items))
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**What this does not show**")
        st.markdown("\n".join(f"- {item}" for item in text.does_not_show(res)))
    with right, st.container(border=True):
        st.markdown("**What had been seen before the plan was frozen**")
        st.write(text.DISCLOSURE)
        st.markdown("\n".join(f"- {item}" for item in text.amendments(res)))


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    theme = st.context.theme.type
    st.markdown(style.page_css(theme) + EXTRA_CSS, unsafe_allow_html=True)
    folder = bundle_dir()
    bundle = _bundle(str(folder), bundle_signature(folder))
    if bundle is None:
        st.title(PAGE_TITLE)
        st.info(text.missing_bundle_message(BUILD_COMMAND))
        return
    res = bundle.results
    cts = text.chart_texts(res, bundle.series)

    _render_answer(res)
    _render_setup(bundle, cts, theme)
    _render_h1(res, cts, theme)
    _section("h5", "H5 · Which part of the AI trade?")
    _chart(cts["h5"], charts.h5_figure(res, theme), "h5")
    _render_h2(res, cts, theme)
    _section("h3", "H3 · Election night, minute by minute", text.DESCRIPTIVE)
    st.caption(text.H3_LABEL + ".")
    _chart(cts["h3_night"], charts.night_figure(bundle.series.get("h3_night"), theme), "h3_night")
    _chart(cts["h3_lags"], charts.h3_lag_figure(res, theme), "h3_lags")
    _section("h4", "H4 · Who moved first?")
    _chart(cts["h4"], charts.h4_figure(res, theme), "h4")
    _render_exploratory(bundle, cts, theme)
    _render_method(res)

    with st.expander("Plain words used here, and the technical terms behind them"):
        for term, plain, technical in text.GLOSSARY:
            st.markdown(f"**{term}.** {plain} *({technical})*")
    st.caption(text.FOOTER)


main()

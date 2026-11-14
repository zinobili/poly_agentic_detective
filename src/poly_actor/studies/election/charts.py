"""Plotly figures of the election presentation. Pure: bundle in, figure out. No Streamlit, no
I/O, no statistics; the only arithmetic is chart transforms (percent scaling, rebasing a
cumulative log return, UTC -> Eastern Time).

One y-axis per panel, never two. Colours are a colour-blind-safe categorical order with its own
steps for the dark theme; identity is never carried by colour alone (legend, labels or marker
shape repeat it). A builder returns ``None`` when its inputs are not in the bundle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from poly_actor.studies.election.report_text import (
    BASKET_LABELS,
    INSTRUMENT_LABELS,
    SERIES_LABELS,
    SIGNAL_LABELS,
    SUB_LABELS,
    day,
    event_dates,
    get,
    sub_of,
)

Results = Mapping[str, Any]
ET = "America/New_York"

# Categorical slots in fixed order (blue, orange, aqua, yellow, magenta), light and dark steps.
PALETTE = {
    "light": {
        "series": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"),
        "neutral": "#8b8a85",
        "muted": "#b9b8b2",
        "zone": "rgba(120,120,116,0.16)",
        "ring": "#ffffff",
        "ink": "#52514e",
    },
    "dark": {
        "series": ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"),
        "neutral": "#a3a29b",
        "muted": "#6f6e69",
        "zone": "rgba(200,200,195,0.14)",
        "ring": "#0e1117",
        "ink": "#c3c2b7",
    },
}
SUB_SYMBOLS = {
    "semis": "circle",
    "hyperscalers": "square",
    "power_infra": "diamond",
    "software": "triangle-up",
}
LEGEND = {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0}
MARGIN = {"t": 48, "r": 24, "b": 40, "l": 56}


def palette(theme: str | None) -> dict[str, Any]:
    return PALETTE["dark" if theme == "dark" else "light"]


def _has(df: pd.DataFrame | None, *cols: str) -> bool:
    return df is not None and len(df) > 0 and all(c in df.columns for c in cols)


def _layout(fig: go.Figure, height: int, legend: bool = True) -> go.Figure:
    fig.update_layout(height=height, margin=MARGIN, legend=LEGEND, showlegend=legend)
    return fig


def _mark_day(fig: go.Figure, x: Any, label: str, pal: dict[str, Any], rows: int = 1) -> None:
    """A thin vertical marker with a label on the top panel (works on date axes)."""
    for row in range(1, rows + 1):
        fig.add_vline(x=x, line_color=pal["muted"], line_width=1, row=row, col=1)
    fig.add_annotation(
        x=x, y=1, yref="y domain", text=label, showarrow=False, xanchor="right", xshift=-4,
        yanchor="top", font={"size": 11, "color": pal["ink"]}, row=1, col=1,
    )  # fmt: skip


# ---------------------------------------------------------------- the set-up


def odds_figure(
    odds: pd.DataFrame | None, res: Results, theme: str | None = None
) -> go.Figure | None:
    """Chart A: the four Polymarket odds series over the life of the markets, in percent."""
    if not _has(odds, "session", "signal", "p"):
        return None
    pal = palette(theme)
    primary = get(res, "meta", "primary_signal")
    order = [s for s in get(res, "meta", "signals") or [] if s in set(odds["signal"])]
    fig = make_subplots(rows=1, cols=1)
    for i, sig in enumerate(order):
        g = odds[odds["signal"] == sig]
        fig.add_trace(
            go.Scatter(
                x=g["session"],
                y=100 * g["p"],
                name=SIGNAL_LABELS.get(sig, sig) + (" (the signal)" if sig == primary else ""),
                mode="lines",
                line={"color": pal["series"][i % 5], "width": 3 if sig == primary else 1.5},
                hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>",
            )
        )
    election = event_dates(res)[0]
    if election:
        _mark_day(fig, election, "Election day", pal)
    fig.update_yaxes(title_text="Polymarket odds (%)", range=[0, 100])
    fig.update_xaxes(title_text="Stock-market session")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, 380)


def returns_figure(
    cum: pd.DataFrame | None, res: Results, theme: str | None = None
) -> go.Figure | None:
    """Chart B: cumulative return (%) of the AI basket, its four parts, the placebo and RSP."""
    if not _has(cum, "session", "ai_composite"):
        return None
    pal = palette(theme)
    styles: dict[str, dict[str, Any]] = {
        "ai_composite": {"color": pal["series"][0], "width": 3.5},
        "placebo": {"color": pal["neutral"], "width": 2},
        "RSP": {"color": pal["neutral"], "width": 2, "dash": "dot"},
    }
    for i, sub in enumerate(SUB_LABELS, start=1):
        styles[sub] = {"color": pal["series"][i], "width": 1.5}
    fig = make_subplots(rows=1, cols=1)
    for col, line in styles.items():
        if col not in cum.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=cum["session"],
                y=100 * (np.exp(cum[col]) - 1),
                name=SERIES_LABELS.get(col, col),
                mode="lines",
                line=line,
                hovertemplate="%{y:+.1f}%<extra>%{fullData.name}</extra>",
            )
        )
    election = event_dates(res)[0]
    if election:
        _mark_day(fig, election, "Election day", pal)
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    fig.update_yaxes(title_text="Return since the start (%)", ticksuffix="%")
    fig.update_xaxes(title_text="Stock-market session")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, 420)


# ---------------------------------------------------------------- betas (H1, H5)


def beta_figure(
    rows: Sequence[tuple[str, Mapping[str, Any]]], theme: str | None = None
) -> go.Figure | None:
    """Dot and 90% range per row, over a grey bar of the too-small-to-detect zone (+/- MDE)."""
    rows = [(label, r) for label, r in rows if r and r.get("b10_pct") is not None]
    if not rows:
        return None
    pal = palette(theme)
    labels = [label for label, _ in rows]
    b = [r["b10_pct"] for _, r in rows]
    lo = [r["ci10_pct"][0] for _, r in rows]
    hi = [r["ci10_pct"][1] for _, r in rows]
    mde = [r.get("mde10_pct") or 0 for _, r in rows]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=labels,
            x=[2 * m for m in mde],
            base=[-m for m in mde],
            orientation="h",
            width=0.5,
            marker={"color": pal["zone"], "line": {"width": 0}},
            name="Too small to detect reliably",
            hovertemplate="detectable from ±%{customdata:.2f}%<extra></extra>",
            customdata=mde,
        )
    )
    fig.add_trace(
        go.Scatter(
            y=labels,
            x=b,
            mode="markers",
            name="Estimate and 90% range",
            marker={
                "color": pal["series"][0],
                "size": 12,
                "line": {"color": pal["ring"], "width": 2},
            },
            error_x={
                "type": "data",
                "symmetric": False,
                "array": [h - v for h, v in zip(hi, b, strict=True)],
                "arrayminus": [v - low for v, low in zip(b, lo, strict=True)],
                "color": pal["series"][0],
                "thickness": 2,
                "width": 6,
            },
            customdata=list(zip(lo, hi, strict=True)),
            hovertemplate="%{x:+.2f}% (90% range %{customdata[0]:+.2f}% to "
            "%{customdata[1]:+.2f}%)<extra>%{y}</extra>",
        )
    )
    fig.add_vline(x=0, line_color=pal["neutral"], line_width=1)
    fig.update_xaxes(
        title_text="Move in daily return per +10 points of Democratic Senate odds (%)",
        ticksuffix="%",
        zeroline=False,
    )
    fig.update_yaxes(autorange="reversed")
    fig = _layout(fig, 130 + 62 * len(rows))
    fig.update_layout(margin={"t": 48, "r": 24, "b": 40, "l": 8})
    return fig


def h1_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    h1 = get(res, "h1") or {}
    return beta_figure([(BASKET_LABELS[k], h1.get(k)) for k in ("ai", "placebo", "diff")], theme)


def h5_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    subs = get(res, "h5", "subs") or {}
    return beta_figure([(SUB_LABELS.get(k, k), subs.get(k)) for k in SUB_LABELS], theme)


# ---------------------------------------------------------------- H2 cross-section


def h2_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    """Per-stock pre-election beta against the event abnormal return: AI | non-AI panels."""
    ai = get(res, "h2", "groups", "ai", "per_stock")
    placebo = get(res, "h2", "groups", "placebo", "per_stock") or []
    if not ai:
        return None
    pal = palette(theme)
    subs = sub_of(res)
    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04, column_widths=[0.62, 0.38],
        subplot_titles=("AI names", "Non-AI names"),
    )  # fmt: skip
    hover = "%{text}: beta %{x:+.2f}%, return %{y:+.1f}%<extra>%{fullData.name}</extra>"
    text_font = {"size": 10, "color": pal["ink"]}
    for i, sub in enumerate(SUB_LABELS):
        pts = [s for s in ai if subs.get(s["ticker"]) == sub]
        fig.add_trace(
            go.Scatter(
                x=[s["b10_pct"] for s in pts],
                y=[s["ar_pct"] for s in pts],
                text=[s["ticker"] for s in pts],
                mode="markers+text",
                textposition="top center",
                textfont=text_font,
                name=SUB_LABELS[sub],
                marker={
                    "color": pal["series"][i],
                    "symbol": SUB_SYMBOLS[sub],
                    "size": 11,
                    "line": {"color": pal["ring"], "width": 1.5},
                },
                hovertemplate=hover,
            ),
            row=1,
            col=1,
        )
    other = [s for s in ai if s["ticker"] not in subs]
    for pts, name, col in ((other, "AI names", 1), (placebo, "Non-AI names", 2)):
        if not pts:
            continue
        fig.add_trace(
            go.Scatter(
                x=[s["b10_pct"] for s in pts],
                y=[s["ar_pct"] for s in pts],
                text=[s["ticker"] for s in pts],
                mode="markers+text",
                textposition="top center",
                textfont=text_font,
                name=name,
                marker={
                    "color": pal["neutral"],
                    "symbol": "circle-open",
                    "size": 10,
                    "line": {"width": 2},
                },
                hovertemplate=hover,
            ),
            row=1,
            col=col,
        )
    for col in (1, 2):
        fig.add_hline(y=0, line_color=pal["muted"], line_width=1, row=1, col=col)
        fig.add_vline(x=0, line_color=pal["muted"], line_width=1, row=1, col=col)
        fig.update_xaxes(
            title_text="Pre-election beta (% per +10 points)", ticksuffix="%", row=1, col=col
        )
    start, end = event_dates(res)
    fig.update_yaxes(
        title_text=f"Return after market and bonds, {day(start, False)} to {day(end, False)} (%)",
        ticksuffix="%",
        row=1,
        col=1,
    )
    fig = _layout(fig, 600)
    fig.update_layout(legend={**LEGEND, "y": 1.08}, margin={**MARGIN, "t": 84})
    return fig


def h2b_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    """One bar per walk-forward day (signed rank score), with the mean as a dashed line."""
    days = get(res, "h2b", "ai", "days")
    mean = get(res, "h2b", "ai", "mean")
    if not days:
        return None
    pal = palette(theme)
    x = [f"{day(d['date'], False)} {str(d['date'])[2:4]}" for d in days]
    y = [d["signed_rho"] for d in days]
    fig = go.Figure(
        go.Bar(
            x=x,
            y=y,
            name="Score on that day",
            marker={
                "color": [pal["series"][0] if v >= 0 else pal["series"][1] for v in y],
                "cornerradius": 2,
            },
            customdata=[100 * d["dp"] for d in days],
            hovertemplate="%{x}: score %{y:+.2f} (odds moved %{customdata:+.1f} pts)"
            "<extra></extra>",
        )
    )
    if mean is not None:
        fig.add_hline(
            y=mean,
            line_dash="dash",
            line_color=pal["ink"],
            line_width=1.5,
            annotation_text=f"Average {mean:+.2f}".replace("-", "−"),
            annotation_position="top right",
            annotation_font={"size": 11, "color": pal["ink"]},
        )
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    fig.update_xaxes(title_text="Large-odds day (in date order)", type="category", nticks=12)
    fig.update_yaxes(
        title_text="Ranking score (−1 wrong way, +1 right way)", range=[-1, 1], zeroline=False
    )
    fig.update_layout(bargap=0.3)
    return _layout(fig, 360, legend=False)


# ---------------------------------------------------------------- H3, H4


def _eastern(ts: pd.Series) -> pd.Series:
    """UTC text -> Eastern wall-clock without an offset (Plotly shows what it is given)."""
    return pd.to_datetime(ts, utc=True).dt.tz_convert(ET).dt.tz_localize(None)


def night_figure(night: pd.DataFrame | None, theme: str | None = None) -> go.Figure | None:
    """Election night: odds on top, futures (% from the window start) below, one ET clock."""
    if not _has(night, "bar_end_ts", "series", "value"):
        return None
    pal = palette(theme)
    df = night.assign(et=_eastern(night["bar_end_ts"]))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07)
    top = [s for s in ("p_sen", "p_house") if s in set(df["series"])]
    bottom = [s for s in ("NQ", "ES", "RTY") if s in set(df["series"])]
    for i, name in enumerate(top):
        g = df[df["series"] == name]
        fig.add_trace(
            go.Scatter(
                x=g["et"], y=100 * g["value"], mode="lines",
                name=f"{SIGNAL_LABELS.get(name, name)} odds",
                line={"color": pal["series"][i], "width": 2.5 if i == 0 else 1.5},
                hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>",
            ),
            row=1, col=1,
        )  # fmt: skip
    for i, name in enumerate(bottom, start=2):
        g = df[df["series"] == name]
        fig.add_trace(
            go.Scatter(
                x=g["et"], y=g["value"], mode="lines", name=INSTRUMENT_LABELS.get(name, name),
                line={"color": pal["series"][i], "width": 2},
                hovertemplate="%{y:+.2f}%<extra>%{fullData.name}</extra>",
            ),
            row=2, col=1,
        )  # fmt: skip
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1, row=2, col=1)
    fig.update_yaxes(title_text="Polymarket odds (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(
        title_text="Futures, change since the start (%)", ticksuffix="%", zeroline=False,
        row=2, col=1,
    )  # fmt: skip
    fig.update_xaxes(title_text="Eastern Time, election night", row=2, col=1)
    fig.update_layout(hovermode="x unified")
    return _layout(fig, 560)


def h3_lag_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    """Per-lag futures move per +10 points of odds, one small panel per index future."""
    instruments = get(res, "h3", "instruments") or {}
    names = [n for n in ("NQ", "ES", "RTY") if get(instruments, n, "rows")]
    if not names:
        return None
    pal = palette(theme)
    fig = make_subplots(
        rows=1, cols=len(names), shared_yaxes=True, horizontal_spacing=0.03,
        subplot_titles=[INSTRUMENT_LABELS.get(n, n) for n in names],
    )  # fmt: skip
    for col, name in enumerate(names, start=1):
        rows = instruments[name]["rows"]
        b = [r["b10_pct"] for r in rows]
        clear = [not (r["ci10_pct"][0] <= 0 <= r["ci10_pct"][1]) for r in rows]
        fig.add_trace(
            go.Bar(
                x=[r["lag"] for r in rows],
                y=b,
                width=0.55,
                name=INSTRUMENT_LABELS.get(name, name),
                marker={
                    "color": [pal["series"][0] if c else pal["muted"] for c in clear],
                    "cornerradius": 3,
                },
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": [r["ci10_pct"][1] - r["b10_pct"] for r in rows],
                    "arrayminus": [r["b10_pct"] - r["ci10_pct"][0] for r in rows],
                    "color": pal["ink"],
                    "thickness": 1,
                    "width": 3,
                },
                hovertemplate="offset %{x:+d} bars: %{y:+.2f}%<extra></extra>",
            ),
            row=1,
            col=col,
        )
        fig.add_hline(y=0, line_color=pal["muted"], line_width=1, row=1, col=col)
        fig.update_xaxes(dtick=1, row=1, col=col)
    fig.update_xaxes(
        title_text="Offset in five-minute bars (positive: odds moved earlier)",
        row=1,
        col=(len(names) + 1) // 2,
    )
    fig.update_yaxes(
        title_text="Move per +10 points of odds (%)", ticksuffix="%", zeroline=False, row=1, col=1
    )
    return _layout(fig, 340, legend=False)


def h4_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    """Hourly lead-lag: link strength (robust t) per lag against the max-|t| noise zone."""
    rows, band = get(res, "h4", "rows"), get(res, "h4", "band_max_abs_t_95")
    if not rows or band is None:
        return None
    pal = palette(theme)
    fig = go.Figure(
        go.Bar(
            x=[r["lag"] for r in rows],
            y=[r["t"] for r in rows],
            width=0.5,
            name="Link strength",
            marker={
                "color": [pal["series"][0] if r["beyond_band"] else pal["muted"] for r in rows],
                "cornerradius": 3,
            },
            customdata=[r["b10_pct"] for r in rows],
            hovertemplate="offset %{x:+d} h: t = %{y:+.2f}, %{customdata:+.2f}% per 10 pts"
            "<extra></extra>",
        )
    )
    fig.add_hrect(y0=-band, y1=band, fillcolor=pal["zone"], line_width=0, layer="below")
    fig.add_annotation(
        x=1, xref="x domain", y=band, text="Noise zone", showarrow=False, xanchor="right",
        yanchor="bottom", font={"size": 11, "color": pal["ink"]},
    )  # fmt: skip
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    reach = max(band, *(abs(r["t"]) for r in rows)) * 1.25
    fig.update_xaxes(title_text="Time gap in hours (positive: odds moved earlier)", dtick=1)
    fig.update_yaxes(title_text="Link strength (robust t)", range=[-reach, reach], zeroline=False)
    return _layout(fig, 340, legend=False)


# ---------------------------------------------------------------- exploratory


E2_PANELS = (
    ("vix9d_over_vix", "Nine-day ÷ one-month"),
    ("vix_over_vix3m", "One-month ÷ three-month"),
    ("vxn_minus_vix", "Nasdaq − S&P (vol pts)"),
)
_DASHES = ("dot", "dash", "dashdot", "longdash")


def e2_term_figure(vol: pd.DataFrame | None, theme: str | None = None) -> go.Figure | None:
    """Three stacked panels on one event-time axis; the latest election in colour."""
    if not _has(vol, "rel_day", "election", *(c for c, _ in E2_PANELS)):
        return None
    pal = palette(theme)
    elections = sorted(vol["election"].unique())
    fig = make_subplots(rows=len(E2_PANELS), cols=1, shared_xaxes=True, vertical_spacing=0.05)
    for row, (col, title) in enumerate(E2_PANELS, start=1):
        for i, election in enumerate(elections):
            g = vol[vol["election"] == election].sort_values("rel_day")
            latest = election == elections[-1]
            fig.add_trace(
                go.Scatter(
                    x=g["rel_day"],
                    y=g[col],
                    mode="lines",
                    name=str(election)[:4],
                    legendgroup=str(election),
                    showlegend=row == 1,
                    line={"color": pal["series"][0], "width": 3}
                    if latest
                    else {"color": pal["neutral"], "width": 1.5, "dash": _DASHES[i % 4]},
                    hovertemplate="%{y:.2f}<extra>" + str(election)[:4] + "</extra>",
                ),
                row=row,
                col=1,
            )
        if "over" in col:
            fig.add_hline(y=1, line_color=pal["muted"], line_width=1, row=row, col=1)
        fig.add_vline(x=0, line_color=pal["muted"], line_width=1, row=row, col=1)
        fig.update_yaxes(title_text=title, zeroline=False, row=row, col=1)
    fig.update_xaxes(
        title_text="Trading sessions from election day (0 = election day)",
        row=len(E2_PANELS),
        col=1,
    )
    fig.update_layout(hovermode="x unified")
    return _layout(fig, 640)


def e2_moves_figure(res: Results, theme: str | None = None) -> go.Figure | None:
    """Per election: a grey bar of +/- the implied one-day move and a dot at the realised move."""
    moves = get(res, "exploratory", "e2", "moves")
    if not moves:
        return None
    pal = palette(theme)
    keys = sorted(moves)
    years = [k[:4] for k in keys]
    implied = [moves[k]["implied_1d_pct"] for k in keys]
    realised = [moves[k]["realised_next_day_pct"] for k in keys]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=[2 * v for v in implied],
            base=[-v for v in implied],
            width=0.35,
            name="Move options implied (±)",
            marker={"color": pal["zone"], "line": {"width": 0}},
            customdata=implied,
            hovertemplate="implied ±%{customdata:.2f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=realised,
            mode="markers+text",
            text=[f"{v:+.1f}%".replace("-", "−") for v in realised],
            textposition="middle right",
            textfont={"size": 11, "color": pal["ink"]},
            name="What the index did next day",
            marker={
                "color": pal["series"][0],
                "size": 13,
                "line": {"color": pal["ring"], "width": 2},
            },
            hovertemplate="realised %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    fig.update_xaxes(title_text="Election year", type="category")
    fig.update_yaxes(title_text="Nasdaq-100 one-day move (%)", ticksuffix="%", zeroline=False)
    return _layout(fig, 360)


def e1_figure(rolling: pd.DataFrame | None, theme: str | None = None) -> go.Figure | None:
    """Rolling estimate with its 90% range as a wash."""
    if not _has(rolling, "date", "b10_pct", "lo", "hi"):
        return None
    pal = palette(theme)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=rolling["date"], y=rolling["hi"], line={"width": 0}, showlegend=False,
                   hoverinfo="skip")
    )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=rolling["date"], y=rolling["lo"], fill="tonexty", line={"width": 0},
            fillcolor=pal["zone"], name="90% range", hoverinfo="skip",
        )
    )  # fmt: skip
    fig.add_trace(
        go.Scatter(
            x=rolling["date"], y=rolling["b10_pct"], name="Rolling estimate", mode="lines",
            line={"color": pal["series"][0], "width": 2},
            hovertemplate="%{y:+.2f}%<extra></extra>",
        )
    )  # fmt: skip
    fig.add_hline(y=0, line_color=pal["neutral"], line_width=1)
    fig.update_xaxes(title_text="Last session of the window")
    fig.update_yaxes(title_text="Move per +10 points of odds (%)", ticksuffix="%", zeroline=False)
    return _layout(fig, 340)


def e3_figure(scatter: pd.DataFrame | None, theme: str | None = None) -> go.Figure | None:
    if not _has(scatter, "mean_dp", "excess_ret"):
        return None
    pal = palette(theme)
    fig = go.Figure(
        go.Scatter(
            x=100 * scatter["mean_dp"],
            y=100 * scatter["excess_ret"],
            mode="markers",
            text=scatter["session"] if "session" in scatter.columns else None,
            marker={
                "color": pal["series"][0],
                "size": 10,
                "line": {"color": pal["ring"], "width": 2},
            },
            hovertemplate="%{text}: odds %{x:+.1f} pts, stocks %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    fig.add_vline(x=0, line_color=pal["muted"], line_width=1)
    fig.update_xaxes(title_text="Average change in moratorium odds that day (points)")
    fig.update_yaxes(title_text="Power and data-centre basket minus utilities (%)", ticksuffix="%")
    return _layout(fig, 360, legend=False)


def e5_figure(car: pd.DataFrame | None, theme: str | None = None) -> go.Figure | None:
    if not _has(car, "session", "top", "bottom", "top_minus_bottom"):
        return None
    pal = palette(theme)
    fig = go.Figure()
    for col, name, line in (
        ("top", "Highest-beta third", {"color": pal["series"][0], "width": 2}),
        ("bottom", "Lowest-beta third", {"color": pal["series"][1], "width": 2}),
        ("top_minus_bottom", "Difference", {"color": pal["neutral"], "width": 2, "dash": "dash"}),
    ):
        fig.add_trace(
            go.Scatter(
                x=[day(s, False) for s in car["session"]],
                y=100 * car[col],
                name=name,
                mode="lines+markers",
                line=line,
                marker={"size": 8},
                hovertemplate="%{y:+.2f}%<extra>%{fullData.name}</extra>",
            )
        )
    fig.add_hline(y=0, line_color=pal["muted"], line_width=1)
    fig.update_xaxes(title_text="Session after the election", type="category")
    fig.update_yaxes(
        title_text="Cumulative return after market and bonds (%)", ticksuffix="%", zeroline=False
    )
    fig.update_layout(hovermode="x unified")
    return _layout(fig, 360)

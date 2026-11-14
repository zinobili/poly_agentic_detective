"""Plotly figure builders. Pure: panel/results in, figure out. No Streamlit, no I/O.

Time axes are UTC and say so. Chart 3 is two stacked panels on one shared x axis; it never
uses a secondary y axis.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .contract import GAP_STEP, EventStudy, XCorr
from .text import ticker_label
from .wording import ROUND_THE_CLOCK, SIGNAL_LABELS

MAX_GAP = pd.Timedelta(hours=6)
POLY_COLOR = "#2563eb"
STOCK_COLOR = "#b45309"
GREY = "#c7ccd4"
TIME_TITLE = "Time (UTC)"

# Panel signal level -> the unit a reader understands (pair id -> function).
_SIGNAL_SCALE: dict[str, Callable[[pd.Series], pd.Series]] = {
    "fed_decision": lambda s: s / 100.0,  # bp -> percentage points
    "us_recession": lambda s: s * 100.0,  # probability -> percent
    "bitcoin_monthly_ladder": lambda s: np.exp(s) / 1000.0,  # log price -> $k
    "us_cpi_inflation": lambda s: s,  # already year-on-year percent
}


def break_gaps(x: pd.Series, y: pd.Series, max_gap: pd.Timedelta = MAX_GAP) -> pd.DataFrame:
    """Drop NaN y, then insert a NaN row in every hole wider than ``max_gap``.

    Plotly leaves a break at a NaN, so no line is drawn across weekends or outages.
    """
    pts = pd.DataFrame({"x": x.to_numpy(), "y": y.to_numpy()}).dropna().sort_values("x")
    gap = pts["x"].diff() > max_gap
    breaks = pd.DataFrame({"x": pts["x"].shift()[gap] + pd.Timedelta(seconds=1), "y": np.nan})
    return pd.concat([pts, breaks]).sort_values("x", kind="stable").reset_index(drop=True)


def _naive_utc(s: pd.Series) -> pd.Series:
    """Plotly shows what it is given, so hand it UTC wall-clock without an offset."""
    return s.dt.tz_convert("UTC").dt.tz_localize(None)


def signal_series(panel: pd.DataFrame, pair_id: str) -> pd.DataFrame:
    """(x, y) of the Polymarket signal in reader units, indexed by the bar end."""
    scale = _SIGNAL_SCALE.get(pair_id, lambda s: s)
    return pd.DataFrame({"x": panel["ts_end"], "y": scale(panel["signal_level"])})


def stock_index_series(panel: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Stock price index (100 at the first bar) built from the panel's log returns.

    Each session bar's return is added at the bar end; the overnight gap is added on the
    opening bar so the level stays continuous across nights. A round-the-clock asset (BTC-USD)
    uses every row, so its line does not break overnight.
    """
    ret = panel[f"ret_{ticker}"]
    if ticker in ROUND_THE_CLOCK:
        rows = ret.notna()
        level = 100.0 * np.exp(ret[rows].cumsum())
        return pd.DataFrame({"x": panel.loc[rows, "ts_end"], "y": level})
    gap_col = f"overnight_gap_{ticker}"
    gap = (
        panel[gap_col].fillna(0.0) if gap_col in panel.columns else pd.Series(0.0, index=ret.index)
    )
    bars = panel["is_session_bar"] & ret.notna()
    level = 100.0 * np.exp((ret[bars] + gap[bars]).cumsum())
    return pd.DataFrame({"x": panel.loc[bars, "ts_end"], "y": level})


def raw_data_figure(panel: pd.DataFrame, pair_id: str, ticker: str) -> go.Figure:
    """Chart 3: Polymarket signal on top, stock price index below, one shared timeline."""
    sig = break_gaps(*_xy(signal_series(panel, pair_id)))
    stock = break_gaps(*_xy(stock_index_series(panel, ticker)))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    signal_name = SIGNAL_LABELS.get(pair_id, "Polymarket signal")
    for row, df, name, color in (
        (1, sig, signal_name, POLY_COLOR),
        (2, stock, f"{ticker_label(ticker)} price index", STOCK_COLOR),
    ):
        fig.add_trace(
            go.Scatter(
                x=_naive_utc(df["x"]),
                y=df["y"],
                name=name,
                mode="lines",
                line={"color": color, "width": 1.5},
                connectgaps=False,
            ),
            row=row,
            col=1,
        )
    fig.update_yaxes(title_text=signal_name, row=1, col=1)
    fig.update_yaxes(title_text="Price index (start = 100)", row=2, col=1)
    fig.update_xaxes(title_text=TIME_TITLE, row=2, col=1)
    fig.update_layout(height=520, margin={"t": 20, "r": 20}, legend={"orientation": "h"})
    return fig


def _xy(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return df["x"], df["y"]


def xcorr_figure(xc: XCorr) -> go.Figure:
    """Chart 1: one bar per lag (r); bars inside the simultaneous noise zone are grey.

    With a robust-t band (A28 item 1) the zone is in t units, so each lag gets its own limit
    in r units, r * band / |t|, drawn as a tick; otherwise one shaded zone of +/- band."""
    colors = [POLY_COLOR if abs(v) > xc.band else GREY for v in xc.stat]
    fig = go.Figure(
        go.Bar(x=list(xc.lags), y=list(xc.r), marker_color=colors, name="Link strength")
    )
    if xc.t is None:
        fig.add_hrect(y0=-xc.band, y1=xc.band, fillcolor=GREY, opacity=0.25, line_width=0)
    else:
        limit = [abs(r) * xc.band / abs(t) if t else None for r, t in zip(xc.r, xc.t, strict=True)]
        for sign in (1, -1):
            fig.add_trace(
                go.Scatter(
                    x=list(xc.lags),
                    y=[None if v is None else sign * v for v in limit],
                    mode="markers",
                    marker={"symbol": "line-ew-open", "size": 18, "color": GREY},
                    name="Noise limit",
                    hoverinfo="skip",
                )
            )
    fig.update_xaxes(title_text="Time gap in hours (positive: odds moved first)", dtick=1)
    fig.update_yaxes(title_text="Link strength (-1 to 1)")
    fig.update_layout(height=340, margin={"t": 20, "r": 20}, showlegend=False)
    return fig


PATH_COLOR = "rgba(100,116,139,0.25)"
COMPARE_COLOR = "#b45309"


def event_study_figure(es: EventStudy) -> go.Figure:
    """Chart 2: mean move per event-time step with its interval, the individual events, the
    ordinary-day band and marked opening-gap steps. Steps are categories, so a 'gap' step sits
    between two bars."""
    x = list(es.steps)
    fig = go.Figure()
    if es.band_low is not None:
        fig.add_trace(go.Scatter(x=x, y=list(es.band_high), line={"width": 0}, showlegend=False))
        fig.add_trace(
            go.Scatter(
                x=x,
                y=list(es.band_low),
                fill="tonexty",
                fillcolor="rgba(156,163,175,0.25)",
                line={"width": 0},
                name="Ordinary days",
            )
        )
    for i, path in enumerate(es.paths):
        marks = es.gap_marks[i] if i < len(es.gap_marks) else ()
        fig.add_trace(
            go.Scatter(
                x=x,
                y=list(path),
                mode="lines+markers" if marks else "lines",
                line={"color": PATH_COLOR, "width": 1},
                marker={
                    "size": [8 if j in marks else 0 for j in range(len(x))],
                    "symbol": "diamond",
                    "color": PATH_COLOR,
                },
                showlegend=i == 0,
                name="Each event",
            )
        )
    fig.add_trace(go.Scatter(x=x, y=list(es.ci_high), line={"width": 0}, showlegend=False))
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(es.ci_low),
            fill="tonexty",
            fillcolor="rgba(37,99,235,0.18)",
            line={"width": 0},
            name="Plausible range",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=list(es.mean), name=es.label or "Average move", line={"color": POLY_COLOR}
        )
    )
    if es.compare is not None:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=list(es.compare.mean),
                name=es.compare.label,
                line={"color": COMPARE_COLOR, "dash": "dash"},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": [
                        h - m for h, m in zip(es.compare.ci_high, es.compare.mean, strict=True)
                    ],
                    "arrayminus": [
                        m - lo for m, lo in zip(es.compare.mean, es.compare.ci_low, strict=True)
                    ],
                },
            )
        )
    if GAP_STEP in x:
        fig.add_vline(x=x.index(GAP_STEP), line_dash="dot", line_color=GREY)
    fig.add_hline(y=0, line_color=GREY)
    unit = "Days after the big move" if es.unit == "days" else "Hours from the event (session bars)"
    fig.update_xaxes(title_text=unit, type="category")
    fig.update_yaxes(title_text=f"{es.ticker} move (%)")
    fig.update_layout(height=360, margin={"t": 20, "r": 20}, legend={"orientation": "h"})
    return fig

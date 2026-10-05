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

from .contract import EventStudy, XCorr
from .text import SIGNAL_LABELS, ticker_label

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
    opening bar so the level stays continuous across nights.
    """
    ret = panel[f"ret_{ticker}"]
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
    """Chart 1: one bar per lag; bars inside the noise zone are grey."""
    colors = [POLY_COLOR if abs(r) > xc.band else GREY for r in xc.r]
    fig = go.Figure(
        go.Bar(x=list(xc.lags), y=list(xc.r), marker_color=colors, name="Link strength")
    )
    fig.add_hrect(y0=-xc.band, y1=xc.band, fillcolor=GREY, opacity=0.25, line_width=0)
    fig.update_xaxes(title_text="Time gap in hours (positive: odds moved first)", dtick=2)
    fig.update_yaxes(title_text="Link strength (-1 to 1)")
    fig.update_layout(height=340, margin={"t": 20, "r": 20}, showlegend=False)
    return fig


def event_study_figure(es: EventStudy) -> go.Figure:
    """Chart 2: mean stock move around each odds jump, with the shaded 95% range."""
    hours = list(es.hours)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=list(es.ci_high), line={"width": 0}, showlegend=False))
    fig.add_trace(
        go.Scatter(
            x=hours,
            y=list(es.ci_low),
            fill="tonexty",
            fillcolor="rgba(37,99,235,0.18)",
            line={"width": 0},
            name="Plausible range",
        )
    )
    fig.add_trace(
        go.Scatter(x=hours, y=list(es.mean), name="Average move", line={"color": POLY_COLOR})
    )
    fig.add_hline(y=0, line_color=GREY)
    fig.update_xaxes(title_text="Hours after the odds jump")
    fig.update_yaxes(title_text=f"{es.ticker} move (%)")
    fig.update_layout(height=340, margin={"t": 20, "r": 20}, legend={"orientation": "h"})
    return fig

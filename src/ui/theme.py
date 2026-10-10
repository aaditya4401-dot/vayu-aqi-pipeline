"""Visual system for the dashboard: flat dark surfaces, square corners, skeleton loaders.

Follows the banned-pattern list in CLAUDE.md: no gradients, shadows, rounded corners,
colored side stripes, emojis, hover animations, or rainbow palettes.
"""

import html
from collections.abc import Callable
from typing import TypeVar

import plotly.graph_objects as go
import streamlit as st

T = TypeVar("T")

BG = "#14191c"
SURFACE = "#1c2226"
BORDER = "#2c353b"
TEXT = "#dde2df"
MUTED = "#8b9696"
ACCENT = "#7fb0b3"

# Restrained earth-tone series colours (not a rainbow), reused across charts.
SERIES = ["#7fb0b3", "#c79a3a", "#9aa5a0", "#b5654a", "#7f9f6b", "#a08c6e", "#7d8ea8"]
SEVERITY_COLORS = {"low": "#7f9f6b", "medium": "#c79a3a", "high": "#c9743a", "critical": "#c4585f"}
GRADE_COLORS = {"A": "#2f6b4a", "B": "#5b7428", "C": "#8a6a14", "D": "#a4551f", "F": "#9a3a33"}

CSS = f"""
<style>
    .block-container {{ padding-top: 1.5rem; max-width: 1400px; }}
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}

    /* No motion on interaction */
    *, *::before, *::after {{ transition: none !important; }}

    .vy-section {{
        color: {MUTED}; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.12em;
        border-bottom: 1px solid {BORDER}; padding-bottom: 6px; margin: 18px 0 12px 0;
    }}
    .vy-aqi-card {{
        padding: 16px 12px; text-align: center; color: #f2f2ee; border-radius: 2px;
        margin-bottom: 8px;
    }}
    .vy-aqi-card .value {{ font-size: 2.3rem; font-weight: 700; line-height: 1.1; }}
    .vy-aqi-card .name {{ font-size: 0.95rem; margin-top: 4px; }}
    .vy-aqi-card .meta {{ font-size: 0.78rem; opacity: 0.85; margin-top: 2px; }}

    .vy-strip {{ display: flex; border: 1px solid {BORDER}; background: {SURFACE}; border-radius: 2px; }}
    .vy-strip .cell {{ flex: 1; padding: 14px 16px; border-right: 1px solid {BORDER}; min-width: 0; }}
    .vy-strip .cell:last-child {{ border-right: none; }}
    .vy-strip .value {{ font-size: 1.7rem; font-weight: 700; color: {TEXT}; overflow-wrap: anywhere; }}
    .vy-strip .label {{ font-size: 0.8rem; color: {MUTED}; margin-top: 2px; }}

    .vy-note {{
        border: 1px solid {BORDER}; background: {SURFACE}; border-radius: 2px;
        padding: 12px 16px; margin: 8px 0; color: {TEXT}; font-size: 0.92rem;
    }}
    .vy-note .head {{ font-weight: 700; }}
    .vy-note .body {{ color: {MUTED}; margin-top: 2px; }}

    .vy-advisory {{
        border: 1px solid {BORDER}; background: {SURFACE}; border-radius: 2px;
        padding: 20px; white-space: pre-wrap; line-height: 1.6; font-size: 0.92rem; color: {TEXT};
    }}

    .vy-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    .vy-table th {{
        text-align: left; color: {MUTED}; font-weight: 600; font-size: 0.78rem;
        text-transform: uppercase; letter-spacing: 0.08em; padding: 8px 10px;
        border-bottom: 1px solid {BORDER};
    }}
    .vy-table td {{ padding: 10px; border-bottom: 1px solid {BORDER}; color: {TEXT}; }}
    .vy-chip {{ display: inline-block; padding: 2px 10px; border-radius: 2px; color: #f2f2ee; font-weight: 700; }}
    .vy-bar {{ background: {BORDER}; height: 8px; width: 100%; border-radius: 0; }}
    .vy-bar > div {{ background: {ACCENT}; height: 8px; border-radius: 0; }}

    .vy-skel {{ background: {BORDER}; border-radius: 2px; animation: vy-pulse 1.4s steps(6, end) infinite; }}
    @keyframes vy-pulse {{ 0% {{ opacity: 0.45; }} 50% {{ opacity: 0.9; }} 100% {{ opacity: 0.45; }} }}
</style>
"""


def apply_theme() -> None:
    """Inject the dashboard stylesheet. Call once per run, before rendering."""
    st.markdown(CSS, unsafe_allow_html=True)


def section(title: str) -> None:
    """Render an uppercase section heading with a hairline rule."""
    st.markdown(f'<div class="vy-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def aqi_card_html(value: int, name: str, meta: str, fill: str) -> str:
    """Return HTML for one AQI card (flat fill, square-ish corners, no shadow)."""
    return (
        f'<div class="vy-aqi-card" style="background:{fill};">'
        f'<div class="value">{value}</div>'
        f'<div class="name">{html.escape(name)}</div>'
        f'<div class="meta">{html.escape(meta).replace(chr(10), "<br>")}</div>'
        f"</div>"
    )


def stat_strip(items: list[tuple[str, str, str | None]]) -> None:
    """Render one bordered strip of divided stat cells.

    Args:
        items: (value, label, optional value colour) per cell. Use four cells, not three.
    """
    cells = ""
    for value, label, color in items:
        style = f' style="color:{color}"' if color else ""
        cells += (
            f'<div class="cell"><div class="value"{style}>{html.escape(value)}</div>'
            f'<div class="label">{html.escape(label)}</div></div>'
        )
    st.markdown(f'<div class="vy-strip">{cells}</div>', unsafe_allow_html=True)


def note(head: str, body: str = "") -> None:
    """Render a bordered note box (full 1px border, no colored side stripe)."""
    body_html = f'<div class="body">{html.escape(body)}</div>' if body else ""
    st.markdown(
        f'<div class="vy-note"><div class="head">{html.escape(head)}</div>{body_html}</div>',
        unsafe_allow_html=True,
    )


def style_fig(fig: go.Figure, height: int = 420, **layout: object) -> go.Figure:
    """Apply the dashboard look to a Plotly figure (flat, dark, no shadows)."""
    options: dict[str, object] = dict(
        template="plotly_dark",
        paper_bgcolor=BG,
        plot_bgcolor=SURFACE,
        font=dict(color=TEXT),
        height=height,
        margin=dict(l=40, r=20, t=30, b=40),
        legend=dict(orientation="h", y=-0.2),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER, font_color=TEXT),
    )
    options.update(layout)  # caller overrides win
    fig.update_layout(**options)
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    return fig


def skeleton_html(kind: str) -> str:
    """Return skeleton-loader HTML: 'cards', 'chart', 'table', or 'strip'."""
    if kind == "cards":
        block = '<div class="vy-skel" style="height:104px;flex:1;"></div>'
        return f'<div style="display:flex;gap:8px;">{block * 7}</div>'
    if kind == "strip":
        return '<div class="vy-skel" style="height:72px;width:100%;"></div>'
    if kind == "table":
        rows = '<div class="vy-skel" style="height:22px;margin-bottom:10px;"></div>' * 6
        return f"<div>{rows}</div>"
    return '<div class="vy-skel" style="height:380px;width:100%;"></div>'


def load_with_skeleton(loader: Callable[..., T], *args: object, kind: str = "chart") -> T:
    """Show a skeleton loader while ``loader(*args)`` runs, then remove it.

    Args:
        loader: Data-loading function (usually cached).
        *args: Arguments passed to the loader.
        kind: Skeleton shape: 'cards', 'chart', 'table', or 'strip'.

    Returns:
        Whatever the loader returns. Exceptions propagate after the skeleton is cleared.
    """
    placeholder = st.empty()
    placeholder.markdown(skeleton_html(kind), unsafe_allow_html=True)
    try:
        return loader(*args)
    finally:
        placeholder.empty()

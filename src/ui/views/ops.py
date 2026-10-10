"""Operations tabs: Advisory, Data Quality, Pipeline."""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ingestion.validators import DELHI_LOCATIONS
from src.ui import data
from src.ui.helpers import aqi_category, aqi_text_color, format_ist, plain_copy, utc_now
from src.ui.theme import (
    ACCENT, GRADE_COLORS, load_with_skeleton, note, section, stat_strip, style_fig,
)

STATE_COLORS = {"Fresh": "#2f6b4a", "Recent": "#5b7428", "Stale": "#a4551f", "Empty": "#4a545a"}


def _chip(text: str, color: str) -> str:
    """Return a flat, square-cornered label chip."""
    return f'<span class="vy-chip" style="background:{color}">{html.escape(text)}</span>'


def _bar(percent: float) -> str:
    """Return a flat horizontal progress bar for a 0 to 100 value."""
    width = max(0.0, min(100.0, percent))
    return f'<div class="vy-bar"><div style="width:{width:.0f}%"></div></div>'


def _table(headers: list[str], rows: list[list[str]]) -> None:
    """Render an HTML table. Cell values must already be escaped or safe HTML."""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    st.markdown(f'<table class="vy-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)


def _ago(then: object) -> str:
    """Describe how long ago a UTC timestamp was, e.g. '12 min ago'."""
    seconds = (utc_now() - pd.Timestamp(then).to_pydatetime().replace(tzinfo=None)).total_seconds()
    if seconds < 3600:
        return f"{max(seconds, 0) / 60:.0f} min ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h ago"
    return f"{seconds / 86400:.1f} days ago"


def render_advisory() -> None:
    """Latest AI health advisory with the headline numbers it was written from."""
    section("AI health advisory")
    adv = load_with_skeleton(data.load_advisories, kind="table")
    if adv.empty:
        note("No advisories yet", "Run the pipeline with a valid OPENAI_API_KEY to generate one.")
        return

    latest = adv.iloc[0]
    st.caption(f"Advisory #{latest['id']}, generated {format_ist(latest['generated_at'])}, model {latest['model_used']}")

    if pd.notna(latest["avg_aqi"]):
        avg = int(latest["avg_aqi"])
        worst_id = latest["worst_location"]
        worst_name = DELHI_LOCATIONS.get(worst_id, {}).get("name", worst_id) if worst_id else "n/a"
        worst_aqi = int(latest["worst_aqi"]) if pd.notna(latest["worst_aqi"]) else None
        stat_strip([
            (str(avg), "Average AQI", aqi_text_color(avg)),
            (aqi_category(avg), "Category", aqi_text_color(avg)),
            (str(worst_name), "Worst location", None),
            (str(worst_aqi) if worst_aqi is not None else "n/a", "Worst AQI", aqi_text_color(worst_aqi) if worst_aqi is not None else None),
        ])

    st.markdown(
        f'<div class="vy-advisory">{html.escape(plain_copy(latest["advisory_text"]))}</div>',
        unsafe_allow_html=True,
    )
    note("Information only", "Written by an AI model from sensor data. It is not medical advice and can be wrong.")

    if len(adv) > 1:
        with st.expander(f"Previous advisories ({len(adv) - 1})"):
            for _, row in adv.iloc[1:].iterrows():
                avg = "n/a" if pd.isna(row["avg_aqi"]) else int(row["avg_aqi"])
                st.markdown(f"**#{row['id']}**, {format_ist(row['generated_at'])}, average AQI {avg}")


def render_data_quality() -> None:
    """Completeness, freshness, consistency, and grade for each data source."""
    section("Data quality scores")
    dq = load_with_skeleton(data.load_data_quality, kind="table")
    if dq.empty:
        note("No data quality scores yet")
        return

    rows = []
    for _, r in dq.iterrows():
        grade = str(r["overall_grade"])
        fresh = "n/a" if pd.isna(r["freshness_seconds"]) else f"{r['freshness_seconds'] / 60:.0f} min"
        cons = "n/a" if pd.isna(r["consistency"]) else f"{r['consistency']:.0f}%"
        rows.append([
            html.escape(str(r["source"]).replace("_", " ").title()),
            _chip(grade, GRADE_COLORS.get(grade.upper(), "#4a545a")),
            f"{_bar(r['completeness'])}<div>{r['completeness']:.0f}%</div>",
            html.escape(fresh),
            html.escape(cons),
            html.escape(format_ist(r["scored_at"])),
        ])
    _table(["Source", "Grade", "Completeness", "Freshness", "Consistency", "Scored"], rows)
    st.caption("Consistency compares OpenWeatherMap PM2.5 against ground-station PM2.5 for the same hour.")


def render_pipeline() -> None:
    """Row counts, last-write times, and how to run each part of the system."""
    section("Pipeline health")
    status = load_with_skeleton(data.load_table_status, kind="table")

    last = status["last_update"].dropna()
    stat_strip([
        (data.backend_label(), "Database backend", None),
        (f"{int(status['rows'].sum()):,}", "Total rows", None),
        (f"{len(status)}", "Tables", None),
        (_ago(last.max()) if not last.empty else "never", "Most recent write", None),
    ])

    ordered = status.sort_values("rows")
    fig = go.Figure(go.Bar(x=ordered["rows"], y=ordered["table"], orientation="h", marker_color=ACCENT))
    style_fig(fig, height=330, xaxis_title="Rows", showlegend=False, margin=dict(l=150, r=20, t=20, b=40))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    rows = []
    for _, r in status.iterrows():
        if pd.isna(r["last_update"]):
            state, when = "Empty", "never"
        else:
            age = (utc_now() - pd.Timestamp(r["last_update"]).to_pydatetime().replace(tzinfo=None)).total_seconds()
            state = "Fresh" if age < 300 else ("Recent" if age < 3600 else "Stale")
            when = f"{format_ist(r['last_update'])} ({_ago(r['last_update'])})"
        rows.append([html.escape(r["table"]), f"{int(r['rows']):,}", html.escape(when), _chip(state, STATE_COLORS[state])])
    _table(["Table", "Rows", "Last update", "State"], rows)

    section("Commands")
    st.markdown(
        "| Task | Command |\n|---|---|\n"
        "| Run the pipeline | `python -m src.orchestration.flows` |\n"
        "| Daily run with causality | `python -m src.orchestration.flows --causality` |\n"
        "| Start this dashboard | `python -m streamlit run src/ui/app.py` |\n"
        "| Prefect UI (opens at localhost:4200) | `prefect server start` |"
    )

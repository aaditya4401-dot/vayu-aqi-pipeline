"""Live air quality tabs: Overview, AQI Trends, Pollutants."""

import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.ui import data
from src.ui.helpers import (
    AQI_BANDS, AQI_FILL, aqi_category, aqi_fill, aqi_text_color, format_ist,
    is_northwest_wind, season_context, to_ist, today_ist,
)
from src.ui.theme import (
    SERIES, aqi_card_html, load_with_skeleton, note, section, stat_strip, style_fig,
)

# NAAQS reference limits in μg/m³ (CO uses the 1-hour limit).
NAAQS: dict[str, float] = {"pm25": 60, "pm10": 100, "no2": 80, "so2": 80, "o3": 100, "co": 4000}
POLLUTANT_LABELS: dict[str, str] = {
    "pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "o3": "O3", "co": "CO",
}


def _rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' to an rgba() string."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def render_overview() -> None:
    """Current AQI per station, season context, wind alert, and ground-station readings."""
    latest = load_with_skeleton(data.load_latest_aqi, kind="cards")
    if latest.empty:
        note("No current AQI data", "Run the pipeline first: python -m src.orchestration.flows")
        return

    headline, detail = season_context(today_ist())
    note(headline, detail)

    weather = data.load_latest_weather()
    if not weather.empty:
        nw = int(weather["wind_direction_deg"].map(is_northwest_wind).sum())
        note(
            f"North-west wind at {nw} of {len(weather)} stations",
            "Wind from 270 to 360 degrees carries Punjab crop smoke towards Delhi.",
        )

    section("Current AQI across Delhi NCR")
    latest = latest.sort_values("name").reset_index(drop=True)
    cols = st.columns(len(latest))
    for col, (_, row) in zip(cols, latest.iterrows()):
        aqi = int(row["aqi"])
        with col:
            st.markdown(
                aqi_card_html(aqi, row["name"], f"{aqi_category(aqi)}\nPM2.5 {row['pm25']:.0f} μg/m³", aqi_fill(aqi)),
                unsafe_allow_html=True,
            )
    st.caption(f"Latest reading: {format_ist(latest['timestamp'].max())}")

    section("Key metrics")
    avg = int(round(latest["aqi"].mean()))
    worst = latest.loc[latest["aqi"].idxmax()]
    best = latest.loc[latest["aqi"].idxmin()]
    ratios = {p: (latest[p] / NAAQS[p]).mean() for p in ("pm25", "pm10", "no2", "o3")}
    dominant = POLLUTANT_LABELS[max(ratios, key=ratios.get)]
    stat_strip([
        (str(avg), f"NCR average AQI, {aqi_category(avg)}", aqi_text_color(avg)),
        (str(int(worst["aqi"])), f"Worst: {worst['name']}", aqi_text_color(worst["aqi"])),
        (str(int(best["aqi"])), f"Best: {best['name']}", aqi_text_color(best["aqi"])),
        (dominant, "Dominant pollutant vs NAAQS", None),
    ])

    stations = data.load_latest_station_measurements()
    if not stations.empty:
        section("Ground stations (simulated CPCB-style)")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=stations["name"], y=stations["pm25"], name="PM2.5", marker_color=SERIES[0]))
        fig.add_trace(go.Bar(x=stations["name"], y=stations["pm10"], name="PM10", marker_color=SERIES[1]))
        style_fig(fig, height=340, barmode="group", yaxis_title="μg/m³")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_trends() -> None:
    """Hourly AQI lines per station with Indian AQI category bands."""
    section("AQI trends over time")
    days = st.radio("Window", [3, 7, 14, 30], index=2, horizontal=True, format_func=lambda d: f"Last {d} days")
    df = load_with_skeleton(data.load_aqi_history, days, kind="chart")
    if df.empty:
        note("No trend data in this window", "Try a longer window or run the pipeline backfill.")
        return

    names = sorted(df["station"].unique())
    chosen = st.multiselect("Stations", names, default=names)
    df = df[df["station"].isin(chosen)]
    if df.empty:
        note("Select at least one station")
        return
    df = df.assign(time_ist=to_ist(df["timestamp"]))

    fig = px.line(
        df, x="time_ist", y="aqi", color="station",
        color_discrete_sequence=SERIES, labels={"aqi": "AQI", "time_ist": "Time (IST)"},
    )
    top = max(100, int(df["aqi"].max() * 1.1))
    for band, y0, y1 in AQI_BANDS:
        if y0 >= top:
            break
        fig.add_hrect(
            y0=y0, y1=min(y1, top), fillcolor=_rgba(AQI_FILL[band], 0.18), line_width=0,
            annotation_text=band, annotation_position="top left",
            annotation_font_size=10, annotation_font_color="#8b9696",
        )
    style_fig(fig, height=480, yaxis_range=[0, top])
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_pollutants() -> None:
    """Latest pollutant levels per station as a share of NAAQS limits."""
    section("Pollutant breakdown by station")
    latest = load_with_skeleton(data.load_latest_aqi, kind="chart")
    if latest.empty:
        note("No pollutant data available")
        return

    latest = latest.sort_values("name")
    fig = go.Figure()
    for color, (key, label) in zip(SERIES, POLLUTANT_LABELS.items()):
        fig.add_trace(go.Bar(x=latest["name"], y=latest[key] / NAAQS[key] * 100, name=label, marker_color=color))
    fig.add_hline(y=100, line_dash="dash", line_color="#c4585f", annotation_text="NAAQS limit (100%)")
    style_fig(fig, height=440, barmode="group", yaxis_title="% of NAAQS limit")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    limits = ", ".join(f"{POLLUTANT_LABELS[k]} {v:,.0f}" for k, v in NAAQS.items())
    st.caption(f"Reference limits (μg/m³): {html.escape(limits)}. CO uses the 1-hour limit.")

    with st.expander("Raw concentrations (μg/m³)"):
        raw = latest[["name", *POLLUTANT_LABELS]].rename(columns={"name": "Station", **POLLUTANT_LABELS})
        st.dataframe(raw.set_index("Station").round(1), width="stretch")

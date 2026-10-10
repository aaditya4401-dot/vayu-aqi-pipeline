"""Analytics tabs: Anomalies, Forecast, Causality, Features."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.ui import data
from src.ui.helpers import (
    aqi_category, aqi_text_color, format_ist, to_ist, utc_now,
)
from src.ui.theme import (
    ACCENT, MUTED, SERIES, SEVERITY_COLORS, load_with_skeleton, note, section, stat_strip, style_fig,
)

VARIABLE_LABELS: dict[str, str] = {
    "wind_speed_mps": "Wind speed", "wind_direction_nw": "NW wind", "temperature_celsius": "Temperature",
    "humidity_percent": "Humidity", "pressure_hpa": "Pressure", "aqi": "AQI", "pm25": "PM2.5",
}
SEVERITIES = ["low", "medium", "high", "critical"]

FEATURE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Weather interaction", ("wind_stagnation_index", "moisture_trap", "ventilation_index", "inversion_proxy")),
    ("Delhi flags", ("is_stubble_season", "is_winter_inversion", "is_diwali_week", "wind_from_northwest",
                     "is_extreme_aqi")),
    ("Temporal", ("hour_of_day", "day_of_week", "is_weekend", "is_rush_hour", "month",
                  "season_winter", "season_monsoon", "season_summer")),
]


def _feature_group(name: str) -> str:
    """Assign a feature to exactly one catalog group."""
    for group, members in FEATURE_GROUPS:
        if name in members:
            return group
    if "lag" in name:
        return "Lag"
    if "rolling" in name:
        return "Rolling"
    if "delta" in name:
        return "Rate of change"
    return "Other"


def render_anomalies() -> None:
    """Anomaly scatter for one metric, severity counts, and detection-method mix."""
    section("Anomaly timeline")
    df = load_with_skeleton(data.load_anomalies, kind="chart")
    if df.empty:
        note("No anomalies detected yet", "Anomalies appear once enough history is loaded.")
        return

    stat_strip([
        (f"{int((df['severity'] == sev).sum()):,}", f"{sev.capitalize()} severity", SEVERITY_COLORS[sev])
        for sev in reversed(SEVERITIES)
    ])

    left, right = st.columns([1, 2])
    with left:
        metric = st.selectbox("Metric", sorted(df["metric"].unique()))
    with right:
        chosen = st.multiselect("Severity", SEVERITIES, default=["medium", "high", "critical"])

    view = df[(df["metric"] == metric) & df["severity"].isin(chosen)].copy()
    if view.empty:
        note("No anomalies match these filters")
    else:
        view["time_ist"] = to_ist(view["timestamp"])
        view["size"] = view["z_score"].abs().fillna(1).clip(1, 8)
        fig = px.scatter(
            view, x="time_ist", y="value", color="severity", size="size",
            hover_data={"station": True, "method": True, "expected_value": ":.1f", "size": False},
            color_discrete_map=SEVERITY_COLORS, category_orders={"severity": SEVERITIES},
            labels={"value": f"Observed {metric}", "time_ist": "Time (IST)"},
        )
        style_fig(fig, height=420)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    section("Detection methods")
    counts = df["method"].value_counts().sort_values()
    fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h", marker_color=ACCENT))
    style_fig(fig, height=220, xaxis_title="Anomalies", showlegend=False)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_forecast() -> None:
    """24-hour forecast per station, shown after recent observed AQI."""
    section("24-hour AQI forecast")
    fc = load_with_skeleton(data.load_forecasts, kind="chart")
    if fc.empty:
        note(
            "No forecasts yet",
            "Forecasts need about 10 hourly readings per station. Run the pipeline after a backfill.",
        )
        return

    station = st.selectbox("Station", sorted(fc["station"].unique()))
    one = fc[fc["station"] == station].copy()
    one["aqi"] = one["predicted_aqi"].round().astype(int)
    one["time_ist"] = to_ist(one["target_timestamp"])

    hist = data.load_aqi_history(3)
    hist = hist[hist["station"] == station].copy()
    hist["time_ist"] = to_ist(hist["timestamp"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["time_ist"], y=hist["aqi"], name="Observed", line=dict(color=SERIES[1], width=2)))
    fig.add_trace(go.Scatter(x=one["time_ist"], y=one["aqi"], name="Forecast", line=dict(color=SERIES[0], width=2, dash="dash")))
    now_ist = to_ist(pd.Series([utc_now()])).iloc[0]
    fig.add_shape(type="line", x0=now_ist, x1=now_ist, y0=0, y1=1, yref="paper", line=dict(color=MUTED, width=1, dash="dot"))
    fig.add_annotation(x=now_ist, y=1, yref="paper", text="Now", showarrow=False, font=dict(color=MUTED), yanchor="bottom")
    style_fig(fig, height=400, yaxis_title="AQI", xaxis_title="Time (IST)")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    peak = one.loc[one["aqi"].idxmax()]
    stat_strip([
        (str(int(peak["aqi"])), f"Forecast peak, {aqi_category(peak['aqi'])}", aqi_text_color(peak["aqi"])),
        (peak["time_ist"].strftime("%I:%M %p"), "Peak time (IST)", None),
        (str(int(round(one["aqi"].mean()))), "Forecast mean AQI", None),
        (f"{len(one)} h", "Horizon", None),
    ])
    st.caption(f"Model: {one['model_version'].iloc[0]}. Generated {format_ist(one['forecast_timestamp'].iloc[0])}.")

    with st.expander("Hourly forecast table"):
        table = pd.DataFrame({
            "Time (IST)": one["time_ist"].dt.strftime("%d %b, %I:%M %p"),
            "Predicted AQI": one["aqi"],
            "Category": one["aqi"].map(aqi_category),
        })
        st.dataframe(table.set_index("Time (IST)"), width="stretch")


def render_causality() -> None:
    """Granger p-value heatmap (pooled across stations) with multiple-testing context."""
    section("Granger causality matrix")
    df = load_with_skeleton(data.load_causality, kind="chart")
    if df.empty:
        note("No causality results yet", "Run: python -m src.orchestration.flows --causality")
        return

    n = len(df)
    df["pair"] = df["cause_variable"].map(VARIABLE_LABELS).fillna(df["cause_variable"]) + " to " + \
        df["effect_variable"].map(VARIABLE_LABELS).fillna(df["effect_variable"])
    pivot = df.pivot_table(index="pair", columns="lag_hours", values="p_value", aggfunc="first")
    stars = pivot.map(lambda p: "**" if p < 0.01 else ("*" if p < 0.05 else ""))

    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=[f"{c}h" for c in pivot.columns], y=list(pivot.index),
        colorscale=[[0.0, "#7fb0b3"], [0.25, "#3f6a6e"], [1.0, "#222a2f"]], zmin=0, zmax=0.2,
        text=stars.values, texttemplate="%{text}", textfont=dict(size=11, color="#f2f2ee"),
        hovertemplate="<b>%{y}</b><br>Lag %{x}<br>p-value %{z:.4f}<extra></extra>",
        colorbar=dict(title="p-value"),
    ))
    style_fig(fig, height=max(340, 52 * len(pivot)), xaxis=dict(side="top"), margin=dict(l=170, r=20, t=50, b=20))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("* p < 0.05, ** p < 0.01. Lighter cells have smaller p-values.")

    sig = df[df["p_value"] < 0.05]
    corrected = df[df["p_value"] < 0.05 / n]
    best = df.loc[df["p_value"].idxmin()]
    stat_strip([
        (f"{n}", "Tests (pooled across stations)", None),
        (f"{len(sig)}", "Significant at p < 0.05", None),
        (f"{len(corrected)}", f"Significant after Bonferroni (p < {0.05 / n:.5f})", None),
        (f"{int(best['lag_hours'])} h", f"Strongest: {best['pair']}", None),
    ])
    note(
        "How to read this",
        "Granger tests show that past values of one series help predict another. They do not prove "
        "physical causation, and neighbouring lags are correlated, so the raw count of significant lags overstates the evidence.",
    )


def render_features() -> None:
    """Feature store catalog with summary statistics and computation versions."""
    section("Feature store catalog")
    stats = load_with_skeleton(data.load_feature_stats, kind="table")
    if stats.empty:
        note("Feature store is empty", "Run the pipeline to compute features.")
        return

    stat_strip([
        (f"{len(stats)}", "Features", None),
        (f"{int(stats['count'].sum()):,}", "Stored values", None),
        (f"{data.load_feature_versions()}", "Computation timestamps", None),
        (format_ist(stats["last_computed"].max()), "Last computed", None),
    ])

    stats = stats.assign(group=stats["feature_name"].map(_feature_group))
    for group in sorted(stats["group"].unique()):
        part = stats[stats["group"] == group]
        with st.expander(f"{group} ({len(part)} features)", expanded=group in ("Delhi flags", "Weather interaction")):
            st.dataframe(
                part[["feature_name", "mean", "std", "min", "max", "count"]].set_index("feature_name").round(2),
                width="stretch",
            )

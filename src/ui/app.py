"""Vayu — Delhi Air Quality Intelligence Dashboard.

Streamlit dashboard with 10 tabs covering the full pipeline output:
AQI overview, trends, pollutant breakdown, anomalies, forecasts,
causality heatmap, feature store, AI advisory, data quality, pipeline health.
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# ---------------------------------------------------------------------------
# Page config & theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Vayu — Delhi Air Quality Intelligence",
    page_icon="🌬️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for dark, clean look with AQI-themed accents
st.markdown("""
<style>
    /* Dark background tweaks */
    .stApp { background-color: #0e1117; }
    .block-container { padding-top: 1.5rem; }

    /* AQI card styling */
    .aqi-card {
        border-radius: 12px;
        padding: 18px 14px;
        text-align: center;
        color: white;
        margin-bottom: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .aqi-card h2 { margin: 0; font-size: 2.2em; font-weight: 700; }
    .aqi-card h4 { margin: 4px 0 0 0; font-size: 0.95em; opacity: 0.92; }
    .aqi-card p { margin: 2px 0 0 0; font-size: 0.78em; opacity: 0.75; }

    /* Metric cards */
    .metric-card {
        background: #1a1d23;
        border: 1px solid #2d3139;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    .metric-card h1 { margin: 0; color: #e0e0e0; font-size: 2em; }
    .metric-card p { margin: 4px 0 0 0; color: #888; font-size: 0.85em; }

    /* Section headers */
    .section-header {
        color: #c0c0c0;
        font-size: 0.8em;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-bottom: 12px;
        border-bottom: 1px solid #2d3139;
        padding-bottom: 6px;
    }

    /* Advisory panel */
    .advisory-panel {
        background: #1a1d23;
        border-left: 4px solid #ff6b35;
        border-radius: 8px;
        padding: 20px;
        margin: 10px 0;
        white-space: pre-wrap;
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.9em;
        line-height: 1.6;
        color: #d0d0d0;
    }

    /* Grade badges */
    .grade-a { background: #2d8a4e; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700; }
    .grade-b { background: #5b9e3c; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700; }
    .grade-c { background: #d4a017; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700; }
    .grade-d { background: #d46a17; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700; }
    .grade-f { background: #c0392b; color: white; padding: 3px 10px; border-radius: 6px; font-weight: 700; }

    /* Hide default Streamlit footer */
    footer { visibility: hidden; }
    .stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_engine():
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/vayu")
    return create_engine(url)


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a SQL query and return a DataFrame."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


# ---------------------------------------------------------------------------
# AQI color helpers
# ---------------------------------------------------------------------------

AQI_COLORS = {
    "Good":         "#2d8a4e",
    "Satisfactory": "#5b9e3c",
    "Moderate":     "#d4a017",
    "Poor":         "#d46a17",
    "Very Poor":    "#c0392b",
    "Severe":       "#7b241c",
}

SEVERITY_COLORS = {
    "low":      "#5b9e3c",
    "medium":   "#d4a017",
    "high":     "#d46a17",
    "critical": "#c0392b",
}


def aqi_category(val: int) -> str:
    if val <= 50: return "Good"
    elif val <= 100: return "Satisfactory"
    elif val <= 200: return "Moderate"
    elif val <= 300: return "Poor"
    elif val <= 400: return "Very Poor"
    else: return "Severe"


def aqi_color(val: int) -> str:
    return AQI_COLORS.get(aqi_category(val), "#555")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

col_brand, col_time = st.columns([3, 1])
with col_brand:
    st.markdown("# VAYU")
    st.markdown(
        '<span style="color:#888; font-size:0.95em;">'
        'Delhi Air Quality Intelligence Pipeline &nbsp;|&nbsp; '
        'Real-time AQI monitoring across 7 NCR zones</span>',
        unsafe_allow_html=True,
    )
with col_time:
    now_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30))
    st.markdown(
        f'<div style="text-align:right; padding-top:20px; color:#888;">'
        f'{now_ist.strftime("%d %b %Y, %I:%M %p IST")}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tabs = st.tabs([
    "Overview",
    "AQI Trends",
    "Pollutants",
    "Anomalies",
    "Forecast",
    "Causality",
    "Features",
    "Advisory",
    "Data Quality",
    "Pipeline",
])

# ============================= TAB 0: OVERVIEW =============================
with tabs[0]:
    # Load latest AQI per location
    latest_aqi = query("""
        SELECT DISTINCT ON (location_id)
            a.location_id, s.name, s.zone, a.aqi, a.pm25, a.pm10, a.no2, a.o3, a.timestamp
        FROM aqi_readings a
        JOIN dim_stations s ON a.location_id = s.location_id
        ORDER BY a.location_id, a.timestamp DESC
    """)

    if not latest_aqi.empty:
        st.markdown('<div class="section-header">CURRENT AQI ACROSS DELHI NCR</div>', unsafe_allow_html=True)

        cols = st.columns(len(latest_aqi))
        for i, (_, row) in enumerate(latest_aqi.iterrows()):
            cat = aqi_category(row["aqi"])
            color = aqi_color(row["aqi"])
            with cols[i]:
                st.markdown(
                    f'<div class="aqi-card" style="background:{color};">'
                    f'<h2>{row["aqi"]}</h2>'
                    f'<h4>{row["name"]}</h4>'
                    f'<p>{cat} &bull; PM2.5: {row["pm25"]:.0f}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Key metrics row
        st.markdown('<div class="section-header">KEY METRICS</div>', unsafe_allow_html=True)
        avg_aqi = int(latest_aqi["aqi"].mean())
        worst = latest_aqi.loc[latest_aqi["aqi"].idxmax()]
        best = latest_aqi.loc[latest_aqi["aqi"].idxmin()]

        # Dominant pollutant across all stations
        pollutant_cols = {"pm25": 60, "pm10": 100, "no2": 80, "o3": 100}
        ratios = {p: (latest_aqi[p] / std).mean() for p, std in pollutant_cols.items()}
        dominant = max(ratios, key=ratios.get).upper().replace("PM25", "PM2.5").replace("PM10", "PM10")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(
                f'<div class="metric-card"><h1>{avg_aqi}</h1>'
                f'<p>NCR Average AQI<br>{aqi_category(avg_aqi)}</p></div>',
                unsafe_allow_html=True,
            )
        with m2:
            st.markdown(
                f'<div class="metric-card"><h1 style="color:{aqi_color(int(worst["aqi"]))}">{int(worst["aqi"])}</h1>'
                f'<p>Worst Zone<br>{worst["name"]}</p></div>',
                unsafe_allow_html=True,
            )
        with m3:
            st.markdown(
                f'<div class="metric-card"><h1 style="color:{aqi_color(int(best["aqi"]))}">{int(best["aqi"])}</h1>'
                f'<p>Best Zone<br>{best["name"]}</p></div>',
                unsafe_allow_html=True,
            )
        with m4:
            st.markdown(
                f'<div class="metric-card"><h1>{dominant}</h1>'
                f'<p>Dominant Pollutant<br>Across NCR</p></div>',
                unsafe_allow_html=True,
            )

        # Station measurements comparison
        station_data = query("""
            SELECT DISTINCT ON (sm.location_id)
                sm.location_id, s.name, sm.pm25, sm.pm10, sm.no2, sm.o3, sm.temperature_celsius, sm.humidity_percent
            FROM station_measurements sm
            JOIN dim_stations s ON sm.location_id = s.location_id
            ORDER BY sm.location_id, sm.timestamp DESC
        """)
        if not station_data.empty:
            st.markdown('<div class="section-header">GROUND STATION READINGS (CPCB)</div>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=station_data["name"], y=station_data["pm25"], name="PM2.5",
                                 marker_color="#e74c3c"))
            fig.add_trace(go.Bar(x=station_data["name"], y=station_data["pm10"], name="PM10",
                                 marker_color="#e67e22"))
            fig.update_layout(
                barmode="group", template="plotly_dark",
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                height=350, margin=dict(l=40, r=20, t=30, b=40),
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No AQI data available. Run the pipeline first.")


# ============================= TAB 1: AQI TRENDS ==========================
with tabs[1]:
    st.markdown('<div class="section-header">AQI TRENDS OVER TIME</div>', unsafe_allow_html=True)

    trend_data = query("""
        SELECT a.timestamp, a.aqi, a.pm25, s.name as station, s.zone
        FROM aqi_readings a
        JOIN dim_stations s ON a.location_id = s.location_id
        ORDER BY a.timestamp
    """)

    if not trend_data.empty:
        zones = sorted(trend_data["zone"].unique())
        selected_zones = st.multiselect("Select zones:", zones, default=zones[:3])

        filtered = trend_data[trend_data["zone"].isin(selected_zones)]
        if not filtered.empty:
            fig = px.line(
                filtered, x="timestamp", y="aqi", color="station",
                labels={"aqi": "AQI", "timestamp": "Time (UTC)"},
            )
            # Add AQI band backgrounds
            for band, y0, y1, color in [
                ("Good", 0, 50, "rgba(45,138,78,0.1)"),
                ("Satisfactory", 50, 100, "rgba(91,158,60,0.1)"),
                ("Moderate", 100, 200, "rgba(212,160,23,0.1)"),
                ("Poor", 200, 300, "rgba(212,106,23,0.1)"),
                ("Very Poor", 300, 400, "rgba(192,57,43,0.1)"),
            ]:
                fig.add_hrect(y0=y0, y1=y1, fillcolor=color, line_width=0,
                              annotation_text=band, annotation_position="top left",
                              annotation_font_size=10, annotation_font_color="#666")

            fig.update_layout(
                template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                height=500, margin=dict(l=40, r=20, t=30, b=40),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No trend data available.")


# ============================= TAB 2: POLLUTANTS ==========================
with tabs[2]:
    st.markdown('<div class="section-header">POLLUTANT BREAKDOWN BY STATION</div>', unsafe_allow_html=True)

    poll_data = query("""
        SELECT DISTINCT ON (a.location_id)
            s.name, a.pm25, a.pm10, a.no2, a.so2, a.o3, a.co
        FROM aqi_readings a
        JOIN dim_stations s ON a.location_id = s.location_id
        ORDER BY a.location_id, a.timestamp DESC
    """)

    if not poll_data.empty:
        # Normalize to NAAQS standards for relative comparison
        norms = {"pm25": 60, "pm10": 100, "no2": 80, "so2": 80, "o3": 100, "co": 4000}
        norm_df = poll_data.copy()
        for p, std in norms.items():
            norm_df[p] = norm_df[p] / std * 100

        fig = go.Figure()
        colors = {"pm25": "#e74c3c", "pm10": "#e67e22", "no2": "#f39c12",
                  "so2": "#9b59b6", "o3": "#3498db", "co": "#1abc9c"}
        for pollutant, color in colors.items():
            label = pollutant.upper().replace("PM25", "PM2.5").replace("PM10", "PM10")
            fig.add_trace(go.Bar(
                x=norm_df["name"], y=norm_df[pollutant], name=label,
                marker_color=color,
            ))

        fig.add_hline(y=100, line_dash="dash", line_color="#ff6b6b",
                      annotation_text="NAAQS Standard (100%)")
        fig.update_layout(
            barmode="stack", template="plotly_dark",
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            yaxis_title="% of NAAQS Standard",
            height=450, margin=dict(l=40, r=20, t=30, b=40),
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Raw values table
        with st.expander("Raw pollutant concentrations (ug/m3)"):
            display_df = poll_data.rename(columns={
                "name": "Station", "pm25": "PM2.5", "pm10": "PM10",
                "no2": "NO2", "so2": "SO2", "o3": "O3", "co": "CO"
            })
            st.dataframe(display_df.set_index("Station"), use_container_width=True)
    else:
        st.info("No pollutant data available.")


# ============================= TAB 3: ANOMALIES ==========================
with tabs[3]:
    st.markdown('<div class="section-header">ANOMALY TIMELINE</div>', unsafe_allow_html=True)

    anomaly_data = query("""
        SELECT al.timestamp, al.location_id, s.name as station, al.metric,
               al.value, al.expected_value, al.z_score, al.method, al.severity
        FROM anomaly_log al
        JOIN dim_stations s ON al.location_id = s.location_id
        ORDER BY al.timestamp DESC
        LIMIT 500
    """)

    if not anomaly_data.empty:
        sev_filter = st.multiselect(
            "Filter by severity:", ["low", "medium", "high", "critical"],
            default=["medium", "high", "critical"],
        )
        filtered = anomaly_data[anomaly_data["severity"].isin(sev_filter)]

        if not filtered.empty:
            fig = px.scatter(
                filtered, x="timestamp", y="value", color="severity",
                size="z_score", hover_data=["station", "metric", "method", "expected_value"],
                color_discrete_map=SEVERITY_COLORS,
                labels={"value": "Observed Value", "timestamp": "Time"},
            )
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                height=450, margin=dict(l=40, r=20, t=30, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

        # Summary stats
        c1, c2, c3, c4 = st.columns(4)
        for col, sev in zip([c1, c2, c3, c4], ["critical", "high", "medium", "low"]):
            count = len(anomaly_data[anomaly_data["severity"] == sev])
            color = SEVERITY_COLORS[sev]
            with col:
                st.markdown(
                    f'<div class="metric-card"><h1 style="color:{color}">{count}</h1>'
                    f'<p>{sev.upper()}</p></div>',
                    unsafe_allow_html=True,
                )

        # Detection method breakdown
        method_counts = anomaly_data["method"].value_counts()
        fig2 = px.pie(values=method_counts.values, names=method_counts.index,
                      color_discrete_sequence=["#3498db", "#e74c3c", "#f39c12", "#2ecc71"])
        fig2.update_layout(
            template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            height=300, margin=dict(l=20, r=20, t=30, b=20),
            title="Detection Method Distribution",
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No anomalies detected yet.")


# ============================= TAB 4: FORECAST ============================
with tabs[4]:
    st.markdown('<div class="section-header">FORECAST VS ACTUAL AQI</div>', unsafe_allow_html=True)

    forecast_data = query("""
        SELECT f.location_id, s.name as station, f.target_timestamp,
               f.predicted_aqi, f.predicted_category, f.actual_aqi, f.model_version
        FROM forecasts f
        JOIN dim_stations s ON f.location_id = s.location_id
        ORDER BY f.target_timestamp
    """)

    if not forecast_data.empty and len(forecast_data) > 0:
        stations = forecast_data["station"].unique()
        selected = st.selectbox("Select station:", stations)
        loc_fc = forecast_data[forecast_data["station"] == selected]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=loc_fc["target_timestamp"], y=loc_fc["predicted_aqi"],
            name="Predicted", line=dict(color="#3498db", width=2),
        ))
        if loc_fc["actual_aqi"].notna().any():
            fig.add_trace(go.Scatter(
                x=loc_fc["target_timestamp"], y=loc_fc["actual_aqi"],
                name="Actual", line=dict(color="#e74c3c", width=2, dash="dot"),
            ))
        fig.update_layout(
            template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            yaxis_title="AQI", height=400,
            margin=dict(l=40, r=20, t=30, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Show Prophet model metrics if available
        st.info("No forecast data in database yet. Forecasts will appear after a full pipeline run with sufficient historical data.")
        st.markdown("""
        **Prophet Model Configuration:**
        - 24-hour ahead forecast per zone
        - Regressors from feature store: wind stagnation, moisture trap, seasonal flags
        - Evaluation: MAPE, RMSE, and AQI category accuracy
        """)


# ============================= TAB 5: CAUSALITY ===========================
with tabs[5]:
    st.markdown('<div class="section-header">GRANGER CAUSALITY MATRIX</div>', unsafe_allow_html=True)
    st.caption("Green = statistically significant (p < 0.05). Tests whether weather variables help predict pollution.")

    causality_data = query("""
        SELECT cause_variable, effect_variable, lag_hours, p_value, f_statistic, is_significant
        FROM causality_results
        WHERE notes = 'pooled_all_locations'
        ORDER BY cause_variable, effect_variable, lag_hours
    """)

    if not causality_data.empty:
        # Pivot to create heatmap: rows = cause->effect pairs, columns = lag hours
        causality_data["pair"] = causality_data["cause_variable"] + " → " + causality_data["effect_variable"]
        pivot = causality_data.pivot_table(
            index="pair", columns="lag_hours", values="p_value", aggfunc="first"
        )

        # Create heatmap with custom colorscale (green = significant, red = not)
        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=[f"Lag {c}h" for c in pivot.columns],
            y=pivot.index,
            colorscale=[
                [0.0, "#1a9850"],   # p=0 (very significant) - deep green
                [0.05, "#66bd63"],  # p=0.05 threshold
                [0.1, "#d9ef8b"],   # marginal
                [0.3, "#fee08b"],   # not significant
                [0.5, "#fc8d59"],
                [1.0, "#d73027"],   # p=1 (not significant) - red
            ],
            zmin=0, zmax=0.5,
            text=np.where(pivot.values < 0.05, "SIG", ""),
            texttemplate="%{text}",
            textfont={"size": 10, "color": "white"},
            hovertemplate="<b>%{y}</b><br>Lag: %{x}<br>p-value: %{z:.4f}<extra></extra>",
            colorbar=dict(title="p-value", tickvals=[0, 0.05, 0.1, 0.25, 0.5]),
        ))

        fig.update_layout(
            template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            height=max(350, len(pivot) * 50),
            margin=dict(l=200, r=40, t=30, b=40),
            xaxis=dict(side="top"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Key insight callout
        sig_results = causality_data[causality_data["is_significant"]]
        if not sig_results.empty:
            best = sig_results.loc[sig_results["p_value"].idxmin()]
            st.success(
                f"**Key finding:** {best['cause_variable']} Granger-causes {best['effect_variable']} "
                f"at a {best['lag_hours']}-hour lag (F={best['f_statistic']:.2f}, p={best['p_value']:.4f}). "
                f"Total: {len(sig_results)} significant relationships found."
            )
    else:
        st.info("No causality results yet. Run the pipeline with `--causality` flag.")


# ============================= TAB 6: FEATURES ============================
with tabs[6]:
    st.markdown('<div class="section-header">FEATURE STORE CATALOG</div>', unsafe_allow_html=True)

    feature_summary = query("""
        SELECT feature_name,
               COUNT(*) as count,
               ROUND(AVG(feature_value)::numeric, 2) as mean,
               ROUND(STDDEV(feature_value)::numeric, 2) as std,
               ROUND(MIN(feature_value)::numeric, 2) as min,
               ROUND(MAX(feature_value)::numeric, 2) as max,
               MAX(computed_at) as last_computed
        FROM feature_store
        GROUP BY feature_name
        ORDER BY feature_name
    """)

    if not feature_summary.empty:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total Features", len(feature_summary))
        with c2:
            st.metric("Total Values", f"{feature_summary['count'].sum():,}")
        with c3:
            latest = feature_summary["last_computed"].max()
            if pd.notna(latest):
                ago = (datetime.utcnow() - pd.Timestamp(latest).to_pydatetime()).total_seconds() / 60
                st.metric("Last Computed", f"{ago:.0f} min ago")

        # Feature table with categories
        categories = {
            "Lag": [f for f in feature_summary["feature_name"] if "lag" in f],
            "Rolling": [f for f in feature_summary["feature_name"] if "rolling" in f],
            "Rate of Change": [f for f in feature_summary["feature_name"] if "delta" in f],
            "Weather Interaction": [f for f in feature_summary["feature_name"] if f in
                                     ("wind_stagnation_index", "moisture_trap", "ventilation_index", "inversion_proxy")],
            "Temporal": [f for f in feature_summary["feature_name"] if f in
                          ("hour_of_day", "day_of_week", "is_weekend", "is_rush_hour", "month",
                           "season_winter", "season_monsoon", "season_summer")],
            "Delhi Flags": [f for f in feature_summary["feature_name"] if f.startswith("is_") or f == "wind_from_northwest"],
        }

        for cat_name, features in categories.items():
            if features:
                cat_df = feature_summary[feature_summary["feature_name"].isin(features)]
                if not cat_df.empty:
                    with st.expander(f"{cat_name} ({len(cat_df)} features)", expanded=(cat_name in ("Delhi Flags", "Weather Interaction"))):
                        st.dataframe(
                            cat_df[["feature_name", "mean", "std", "min", "max", "count"]].set_index("feature_name"),
                            use_container_width=True,
                        )
    else:
        st.info("Feature store is empty. Run the pipeline to compute features.")


# ============================= TAB 7: ADVISORY ============================
with tabs[7]:
    st.markdown('<div class="section-header">AI HEALTH ADVISORY</div>', unsafe_allow_html=True)

    advisory_data = query("""
        SELECT id, advisory_text, avg_aqi, worst_location, worst_aqi,
               model_used, generated_at
        FROM advisories
        ORDER BY generated_at DESC
        LIMIT 5
    """)

    if not advisory_data.empty:
        latest = advisory_data.iloc[0]
        gen_time = pd.Timestamp(latest["generated_at"])
        ist_time = gen_time + timedelta(hours=5, minutes=30)

        st.markdown(
            f'<span style="color:#888;">Advisory #{latest["id"]} &bull; '
            f'Generated {ist_time.strftime("%d %b %Y, %I:%M %p IST")} &bull; '
            f'Model: {latest["model_used"]}</span>',
            unsafe_allow_html=True,
        )

        if latest["avg_aqi"] is not None:
            ac1, ac2, ac3 = st.columns(3)
            with ac1:
                st.metric("Average AQI", latest["avg_aqi"])
            with ac2:
                wl = latest["worst_location"] or "N/A"
                st.metric("Worst Location", wl)
            with ac3:
                st.metric("Worst AQI", latest["worst_aqi"] or "N/A")

        st.markdown(
            f'<div class="advisory-panel">{latest["advisory_text"]}</div>',
            unsafe_allow_html=True,
        )

        # Previous advisories
        if len(advisory_data) > 1:
            with st.expander(f"Previous advisories ({len(advisory_data) - 1})"):
                for _, row in advisory_data.iloc[1:].iterrows():
                    t = pd.Timestamp(row["generated_at"]) + timedelta(hours=5, minutes=30)
                    st.markdown(f"**#{row['id']}** — {t.strftime('%d %b %Y %I:%M %p')} — AQI: {row['avg_aqi']}")
    else:
        st.info("No advisories generated yet. Run the pipeline to generate one.")


# ============================= TAB 8: DATA QUALITY ========================
with tabs[8]:
    st.markdown('<div class="section-header">DATA QUALITY SCORES</div>', unsafe_allow_html=True)

    dq_data = query("""
        SELECT DISTINCT ON (source) source, completeness, freshness_seconds,
               consistency, overall_grade, details, scored_at
        FROM data_quality_scores
        ORDER BY source, scored_at DESC
    """)

    if not dq_data.empty:
        cols = st.columns(len(dq_data))
        for i, (_, row) in enumerate(dq_data.iterrows()):
            grade = row["overall_grade"]
            grade_class = f"grade-{grade.lower()}"
            with cols[i]:
                source_label = row["source"].replace("_", " ").title()
                fresh_min = row["freshness_seconds"] / 60 if row["freshness_seconds"] else None
                fresh_str = f"{fresh_min:.0f} min" if fresh_min else "N/A"

                st.markdown(
                    f'<div class="metric-card">'
                    f'<h1><span class="{grade_class}">{grade}</span></h1>'
                    f'<p><b>{source_label}</b></p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.progress(min(row["completeness"] / 100, 1.0), text=f"Completeness: {row['completeness']:.0f}%")
                st.caption(f"Freshness: {fresh_str}")

        # Consistency detail
        consistency_val = dq_data["consistency"].dropna()
        if not consistency_val.empty:
            st.markdown('<div class="section-header" style="margin-top:20px">CROSS-SOURCE CONSISTENCY</div>',
                        unsafe_allow_html=True)
            st.caption("How well do OpenWeatherMap and ground station PM2.5 readings agree?")
            cons = consistency_val.iloc[0]
            st.progress(min(max(cons, 0) / 100, 1.0), text=f"Consistency score: {cons:.0f}%")
    else:
        st.info("No data quality scores yet.")


# ============================= TAB 9: PIPELINE ============================
with tabs[9]:
    st.markdown('<div class="section-header">PIPELINE HEALTH</div>', unsafe_allow_html=True)

    # Table row counts as proxy for pipeline activity
    counts = query("""
        SELECT 'Weather Readings' as source, COUNT(*) as rows, MAX(ingested_at) as last_update FROM weather_readings
        UNION ALL SELECT 'AQI Readings', COUNT(*), MAX(ingested_at) FROM aqi_readings
        UNION ALL SELECT 'Station Measurements', COUNT(*), MAX(ingested_at) FROM station_measurements
        UNION ALL SELECT 'Anomaly Log', COUNT(*), MAX(detected_at) FROM anomaly_log
        UNION ALL SELECT 'Feature Store', COUNT(*), MAX(computed_at) FROM feature_store
        UNION ALL SELECT 'Causality Results', COUNT(*), MAX(computed_at) FROM causality_results
        UNION ALL SELECT 'Advisories', COUNT(*), MAX(generated_at) FROM advisories
        UNION ALL SELECT 'Data Quality', COUNT(*), MAX(scored_at) FROM data_quality_scores
    """)

    if not counts.empty:
        c1, c2 = st.columns([2, 1])
        with c1:
            # Bar chart of table sizes
            fig = px.bar(
                counts, x="source", y="rows",
                color="rows", color_continuous_scale="Blues",
                labels={"rows": "Row Count", "source": ""},
            )
            fig.update_layout(
                template="plotly_dark", plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                height=350, margin=dict(l=40, r=20, t=30, b=80),
                showlegend=False, coloraxis_showscale=False,
            )
            fig.update_xaxes(tickangle=45)
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("**Table Status**")
            for _, row in counts.iterrows():
                last = row["last_update"]
                if pd.notna(last):
                    ago = (datetime.utcnow() - pd.Timestamp(last).to_pydatetime()).total_seconds()
                    if ago < 300:
                        status = "🟢"
                    elif ago < 3600:
                        status = "🟡"
                    else:
                        status = "🔴"
                    ago_str = f"{ago/60:.0f}m ago" if ago < 3600 else f"{ago/3600:.1f}h ago"
                else:
                    status = "⚪"
                    ago_str = "never"
                st.markdown(f"{status} **{row['source']}** — {row['rows']:,} rows — {ago_str}")

        # Pipeline instructions
        st.markdown("---")
        st.markdown("**Run the pipeline:**")
        st.code("d:/vayu_env/Scripts/python -m src.orchestration.flows", language="bash")
        st.code("d:/vayu_env/Scripts/python -m src.orchestration.flows --causality  # daily run", language="bash")
        st.markdown("**Start Prefect UI:**")
        st.code("d:/vayu_env/Scripts/prefect server start  # then visit http://localhost:4200", language="bash")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    '<div style="text-align:center; color:#555; font-size:0.75em; padding: 10px 0;">'
    'Vayu Air Quality Intelligence Pipeline &bull; '
    'Data: OpenWeatherMap + Simulated CPCB &bull; '
    'Built with Prefect, dbt, Prophet, GPT-4o-mini, Streamlit'
    '</div>',
    unsafe_allow_html=True,
)

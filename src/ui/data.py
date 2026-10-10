"""Cached, backend-agnostic data loaders for the dashboard.

Queries use SQLAlchemy 2.0 constructs on the shared engine (PostgreSQL with automatic
SQLite fallback), so nothing here is dialect-specific. Timestamps stay in UTC; convert
with ``src.ui.helpers.to_ist`` at render time.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import Select, func, select

from src.storage.db import get_engine, is_postgres
from src.storage.models import (
    Advisory,
    AnomalyLog,
    AQIReadingRow,
    CausalityResult,
    DataQualityScore,
    DimStation,
    FeatureStoreRow,
    ForecastRow,
    StationMeasurementRow,
    WeatherReadingRow,
)
from src.ui.helpers import utc_now

TTL = 60          # seconds, live readings
TTL_SLOW = 300    # seconds, heavier aggregates


def _read(stmt: Select) -> pd.DataFrame:
    """Execute a SELECT on the shared engine and return a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def _latest_per_location(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """Keep the most recent row for each location_id."""
    if df.empty:
        return df
    return df.sort_values(ts_col).groupby("location_id", as_index=False).tail(1).reset_index(drop=True)


@st.cache_data(ttl=TTL, show_spinner=False)
def backend_label() -> str:
    """Name the active database backend for the pipeline tab."""
    return "PostgreSQL" if is_postgres() else "SQLite (fallback)"


@st.cache_data(ttl=TTL, show_spinner=False)
def load_latest_aqi() -> pd.DataFrame:
    """Latest AQI reading per station at or before now (future forecast rows excluded)."""
    now = utc_now()
    stmt = (
        select(
            AQIReadingRow.location_id, DimStation.name, DimStation.zone, AQIReadingRow.timestamp,
            AQIReadingRow.aqi, AQIReadingRow.pm25, AQIReadingRow.pm10, AQIReadingRow.no2,
            AQIReadingRow.so2, AQIReadingRow.o3, AQIReadingRow.co,
        )
        .join(DimStation, DimStation.location_id == AQIReadingRow.location_id)
        .where(AQIReadingRow.timestamp <= now, AQIReadingRow.timestamp >= now - timedelta(days=3))
    )
    return _latest_per_location(_read(stmt))


@st.cache_data(ttl=TTL, show_spinner=False)
def load_aqi_history(days: int) -> pd.DataFrame:
    """Hourly AQI per station for the last ``days`` days, up to now."""
    now = utc_now()
    stmt = (
        select(
            AQIReadingRow.timestamp, AQIReadingRow.location_id, DimStation.name.label("station"),
            DimStation.zone, AQIReadingRow.aqi, AQIReadingRow.pm25,
        )
        .join(DimStation, DimStation.location_id == AQIReadingRow.location_id)
        .where(AQIReadingRow.timestamp <= now, AQIReadingRow.timestamp >= now - timedelta(days=days))
        .order_by(AQIReadingRow.timestamp)
    )
    return _read(stmt)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_latest_station_measurements() -> pd.DataFrame:
    """Latest ground-station (simulated CPCB) reading per station."""
    now = utc_now()
    stmt = (
        select(
            StationMeasurementRow.location_id, DimStation.name, StationMeasurementRow.timestamp,
            StationMeasurementRow.pm25, StationMeasurementRow.pm10, StationMeasurementRow.source,
        )
        .join(DimStation, DimStation.location_id == StationMeasurementRow.location_id)
        .where(
            StationMeasurementRow.timestamp <= now,
            StationMeasurementRow.timestamp >= now - timedelta(days=3),
        )
    )
    return _latest_per_location(_read(stmt))


@st.cache_data(ttl=TTL, show_spinner=False)
def load_latest_weather() -> pd.DataFrame:
    """Latest weather reading per station at or before now."""
    now = utc_now()
    stmt = (
        select(
            WeatherReadingRow.location_id, DimStation.name, WeatherReadingRow.timestamp,
            WeatherReadingRow.wind_speed_mps, WeatherReadingRow.wind_direction_deg,
            WeatherReadingRow.temperature_celsius, WeatherReadingRow.humidity_percent,
        )
        .join(DimStation, DimStation.location_id == WeatherReadingRow.location_id)
        .where(WeatherReadingRow.timestamp <= now, WeatherReadingRow.timestamp >= now - timedelta(days=3))
    )
    return _latest_per_location(_read(stmt))


@st.cache_data(ttl=TTL, show_spinner=False)
def load_anomalies(limit: int = 2000) -> pd.DataFrame:
    """Most recent anomalies (by observation time), joined to station names."""
    stmt = (
        select(
            AnomalyLog.timestamp, AnomalyLog.location_id, DimStation.name.label("station"),
            AnomalyLog.metric, AnomalyLog.value, AnomalyLog.expected_value, AnomalyLog.z_score,
            AnomalyLog.method, AnomalyLog.severity,
        )
        .join(DimStation, DimStation.location_id == AnomalyLog.location_id)
        .order_by(AnomalyLog.timestamp.desc())
        .limit(limit)
    )
    return _read(stmt)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_forecasts() -> pd.DataFrame:
    """Latest forecast run per station (older runs share a different forecast_timestamp)."""
    stmt = (
        select(
            ForecastRow.location_id, DimStation.name.label("station"), ForecastRow.target_timestamp,
            ForecastRow.predicted_aqi, ForecastRow.predicted_category, ForecastRow.actual_aqi,
            ForecastRow.model_version, ForecastRow.forecast_timestamp, ForecastRow.created_at,
        )
        .join(DimStation, DimStation.location_id == ForecastRow.location_id)
    )
    df = _read(stmt)
    if df.empty:
        return df
    newest = df.groupby("location_id")["forecast_timestamp"].transform("max")
    return df[df["forecast_timestamp"] == newest].sort_values(["station", "target_timestamp"]).reset_index(drop=True)


@st.cache_data(ttl=TTL_SLOW, show_spinner=False)
def load_causality() -> pd.DataFrame:
    """Pooled Granger results, keeping only the newest result per (cause, effect, lag)."""
    stmt = select(
        CausalityResult.id, CausalityResult.cause_variable, CausalityResult.effect_variable,
        CausalityResult.lag_hours, CausalityResult.f_statistic, CausalityResult.p_value,
        CausalityResult.is_significant, CausalityResult.computed_at,
    ).where(CausalityResult.notes == "pooled_all_locations")
    df = _read(stmt)
    if df.empty:
        return df
    key = ["cause_variable", "effect_variable", "lag_hours"]
    return df.sort_values("id").drop_duplicates(key, keep="last").reset_index(drop=True)


@st.cache_data(ttl=TTL_SLOW, show_spinner=False)
def load_feature_stats() -> pd.DataFrame:
    """Per-feature summary statistics computed in the database."""
    v = FeatureStoreRow.feature_value
    stmt = select(
        FeatureStoreRow.feature_name,
        func.count().label("count"),
        func.avg(v).label("mean"),
        func.avg(v * v).label("mean_sq"),
        func.min(v).label("min"),
        func.max(v).label("max"),
        func.max(FeatureStoreRow.computed_at).label("last_computed"),
    ).group_by(FeatureStoreRow.feature_name).order_by(FeatureStoreRow.feature_name)
    df = _read(stmt)
    if not df.empty:
        df["std"] = np.sqrt((df["mean_sq"] - df["mean"] ** 2).clip(lower=0))
    return df


@st.cache_data(ttl=TTL_SLOW, show_spinner=False)
def load_feature_versions() -> int:
    """Number of distinct computation timestamps in the feature store."""
    with get_engine().connect() as conn:
        return int(conn.execute(select(func.count(func.distinct(FeatureStoreRow.computed_at)))).scalar() or 0)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_advisories(limit: int = 5) -> pd.DataFrame:
    """Most recent AI health advisories."""
    stmt = (
        select(
            Advisory.id, Advisory.advisory_text, Advisory.avg_aqi, Advisory.worst_location,
            Advisory.worst_aqi, Advisory.model_used, Advisory.generated_at,
        )
        .order_by(Advisory.generated_at.desc())
        .limit(limit)
    )
    return _read(stmt)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_data_quality() -> pd.DataFrame:
    """Latest data quality score per source."""
    stmt = select(
        DataQualityScore.source, DataQualityScore.completeness, DataQualityScore.freshness_seconds,
        DataQualityScore.consistency, DataQualityScore.overall_grade, DataQualityScore.scored_at,
    )
    df = _read(stmt)
    if df.empty:
        return df
    return df.sort_values("scored_at").groupby("source", as_index=False).tail(1).reset_index(drop=True)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_table_status() -> pd.DataFrame:
    """Row count and last-write time for each pipeline table."""
    tables = [
        ("Weather readings", WeatherReadingRow.id, WeatherReadingRow.ingested_at),
        ("AQI readings", AQIReadingRow.id, AQIReadingRow.ingested_at),
        ("Station measurements", StationMeasurementRow.id, StationMeasurementRow.ingested_at),
        ("Anomaly log", AnomalyLog.id, AnomalyLog.detected_at),
        ("Forecasts", ForecastRow.id, ForecastRow.created_at),
        ("Feature store", FeatureStoreRow.id, FeatureStoreRow.computed_at),
        ("Causality results", CausalityResult.id, CausalityResult.computed_at),
        ("Advisories", Advisory.id, Advisory.generated_at),
        ("Data quality", DataQualityScore.id, DataQualityScore.scored_at),
    ]
    rows = []
    with get_engine().connect() as conn:
        for label, id_col, ts_col in tables:
            count, last = conn.execute(select(func.count(id_col), func.max(ts_col))).one()
            rows.append({"table": label, "rows": int(count), "last_update": last})
    return pd.DataFrame(rows)

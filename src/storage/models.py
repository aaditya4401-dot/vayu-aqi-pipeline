"""SQLAlchemy 2.0 ORM models for the Vayu data warehouse.

Star schema design:
- Fact tables: weather_readings, aqi_readings, station_measurements
- Dimension tables: dim_stations, dim_pollutants
- Feature table: feature_store (versioned computed features)
- Results tables: anomaly_log, forecasts, causality_results, advisories
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Dimension Tables
# ---------------------------------------------------------------------------

class DimStation(Base):
    """Dimension table for the 7 Delhi NCR monitoring locations."""

    __tablename__ = "dim_stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    zone: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DimStation {self.location_id}: {self.name}>"


class DimPollutant(Base):
    """Dimension table for tracked pollutants."""

    __tablename__ = "dim_pollutants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="ug/m3")
    who_guideline: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DimPollutant {self.code}: {self.name}>"


# ---------------------------------------------------------------------------
# Fact Tables
# ---------------------------------------------------------------------------

class WeatherReadingRow(Base):
    """Fact table for weather observations."""

    __tablename__ = "weather_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    temperature_celsius: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_percent: Mapped[float] = mapped_column(Float, nullable=False)
    pressure_hpa: Mapped[float] = mapped_column(Float, nullable=False)
    wind_speed_mps: Mapped[float] = mapped_column(Float, nullable=False)
    wind_direction_deg: Mapped[float] = mapped_column(Float, nullable=False)
    visibility_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    clouds_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="openweathermap")
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("location_id", "timestamp", "source", name="uq_weather_loc_ts_src"),
        Index("ix_weather_loc_ts", "location_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<WeatherReading {self.location_id} @ {self.timestamp}>"


class AQIReadingRow(Base):
    """Fact table for air quality readings."""

    __tablename__ = "aqi_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    aqi: Mapped[int] = mapped_column(Integer, nullable=False)
    pm25: Mapped[float] = mapped_column(Float, nullable=False)
    pm10: Mapped[float] = mapped_column(Float, nullable=False)
    no2: Mapped[float] = mapped_column(Float, nullable=False)
    so2: Mapped[float] = mapped_column(Float, nullable=False)
    o3: Mapped[float] = mapped_column(Float, nullable=False)
    co: Mapped[float] = mapped_column(Float, nullable=False)
    nh3: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="openweathermap")
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("location_id", "timestamp", "source", name="uq_aqi_loc_ts_src"),
        Index("ix_aqi_loc_ts", "location_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AQIReading {self.location_id} AQI={self.aqi} @ {self.timestamp}>"


class StationMeasurementRow(Base):
    """Fact table for ground-station measurements (real + simulated)."""

    __tablename__ = "station_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(String(100), nullable=False)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pm25: Mapped[float] = mapped_column(Float, nullable=False)
    pm10: Mapped[float] = mapped_column(Float, nullable=False)
    no2: Mapped[float | None] = mapped_column(Float, nullable=True)
    so2: Mapped[float | None] = mapped_column(Float, nullable=True)
    o3: Mapped[float | None] = mapped_column(Float, nullable=True)
    co: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_celsius: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="simulated_cpcb")
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("station_id", "location_id", "timestamp", "source", name="uq_station_loc_ts_src"),
        Index("ix_station_loc_ts", "location_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<StationMeasurement {self.station_id} @ {self.timestamp}>"


# ---------------------------------------------------------------------------
# Feature Store
# ---------------------------------------------------------------------------

class FeatureStoreRow(Base):
    """Versioned computed features for ML consumption."""

    __tablename__ = "feature_store"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    feature_name: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_value: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("location_id", "timestamp", "feature_name", name="uq_feature_loc_ts_name"),
        Index("ix_feature_loc_ts", "location_id", "timestamp"),
        Index("ix_feature_name", "feature_name"),
    )

    def __repr__(self) -> str:
        return f"<Feature {self.feature_name}={self.feature_value} @ {self.location_id} {self.timestamp}>"


# ---------------------------------------------------------------------------
# Results Tables
# ---------------------------------------------------------------------------

class AnomalyLog(Base):
    """Detected anomalies with context."""

    __tablename__ = "anomaly_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_anomaly_loc_ts", "location_id", "timestamp"),
        Index("ix_anomaly_severity", "severity"),
    )

    def __repr__(self) -> str:
        return f"<Anomaly {self.metric} {self.severity} @ {self.location_id}>"


class ForecastRow(Base):
    """AQI forecast predictions vs actuals."""

    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    forecast_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    target_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    predicted_aqi: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_aqi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_version: Mapped[str] = mapped_column(String(50), default="prophet_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "location_id", "forecast_timestamp", "target_timestamp", "model_version",
            name="uq_forecast_loc_fts_tts_mv",
        ),
        Index("ix_forecast_loc_target", "location_id", "target_timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Forecast {self.location_id} pred={self.predicted_aqi} @ {self.target_timestamp}>"


class CausalityResult(Base):
    """Granger causality test results."""

    __tablename__ = "causality_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cause_variable: Mapped[str] = mapped_column(String(50), nullable=False)
    effect_variable: Mapped[str] = mapped_column(String(50), nullable=False)
    lag_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    f_statistic: Mapped[float] = mapped_column(Float, nullable=False)
    p_value: Mapped[float] = mapped_column(Float, nullable=False)
    is_significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    test_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    test_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    adf_stationary_cause: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    adf_stationary_effect: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_causality_vars", "cause_variable", "effect_variable"),
    )

    def __repr__(self) -> str:
        sig = "SIG" if self.is_significant else "ns"
        return f"<Causality {self.cause_variable}->{self.effect_variable} lag={self.lag_hours}h p={self.p_value:.4f} {sig}>"


class Advisory(Base):
    """AI-generated health advisories."""

    __tablename__ = "advisories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    advisory_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avg_aqi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worst_location: Mapped[str | None] = mapped_column(String(50), nullable=True)
    worst_aqi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forecast_trend: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_used: Mapped[str] = mapped_column(String(50), default="gpt-4o-mini")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Advisory avg_aqi={self.avg_aqi} @ {self.generated_at}>"


# ---------------------------------------------------------------------------
# Data Quality Scores
# ---------------------------------------------------------------------------

class DataQualityScore(Base):
    """Per-source data quality scores."""

    __tablename__ = "data_quality_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_grade: Mapped[str] = mapped_column(String(2), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_dq_source", "source"),
    )

    def __repr__(self) -> str:
        return f"<DataQuality {self.source}: {self.overall_grade}>"

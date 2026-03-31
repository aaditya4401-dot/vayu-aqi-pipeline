"""Vayu storage layer.

Modules:
- db: Database connection manager (PostgreSQL with SQLite fallback)
- models: SQLAlchemy 2.0 ORM models (fact, dim, feature, results tables)
- init_db: Schema initialization, dimension seeding, upsert helpers
"""

from src.storage.db import get_engine, get_session, is_postgres
from src.storage.init_db import (
    create_tables,
    initialize,
    seed_dimensions,
    upsert_aqi_readings,
    upsert_station_measurements,
    upsert_weather_readings,
)
from src.storage.models import (
    AQIReadingRow,
    AnomalyLog,
    Advisory,
    Base,
    CausalityResult,
    DataQualityScore,
    DimPollutant,
    DimStation,
    FeatureStoreRow,
    ForecastRow,
    StationMeasurementRow,
    WeatherReadingRow,
)

__all__ = [
    "get_engine",
    "get_session",
    "is_postgres",
    "create_tables",
    "initialize",
    "seed_dimensions",
    "upsert_aqi_readings",
    "upsert_station_measurements",
    "upsert_weather_readings",
    "Base",
    "DimStation",
    "DimPollutant",
    "WeatherReadingRow",
    "AQIReadingRow",
    "StationMeasurementRow",
    "FeatureStoreRow",
    "AnomalyLog",
    "ForecastRow",
    "CausalityResult",
    "Advisory",
    "DataQualityScore",
]

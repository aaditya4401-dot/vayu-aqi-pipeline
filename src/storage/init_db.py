"""Schema initialization and dimension seeding for the Vayu database.

Creates all tables and seeds dim_stations (7 Delhi NCR locations) and
dim_pollutants. Uses upsert logic so it's safe to re-run (idempotent).

Also provides insert helpers with upsert semantics for weather, AQI,
and station measurement data.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.ingestion.validators import (
    AQIReading,
    DELHI_LOCATIONS,
    StationMeasurement,
    WeatherReading,
)
from src.storage.db import get_engine, get_session, is_postgres
from src.storage.models import (
    AQIReadingRow,
    Base,
    DimPollutant,
    DimStation,
    StationMeasurementRow,
    WeatherReadingRow,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def create_tables() -> None:
    """Create all tables defined in models.py (no-op if they already exist)."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("All tables created (or already exist)")


# ---------------------------------------------------------------------------
# Dimension seeding
# ---------------------------------------------------------------------------

POLLUTANTS = [
    {"code": "pm25",  "name": "PM2.5",               "unit": "ug/m3", "who_guideline": 15.0,
     "description": "Fine particulate matter (<2.5 micrometers)"},
    {"code": "pm10",  "name": "PM10",                 "unit": "ug/m3", "who_guideline": 45.0,
     "description": "Coarse particulate matter (<10 micrometers)"},
    {"code": "no2",   "name": "Nitrogen Dioxide",     "unit": "ug/m3", "who_guideline": 25.0,
     "description": "Traffic and combustion byproduct"},
    {"code": "so2",   "name": "Sulfur Dioxide",       "unit": "ug/m3", "who_guideline": 40.0,
     "description": "Industrial and power plant emissions"},
    {"code": "o3",    "name": "Ozone",                "unit": "ug/m3", "who_guideline": 100.0,
     "description": "Ground-level ozone, photochemical pollutant"},
    {"code": "co",    "name": "Carbon Monoxide",      "unit": "ug/m3", "who_guideline": 4000.0,
     "description": "Incomplete combustion product"},
    {"code": "nh3",   "name": "Ammonia",              "unit": "ug/m3", "who_guideline": None,
     "description": "Agricultural and waste decomposition emissions"},
]


def _upsert_station(session: Session, location_id: str, info: dict) -> None:
    """Insert or update a single station dimension row."""
    existing = session.execute(
        select(DimStation).where(DimStation.location_id == location_id)
    ).scalar_one_or_none()

    if existing:
        existing.name = info["name"]
        existing.zone = info["zone"]
        existing.latitude = info["lat"]
        existing.longitude = info["lon"]
        existing.is_active = True
    else:
        session.add(DimStation(
            location_id=location_id,
            name=info["name"],
            zone=info["zone"],
            latitude=info["lat"],
            longitude=info["lon"],
        ))


def _upsert_pollutant(session: Session, data: dict) -> None:
    """Insert or update a single pollutant dimension row."""
    existing = session.execute(
        select(DimPollutant).where(DimPollutant.code == data["code"])
    ).scalar_one_or_none()

    if existing:
        existing.name = data["name"]
        existing.unit = data["unit"]
        existing.who_guideline = data["who_guideline"]
        existing.description = data["description"]
    else:
        session.add(DimPollutant(**data))


def seed_dimensions() -> None:
    """Seed dim_stations and dim_pollutants with idempotent upsert logic."""
    session = get_session()
    try:
        # Seed stations
        for loc_id, info in DELHI_LOCATIONS.items():
            _upsert_station(session, loc_id, info)
        logger.info("Seeded %d stations", len(DELHI_LOCATIONS))

        # Seed pollutants
        for pollutant in POLLUTANTS:
            _upsert_pollutant(session, pollutant)
        logger.info("Seeded %d pollutants", len(POLLUTANTS))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Upsert helpers for fact tables
# ---------------------------------------------------------------------------

def upsert_weather_readings(readings: list[WeatherReading]) -> int:
    """Insert weather readings with upsert (skip duplicates on location+timestamp+source).

    Args:
        readings: Validated WeatherReading objects from the ingestion layer.

    Returns:
        Number of rows inserted or updated.
    """
    if not readings:
        return 0

    session = get_session()
    count = 0
    try:
        for r in readings:
            existing = session.execute(
                select(WeatherReadingRow).where(
                    WeatherReadingRow.location_id == r.location_id,
                    WeatherReadingRow.timestamp == r.timestamp,
                    WeatherReadingRow.source == r.source,
                )
            ).scalar_one_or_none()

            if existing:
                # Update existing row
                existing.temperature_celsius = r.temperature_celsius
                existing.humidity_percent = r.humidity_percent
                existing.pressure_hpa = r.pressure_hpa
                existing.wind_speed_mps = r.wind_speed_mps
                existing.wind_direction_deg = r.wind_direction_deg
                existing.visibility_m = r.visibility_m
                existing.clouds_percent = r.clouds_percent
                existing.description = r.description
                existing.ingested_at = datetime.utcnow()
            else:
                session.add(WeatherReadingRow(
                    location_id=r.location_id,
                    timestamp=r.timestamp,
                    temperature_celsius=r.temperature_celsius,
                    humidity_percent=r.humidity_percent,
                    pressure_hpa=r.pressure_hpa,
                    wind_speed_mps=r.wind_speed_mps,
                    wind_direction_deg=r.wind_direction_deg,
                    visibility_m=r.visibility_m,
                    clouds_percent=r.clouds_percent,
                    description=r.description,
                    source=r.source,
                ))
            count += 1

        session.commit()
        logger.info("Upserted %d weather readings", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


def upsert_aqi_readings(readings: list[AQIReading]) -> int:
    """Insert AQI readings with upsert (skip duplicates on location+timestamp+source).

    Args:
        readings: Validated AQIReading objects from the ingestion layer.

    Returns:
        Number of rows inserted or updated.
    """
    if not readings:
        return 0

    session = get_session()
    count = 0
    try:
        for r in readings:
            existing = session.execute(
                select(AQIReadingRow).where(
                    AQIReadingRow.location_id == r.location_id,
                    AQIReadingRow.timestamp == r.timestamp,
                    AQIReadingRow.source == r.source,
                )
            ).scalar_one_or_none()

            if existing:
                existing.aqi = r.aqi
                existing.pm25 = r.pm25
                existing.pm10 = r.pm10
                existing.no2 = r.no2
                existing.so2 = r.so2
                existing.o3 = r.o3
                existing.co = r.co
                existing.nh3 = r.nh3
                existing.category = r.category.value if r.category else None
                existing.ingested_at = datetime.utcnow()
            else:
                session.add(AQIReadingRow(
                    location_id=r.location_id,
                    timestamp=r.timestamp,
                    aqi=r.aqi,
                    pm25=r.pm25,
                    pm10=r.pm10,
                    no2=r.no2,
                    so2=r.so2,
                    o3=r.o3,
                    co=r.co,
                    nh3=r.nh3,
                    category=r.category.value if r.category else None,
                    source=r.source,
                ))
            count += 1

        session.commit()
        logger.info("Upserted %d AQI readings", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


def upsert_station_measurements(readings: list[StationMeasurement]) -> int:
    """Insert station measurements with upsert (skip duplicates on station+location+timestamp+source).

    Args:
        readings: Validated StationMeasurement objects from the ingestion layer.

    Returns:
        Number of rows inserted or updated.
    """
    if not readings:
        return 0

    session = get_session()
    count = 0
    try:
        for r in readings:
            existing = session.execute(
                select(StationMeasurementRow).where(
                    StationMeasurementRow.station_id == r.station_id,
                    StationMeasurementRow.location_id == r.location_id,
                    StationMeasurementRow.timestamp == r.timestamp,
                    StationMeasurementRow.source == r.source,
                )
            ).scalar_one_or_none()

            if existing:
                existing.pm25 = r.pm25
                existing.pm10 = r.pm10
                existing.no2 = r.no2
                existing.so2 = r.so2
                existing.o3 = r.o3
                existing.co = r.co
                existing.temperature_celsius = r.temperature_celsius
                existing.humidity_percent = r.humidity_percent
                existing.ingested_at = datetime.utcnow()
            else:
                session.add(StationMeasurementRow(
                    station_id=r.station_id,
                    location_id=r.location_id,
                    timestamp=r.timestamp,
                    pm25=r.pm25,
                    pm10=r.pm10,
                    no2=r.no2,
                    so2=r.so2,
                    o3=r.o3,
                    co=r.co,
                    temperature_celsius=r.temperature_celsius,
                    humidity_percent=r.humidity_percent,
                    source=r.source,
                ))
            count += 1

        session.commit()
        logger.info("Upserted %d station measurements", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def initialize() -> None:
    """Full initialization: create tables + seed dimensions."""
    print("=" * 60)
    print("VAYU DATABASE INITIALIZATION")
    print("=" * 60)

    from src.storage.db import is_postgres
    db_type = "PostgreSQL" if is_postgres() else "SQLite"
    print(f"  Database: {db_type}")

    print("\n  Creating tables...")
    create_tables()
    print("  [OK] Tables created")

    print("\n  Seeding dimensions...")
    seed_dimensions()
    print("  [OK] Dimensions seeded")

    # Verify
    print("\n  Verifying...")
    session = get_session()
    try:
        station_count = session.query(DimStation).count()
        pollutant_count = session.query(DimPollutant).count()
        print(f"  dim_stations:   {station_count} rows")
        print(f"  dim_pollutants: {pollutant_count} rows")

        # List all tables
        from sqlalchemy import inspect
        inspector = inspect(get_engine())
        tables = inspector.get_table_names()
        print(f"\n  Tables in database ({len(tables)}):")
        for t in sorted(tables):
            print(f"    - {t}")
    finally:
        session.close()

    print(f"\n[OK] Database initialized successfully ({db_type})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize()

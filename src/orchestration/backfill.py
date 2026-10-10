"""One-off historical backfill so forecasting, anomaly detection and causality have data.

Usage: python -m src.orchestration.backfill [--days 30]

Loads hourly AQI (OpenWeather), simulated station history, and hourly weather
(Open-Meteo, free and keyless). All writes are idempotent upserts.
"""

import argparse
import asyncio
import logging

from src.ingestion.aqi_ingest import backfill_aqi
from src.ingestion.station_ingest import simulate_backfill
from src.ingestion.weather_ingest import backfill_weather_openmeteo
from src.storage.init_db import (
    initialize,
    upsert_aqi_readings,
    upsert_station_measurements,
    upsert_weather_readings,
)

logger = logging.getLogger(__name__)


async def run_backfill(days: int = 30) -> dict[str, int]:
    """Backfill AQI, station, and weather history for all 7 locations.

    Args:
        days: Number of past days to load.

    Returns:
        Rows upserted per source.
    """
    initialize()
    aqi = upsert_aqi_readings(await backfill_aqi(days=days))
    stations = upsert_station_measurements(simulate_backfill(days=days))
    weather = upsert_weather_readings(await backfill_weather_openmeteo(days=days))
    return {"aqi": aqi, "stations": stations, "weather": weather}


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Backfill historical data for Vayu.")
    parser.add_argument("--days", type=int, default=30, help="Days of history to load (default 30)")
    args = parser.parse_args()
    counts = asyncio.run(run_backfill(args.days))
    print(f"Backfill complete: {counts}")


if __name__ == "__main__":
    main()

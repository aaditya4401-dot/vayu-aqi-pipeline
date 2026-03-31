"""Air quality data ingestion from OpenWeatherMap Air Pollution API.

Fetches current, historical (30-day backfill), and forecast (4-day)
air pollution data for all 7 Delhi NCR monitoring locations.
All pollutant concentrations are returned in μg/m³.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

from src.ingestion.validators import (
    DELHI_LOCATIONS,
    AQIReading,
    owm_aqi_to_reading,
)

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

MAX_RETRIES = 3
BACKOFF_BASE = 2


# ---------------------------------------------------------------------------
# HTTP helper with retry
# ---------------------------------------------------------------------------

async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    description: str = "",
) -> dict:
    """Async GET with 3 retries and exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if attempt == MAX_RETRIES:
                logger.error("Failed after %d retries (%s): %s", MAX_RETRIES, description, exc)
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning(
                "Attempt %d/%d failed (%s): %s — retrying in %ds",
                attempt, MAX_RETRIES, description, exc, wait,
            )
            await asyncio.sleep(wait)
    return {}


# ---------------------------------------------------------------------------
# Current air quality
# ---------------------------------------------------------------------------

async def fetch_current_aqi(
    location_id: str,
    client: Optional[httpx.AsyncClient] = None,
) -> AQIReading:
    """Fetch current air pollution data for a single Delhi NCR location.

    Args:
        location_id: Key from DELHI_LOCATIONS.
        client: Optional shared httpx client.

    Returns:
        Validated AQIReading with Indian AQI scale.
    """
    loc = DELHI_LOCATIONS[location_id]
    params = {
        "lat": loc["lat"],
        "lon": loc["lon"],
        "appid": API_KEY,
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        data = await _fetch_with_retry(
            client, BASE_URL, params,
            description=f"current AQI for {location_id}",
        )
        item = data["list"][0]
        return owm_aqi_to_reading(item, location_id)
    finally:
        if own_client:
            await client.aclose()


async def fetch_all_current_aqi() -> list[AQIReading]:
    """Fetch current air quality for all 7 Delhi NCR locations concurrently."""
    async with httpx.AsyncClient() as client:
        tasks = [fetch_current_aqi(loc_id, client) for loc_id in DELHI_LOCATIONS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    readings: list[AQIReading] = []
    for loc_id, result in zip(DELHI_LOCATIONS, results):
        if isinstance(result, Exception):
            logger.error("Failed to fetch AQI for %s: %s", loc_id, result)
        else:
            readings.append(result)
    return readings


# ---------------------------------------------------------------------------
# Historical air quality (backfill)
# ---------------------------------------------------------------------------

async def fetch_historical_aqi(
    location_id: str,
    start_dt: datetime,
    end_dt: datetime,
    client: Optional[httpx.AsyncClient] = None,
) -> list[AQIReading]:
    """Fetch historical air pollution data using /air_pollution/history endpoint.

    The history endpoint returns hourly data between start and end unix timestamps.
    Free tier supports history back to Nov 27, 2020.

    Args:
        location_id: Key from DELHI_LOCATIONS.
        start_dt: Start of backfill window (UTC).
        end_dt: End of backfill window (UTC).
        client: Optional shared httpx client.

    Returns:
        List of validated AQIReadings.
    """
    loc = DELHI_LOCATIONS[location_id]
    params = {
        "lat": loc["lat"],
        "lon": loc["lon"],
        "start": int(start_dt.timestamp()),
        "end": int(end_dt.timestamp()),
        "appid": API_KEY,
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    readings: list[AQIReading] = []
    try:
        data = await _fetch_with_retry(
            client, f"{BASE_URL}/history", params,
            description=f"historical AQI for {location_id}",
        )
        for item in data.get("list", []):
            try:
                readings.append(owm_aqi_to_reading(item, location_id))
            except Exception as e:
                logger.warning("Skipping invalid AQI entry for %s: %s", location_id, e)
    finally:
        if own_client:
            await client.aclose()

    return readings


async def backfill_aqi(days: int = 30) -> list[AQIReading]:
    """Backfill historical air quality for all locations over the last N days.

    Args:
        days: Number of days to backfill (default 30).

    Returns:
        All collected AQIReadings across locations.
    """
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    all_readings: list[AQIReading] = []

    async with httpx.AsyncClient() as client:
        for loc_id in DELHI_LOCATIONS:
            logger.info("Backfilling AQI for %s (%d days)...", loc_id, days)
            readings = await fetch_historical_aqi(loc_id, start_dt, end_dt, client)
            all_readings.extend(readings)
            logger.info("  → got %d readings for %s", len(readings), loc_id)
            # Small delay to respect rate limits
            await asyncio.sleep(1.1)

    return all_readings


# ---------------------------------------------------------------------------
# AQI Forecast (4-day)
# ---------------------------------------------------------------------------

async def fetch_aqi_forecast(
    location_id: str,
    client: Optional[httpx.AsyncClient] = None,
) -> list[AQIReading]:
    """Fetch 4-day hourly AQI forecast for a single location.

    Args:
        location_id: Key from DELHI_LOCATIONS.
        client: Optional shared httpx client.

    Returns:
        List of forecast AQIReadings.
    """
    loc = DELHI_LOCATIONS[location_id]
    params = {
        "lat": loc["lat"],
        "lon": loc["lon"],
        "appid": API_KEY,
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    readings: list[AQIReading] = []
    try:
        data = await _fetch_with_retry(
            client, f"{BASE_URL}/forecast", params,
            description=f"AQI forecast for {location_id}",
        )
        for item in data.get("list", []):
            try:
                reading = owm_aqi_to_reading(item, location_id)
                reading.source = "openweathermap_forecast"
                readings.append(reading)
            except Exception as e:
                logger.warning("Skipping invalid forecast entry for %s: %s", location_id, e)
    finally:
        if own_client:
            await client.aclose()

    return readings


async def fetch_all_aqi_forecasts() -> list[AQIReading]:
    """Fetch 4-day AQI forecast for all 7 locations concurrently."""
    async with httpx.AsyncClient() as client:
        tasks = [fetch_aqi_forecast(loc_id, client) for loc_id in DELHI_LOCATIONS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    readings: list[AQIReading] = []
    for loc_id, result in zip(DELHI_LOCATIONS, results):
        if isinstance(result, Exception):
            logger.error("Failed to fetch AQI forecast for %s: %s", loc_id, result)
        else:
            readings.extend(result)
    return readings


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

async def _test():
    """Smoke test — fetch current AQI + forecast sample for all locations."""
    from src.ingestion.validators import classify_aqi

    print("=" * 60)
    print("AQI INGESTION TEST - Current")
    print("=" * 60)

    readings = await fetch_all_current_aqi()
    for r in readings:
        loc = DELHI_LOCATIONS[r.location_id]
        print(
            f"  {loc['name']:20s} | AQI {r.aqi:3d} ({r.category.value:12s}) | "
            f"PM2.5 {r.pm25:6.1f} | PM10 {r.pm10:6.1f} | "
            f"NO2 {r.no2:5.1f} | SO2 {r.so2:5.1f} | O3 {r.o3:5.1f}"
        )
    print(f"\n[OK] Current AQI: {len(readings)}/7 locations")

    print("\n" + "=" * 60)
    print("AQI INGESTION TEST - Forecast (4-day)")
    print("=" * 60)

    forecasts = await fetch_all_aqi_forecasts()
    # Show just first and last forecast entry per location
    from itertools import groupby
    for loc_id, group in groupby(forecasts, key=lambda r: r.location_id):
        entries = list(group)
        loc = DELHI_LOCATIONS[loc_id]
        if entries:
            first, last = entries[0], entries[-1]
            print(
                f"  {loc['name']:20s} | {len(entries):3d} forecast hours | "
                f"AQI range: {min(e.aqi for e in entries)}-{max(e.aqi for e in entries)}"
            )
    print(f"\n[OK] Forecast: {len(forecasts)} total hourly entries")

    return readings, forecasts


if __name__ == "__main__":
    asyncio.run(_test())

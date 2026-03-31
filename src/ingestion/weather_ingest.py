"""Weather data ingestion from OpenWeatherMap API.

Fetches current and historical weather for all 7 Delhi NCR monitoring locations.
All responses are validated through Pydantic schemas before returning.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

from src.ingestion.validators import (
    DELHI_LOCATIONS,
    WeatherReading,
    owm_weather_to_reading,
)

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://api.openweathermap.org/data/2.5"
API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# Retry config
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


# ---------------------------------------------------------------------------
# Low-level HTTP helper with retry + exponential backoff
# ---------------------------------------------------------------------------

async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    description: str = "",
) -> dict:
    """Make an async GET request with 3 retries and exponential backoff."""
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
    return {}  # unreachable, but keeps type-checker happy


# ---------------------------------------------------------------------------
# Current weather
# ---------------------------------------------------------------------------

async def fetch_current_weather(
    location_id: str,
    client: Optional[httpx.AsyncClient] = None,
) -> WeatherReading:
    """Fetch current weather for a single Delhi NCR location.

    Args:
        location_id: Key from DELHI_LOCATIONS (e.g. "anand_vihar").
        client: Optional shared httpx client. Created internally if not provided.

    Returns:
        Validated WeatherReading.
    """
    loc = DELHI_LOCATIONS[location_id]
    params = {
        "lat": loc["lat"],
        "lon": loc["lon"],
        "appid": API_KEY,
        "units": "metric",
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        data = await _fetch_with_retry(
            client, f"{BASE_URL}/weather", params,
            description=f"current weather for {location_id}",
        )
        return owm_weather_to_reading(data, location_id)
    finally:
        if own_client:
            await client.aclose()


async def fetch_all_current_weather() -> list[WeatherReading]:
    """Fetch current weather for all 7 Delhi NCR locations concurrently."""
    async with httpx.AsyncClient() as client:
        tasks = [
            fetch_current_weather(loc_id, client)
            for loc_id in DELHI_LOCATIONS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    readings: list[WeatherReading] = []
    for loc_id, result in zip(DELHI_LOCATIONS, results):
        if isinstance(result, Exception):
            logger.error("Failed to fetch weather for %s: %s", loc_id, result)
        else:
            readings.append(result)
    return readings


# ---------------------------------------------------------------------------
# Historical weather (backfill)
# ---------------------------------------------------------------------------

async def fetch_historical_weather(
    location_id: str,
    start_dt: datetime,
    end_dt: datetime,
    client: Optional[httpx.AsyncClient] = None,
) -> list[WeatherReading]:
    """Fetch historical weather using OpenWeatherMap History API (hourly via onecall/timemachine).

    The free-tier timemachine endpoint only allows one timestamp per call,
    so we iterate day-by-day.

    Args:
        location_id: Key from DELHI_LOCATIONS.
        start_dt: Start of backfill window (UTC).
        end_dt: End of backfill window (UTC).
        client: Optional shared httpx client.

    Returns:
        List of validated WeatherReadings.
    """
    loc = DELHI_LOCATIONS[location_id]
    readings: list[WeatherReading] = []

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        current = start_dt
        while current <= end_dt:
            unix_ts = int(current.timestamp())
            params = {
                "lat": loc["lat"],
                "lon": loc["lon"],
                "dt": unix_ts,
                "appid": API_KEY,
                "units": "metric",
            }
            try:
                data = await _fetch_with_retry(
                    client,
                    "https://api.openweathermap.org/data/3.0/onecall/timemachine",
                    params,
                    description=f"historical weather {location_id} @ {current.date()}",
                )
                # timemachine returns {"data": [...]} with hourly entries
                for entry in data.get("data", []):
                    try:
                        reading = WeatherReading(
                            location_id=location_id,
                            timestamp=datetime.utcfromtimestamp(entry["dt"]),
                            temperature_celsius=entry.get("temp", 0),
                            humidity_percent=entry.get("humidity", 0),
                            pressure_hpa=entry.get("pressure", 1013),
                            wind_speed_mps=entry.get("wind_speed", 0),
                            wind_direction_deg=entry.get("wind_deg", 0),
                            visibility_m=entry.get("visibility"),
                            clouds_percent=entry.get("clouds"),
                            description=entry.get("weather", [{}])[0].get("description", ""),
                        )
                        readings.append(reading)
                    except Exception as e:
                        logger.warning("Skipping invalid historical entry: %s", e)
            except Exception as e:
                logger.error("Historical fetch failed for %s @ %s: %s", location_id, current.date(), e)

            current += timedelta(days=1)
            # Respect free-tier rate limits
            await asyncio.sleep(1.1)
    finally:
        if own_client:
            await client.aclose()

    return readings


async def backfill_weather(days: int = 30) -> list[WeatherReading]:
    """Backfill historical weather for all locations over the last N days.

    Args:
        days: Number of days to backfill (default 30).

    Returns:
        All collected WeatherReadings across locations.
    """
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    all_readings: list[WeatherReading] = []

    async with httpx.AsyncClient() as client:
        for loc_id in DELHI_LOCATIONS:
            logger.info("Backfilling weather for %s (%d days)...", loc_id, days)
            readings = await fetch_historical_weather(loc_id, start_dt, end_dt, client)
            all_readings.extend(readings)
            logger.info("  → got %d readings for %s", len(readings), loc_id)

    return all_readings


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

async def _test():
    """Quick smoke test — fetch current weather for all locations."""
    print("=" * 60)
    print("WEATHER INGESTION TEST")
    print("=" * 60)

    readings = await fetch_all_current_weather()
    for r in readings:
        loc = DELHI_LOCATIONS[r.location_id]
        nw = "<< NW WIND >>" if r.wind_from_northwest else ""
        print(
            f"  {loc['name']:20s} | {r.temperature_celsius:5.1f} C | "
            f"Hum {r.humidity_percent:.0f}% | Wind {r.wind_speed_mps:.1f} m/s @ {r.wind_direction_deg:.0f} deg | "
            f"Clouds {r.clouds_percent}% | {r.description} {nw}"
        )
    print(f"\n[OK] Fetched {len(readings)}/7 locations successfully")
    return readings


if __name__ == "__main__":
    asyncio.run(_test())

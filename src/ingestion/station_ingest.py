"""Ground-station data ingestion: OpenAQ real data + simulated CPCB sensors.

The simulator generates realistic Delhi pollution patterns including:
- Morning rush hour spike (8-10am IST)
- Evening cooking + traffic spike (6-9pm IST)
- Winter inversion amplification (Nov-Feb)
- Stubble burning season overlay (Oct 15 - Nov 30)
- Diwali fireworks spike
- Weekend vs weekday patterns
"""

import asyncio
import logging
import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

from src.ingestion.validators import (
    DELHI_LOCATIONS,
    StationMeasurement,
)

load_dotenv()
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

# Station-specific baseline PM2.5 (μg/m³) — reflects real-world Delhi variation
STATION_BASELINES: dict[str, dict[str, float]] = {
    "anand_vihar":    {"pm25": 120, "pm10": 220, "no2": 65, "so2": 18, "o3": 25, "co": 1800},
    "ito":            {"pm25": 100, "pm10": 190, "no2": 80, "so2": 15, "o3": 20, "co": 2200},
    "rk_puram":       {"pm25":  90, "pm10": 170, "no2": 55, "so2": 12, "o3": 30, "co": 1500},
    "dwarka_sec8":    {"pm25":  70, "pm10": 140, "no2": 40, "so2": 10, "o3": 35, "co": 1100},
    "igi_airport_t3": {"pm25":  65, "pm10": 130, "no2": 35, "so2":  8, "o3": 40, "co":  900},
    "rohini":         {"pm25": 105, "pm10": 200, "no2": 60, "so2": 20, "o3": 22, "co": 1700},
    "noida_sec62":    {"pm25":  85, "pm10": 165, "no2": 50, "so2": 14, "o3": 28, "co": 1400},
}

# Diwali dates (approximate, for simulation purposes)
DIWALI_DATES: dict[int, str] = {
    2023: "2023-11-12",
    2024: "2024-11-01",
    2025: "2025-10-20",
    2026: "2026-11-08",
}


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _hour_of_day_factor(hour_ist: int) -> float:
    """Diurnal pollution pattern multiplier based on IST hour.

    Models two peaks:
    - Morning rush: 8-10 AM (factor ~1.6)
    - Evening rush + cooking: 6-9 PM (factor ~1.8)
    - Night minimum: 2-5 AM (factor ~0.6)
    - Afternoon dip: 1-3 PM (factor ~0.8)
    """
    # Smooth curve using sum of gaussians
    morning_peak = 1.6 * math.exp(-0.5 * ((hour_ist - 9) / 1.5) ** 2)
    evening_peak = 1.8 * math.exp(-0.5 * ((hour_ist - 20) / 2.0) ** 2)
    night_dip = -0.4 * math.exp(-0.5 * ((hour_ist - 3) / 2.0) ** 2)
    afternoon_dip = -0.2 * math.exp(-0.5 * ((hour_ist - 14) / 1.5) ** 2)

    return 1.0 + morning_peak + evening_peak + night_dip + afternoon_dip


def _seasonal_factor(dt: datetime) -> float:
    """Seasonal multiplier for Delhi pollution.

    Winter (Nov-Feb): pollution trapped by thermal inversion → 1.8-2.5x
    Summer (Apr-Jun): heat disperses pollutants → 0.5-0.7x
    Monsoon (Jul-Sep): rain washes out particulates → 0.3-0.5x
    Post-monsoon (Oct): transition → 1.0-1.3x
    """
    month = dt.month
    if month in (12, 1, 2):
        return 2.2 + 0.3 * math.sin(2 * math.pi * dt.day / 30)
    elif month == 11:
        return 2.0
    elif month == 10:
        return 1.3
    elif month == 3:
        return 1.0
    elif month in (4, 5, 6):
        return 0.6
    elif month in (7, 8, 9):
        return 0.4
    else:
        return 1.0


def _stubble_burning_factor(dt: datetime) -> float:
    """Extra pollution from Punjab crop residue burning (Oct 15 - Nov 30).

    Returns an additive PM2.5 amount (μg/m³), not a multiplier.
    Peak burning is late October to mid-November.
    """
    month, day = dt.month, dt.day
    if month == 10 and day >= 15:
        # Ramp up from Oct 15
        days_in = day - 15
        intensity = min(days_in / 10.0, 1.0)  # peaks after 10 days
        return intensity * 80 * random.uniform(0.6, 1.4)
    elif month == 11:
        if day <= 15:
            return 80 * random.uniform(0.7, 1.3)  # peak
        else:
            # Taper off
            days_left = 30 - day
            intensity = max(days_left / 15.0, 0.1)
            return intensity * 60 * random.uniform(0.5, 1.2)
    return 0.0


def _diwali_factor(dt: datetime) -> float:
    """Additive PM2.5 spike (μg/m³) around Diwali (±3 days).

    Diwali night itself can add 200+ μg/m³ of PM2.5 from fireworks.
    """
    year = dt.year
    diwali_str = DIWALI_DATES.get(year)
    if not diwali_str:
        return 0.0

    diwali = datetime.strptime(diwali_str, "%Y-%m-%d")
    delta_days = abs((dt.date() - diwali.date()).days)

    if delta_days > 3:
        return 0.0

    # Peak on Diwali night, tapering off
    ist_hour = (dt + timedelta(hours=5, minutes=30)).hour
    if delta_days == 0:
        # Diwali day: evening peak from fireworks
        if 18 <= ist_hour <= 23:
            return 250 * random.uniform(0.8, 1.2)
        elif ist_hour < 6:
            return 150 * random.uniform(0.7, 1.1)  # lingering smoke
        else:
            return 50 * random.uniform(0.5, 1.0)
    elif delta_days == 1:
        return 100 * random.uniform(0.5, 1.0)
    elif delta_days == 2:
        return 40 * random.uniform(0.4, 0.8)
    else:
        return 15 * random.uniform(0.3, 0.7)


def _weekend_factor(dt: datetime) -> float:
    """Weekend vs weekday multiplier. Weekends have ~15% less traffic pollution."""
    return 0.85 if dt.weekday() >= 5 else 1.0


def _add_noise(value: float, noise_pct: float = 0.15) -> float:
    """Add gaussian noise to a value. Clamp to non-negative."""
    noisy = value * random.gauss(1.0, noise_pct)
    return max(0.0, noisy)


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

def simulate_station_reading(
    location_id: str,
    dt: datetime,
    seed: Optional[int] = None,
) -> StationMeasurement:
    """Generate a single realistic simulated CPCB sensor reading.

    Combines baseline, diurnal cycle, seasonal pattern, stubble burning,
    Diwali spike, and weekend effects to produce a reading that mirrors
    real Delhi pollution dynamics.

    Args:
        location_id: Key from DELHI_LOCATIONS.
        dt: Timestamp for the reading (UTC).
        seed: Optional random seed for reproducibility.

    Returns:
        Validated StationMeasurement.
    """
    if seed is not None:
        random.seed(seed)

    baselines = STATION_BASELINES[location_id]
    ist_dt = dt + timedelta(hours=5, minutes=30)
    hour_ist = ist_dt.hour

    # Compute multipliers
    diurnal = _hour_of_day_factor(hour_ist)
    seasonal = _seasonal_factor(dt)
    weekend = _weekend_factor(dt)

    # Additive components
    stubble = _stubble_burning_factor(dt)
    diwali = _diwali_factor(dt)

    # PM2.5: baseline × diurnal × seasonal × weekend + stubble + diwali + noise
    pm25 = baselines["pm25"] * diurnal * seasonal * weekend + stubble + diwali
    pm25 = _add_noise(pm25, 0.12)
    pm25 = min(max(pm25, 1.0), 1500.0)

    # PM10 tracks PM2.5 with a ratio (typically PM10 ≈ 1.8-2.2× PM2.5 in Delhi)
    pm10_ratio = random.uniform(1.7, 2.3)
    pm10 = pm25 * pm10_ratio
    pm10 = _add_noise(pm10, 0.10)
    pm10 = min(max(pm10, 2.0), 2000.0)

    # NO2: traffic-driven, peaks with rush hours
    no2 = baselines["no2"] * diurnal * weekend * (seasonal * 0.5 + 0.5)
    no2 = _add_noise(no2, 0.15)

    # SO2: industrial, less diurnal variation
    so2 = baselines["so2"] * (seasonal * 0.6 + 0.4) * random.uniform(0.8, 1.2)
    so2 = _add_noise(so2, 0.20)

    # O3: inversely correlated with NO2 (photochemical), peaks at midday
    o3_diurnal = 1.8 * math.exp(-0.5 * ((hour_ist - 14) / 3.0) ** 2)
    o3 = baselines["o3"] * (0.5 + o3_diurnal) * (1.0 / (seasonal * 0.5 + 0.5))
    o3 = _add_noise(o3, 0.18)

    # CO: traffic + cooking, similar diurnal to PM
    co = baselines["co"] * diurnal * weekend * (seasonal * 0.4 + 0.6)
    co = _add_noise(co, 0.15)

    # Simulated temperature and humidity (rough Delhi ranges)
    temp = _simulate_temperature(dt, hour_ist)
    humidity = _simulate_humidity(dt, hour_ist)

    station_id = f"CPCB_{location_id.upper()}_SIM"

    return StationMeasurement(
        station_id=station_id,
        location_id=location_id,
        timestamp=dt,
        pm25=round(pm25, 1),
        pm10=round(pm10, 1),
        no2=round(no2, 1),
        so2=round(so2, 1),
        o3=round(o3, 1),
        co=round(co, 1),
        temperature_celsius=round(temp, 1),
        humidity_percent=round(humidity, 1),
        source="simulated_cpcb",
    )


def _simulate_temperature(dt: datetime, hour_ist: int) -> float:
    """Rough Delhi temperature model (°C)."""
    month = dt.month
    # Monthly average highs for Delhi
    monthly_avg = {
        1: 14, 2: 17, 3: 23, 4: 30, 5: 35, 6: 36,
        7: 33, 8: 32, 9: 31, 10: 27, 11: 21, 12: 15,
    }
    base = monthly_avg.get(month, 25)
    # Diurnal: warmest at 2-3 PM, coolest at 5-6 AM
    diurnal = 5 * math.sin(math.pi * (hour_ist - 6) / 12) if 6 <= hour_ist <= 18 else -3
    return base + diurnal + random.gauss(0, 1.5)


def _simulate_humidity(dt: datetime, hour_ist: int) -> float:
    """Rough Delhi humidity model (%)."""
    month = dt.month
    monthly_avg = {
        1: 65, 2: 55, 3: 40, 4: 30, 5: 28, 6: 45,
        7: 75, 8: 80, 9: 70, 10: 55, 11: 55, 12: 65,
    }
    base = monthly_avg.get(month, 50)
    # Humidity inversely correlated with temperature within day
    diurnal = -15 * math.sin(math.pi * (hour_ist - 6) / 12) if 6 <= hour_ist <= 18 else 10
    val = base + diurnal + random.gauss(0, 5)
    return max(10, min(100, val))


# ---------------------------------------------------------------------------
# Batch simulation
# ---------------------------------------------------------------------------

def simulate_batch(
    start_dt: datetime,
    end_dt: datetime,
    interval_hours: int = 1,
) -> list[StationMeasurement]:
    """Generate simulated readings for all stations over a time range.

    Args:
        start_dt: Start of simulation window (UTC).
        end_dt: End of simulation window (UTC).
        interval_hours: Hours between readings (default 1).

    Returns:
        List of StationMeasurements for all locations across the time range.
    """
    readings: list[StationMeasurement] = []
    current = start_dt

    while current <= end_dt:
        for loc_id in DELHI_LOCATIONS:
            reading = simulate_station_reading(loc_id, current)
            readings.append(reading)
        current += timedelta(hours=interval_hours)

    logger.info(
        "Simulated %d readings across %d locations (%s to %s)",
        len(readings), len(DELHI_LOCATIONS),
        start_dt.isoformat(), end_dt.isoformat(),
    )
    return readings


def simulate_backfill(days: int = 30) -> list[StationMeasurement]:
    """Generate simulated historical readings for the last N days.

    Args:
        days: Number of days to simulate (default 30).

    Returns:
        Hourly StationMeasurements for all 7 locations.
    """
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    return simulate_batch(start_dt, end_dt, interval_hours=1)


# ---------------------------------------------------------------------------
# OpenAQ — attempt to fetch real Delhi station data
# ---------------------------------------------------------------------------

async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    description: str = "",
) -> dict:
    """Async GET with retry logic."""
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


async def fetch_openaq_delhi(
    limit: int = 100,
) -> list[StationMeasurement]:
    """Fetch recent measurements from OpenAQ v3 API for Delhi-area stations.

    OpenAQ v3 is the current API. We search for locations near Delhi
    and fetch their latest measurements.

    Args:
        limit: Max measurements to fetch per request.

    Returns:
        List of validated StationMeasurements (may be empty if API is unavailable).
    """
    readings: list[StationMeasurement] = []

    # Map OpenAQ parameter names to our schema fields
    param_map = {
        "pm25": "pm25",
        "pm10": "pm10",
        "no2": "no2",
        "so2": "so2",
        "o3": "o3",
        "co": "co",
    }

    openaq_key = os.getenv("OPENAQ_API_KEY", "")
    headers = {"X-API-Key": openaq_key} if openaq_key else {}

    async with httpx.AsyncClient(headers=headers) as client:
        try:
            # Step 1: Find Delhi-area locations via v3 API
            loc_data = await _fetch_with_retry(
                client,
                "https://api.openaq.org/v3/locations",
                params={
                    "coordinates": "28.6139,77.2090",
                    "radius": 25000,  # OpenAQ v3 max
                    "limit": 20,
                },
                description="OpenAQ v3 Delhi locations",
            )

            location_ids = []
            location_coords: dict[int, tuple[float, float]] = {}
            for loc in loc_data.get("results", []):
                loc_id_oaq = loc.get("id")
                if loc_id_oaq:
                    location_ids.append(loc_id_oaq)
                    coords = loc.get("coordinates", {})
                    location_coords[loc_id_oaq] = (
                        coords.get("latitude", 0),
                        coords.get("longitude", 0),
                    )

            # Step 2: Fetch latest measurements for each location
            for oaq_loc_id in location_ids[:10]:  # cap at 10 stations
                try:
                    meas_data = await _fetch_with_retry(
                        client,
                        f"https://api.openaq.org/v3/locations/{oaq_loc_id}/latest",
                        params={},
                        description=f"OpenAQ v3 measurements for location {oaq_loc_id}",
                    )

                    lat, lon = location_coords.get(oaq_loc_id, (28.6, 77.2))
                    our_location_id = _nearest_delhi_location(lat, lon)

                    for meas in meas_data.get("results", []):
                        param_name = meas.get("parameter", {}).get("name", "")
                        if param_name not in param_map:
                            continue

                        ts_str = meas.get("datetime", {}).get("utc", "")
                        if not ts_str:
                            continue

                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        except (ValueError, AttributeError):
                            continue

                        value = meas.get("value", 0)
                        if value is None or value < 0:
                            continue

                        kwargs = {
                            "station_id": f"openaq_{oaq_loc_id}",
                            "location_id": our_location_id,
                            "timestamp": ts,
                            "pm25": 0, "pm10": 0,
                            param_map[param_name]: max(0, float(value)),
                            "source": "openaq",
                        }
                        try:
                            readings.append(StationMeasurement(**kwargs))
                        except Exception as e:
                            logger.debug("Skipping OpenAQ entry: %s", e)

                except Exception as e:
                    logger.debug("Failed to fetch measurements for OpenAQ location %d: %s", oaq_loc_id, e)

                await asyncio.sleep(0.5)  # rate limit courtesy

        except Exception as e:
            logger.warning("OpenAQ fetch failed (non-critical, will use simulator): %s", e)

    logger.info("Fetched %d readings from OpenAQ", len(readings))
    return readings


def _nearest_delhi_location(lat: float, lon: float) -> str:
    """Find the closest Delhi monitoring location to given coordinates."""
    best_id = "ito"  # default to central Delhi
    best_dist = float("inf")
    for loc_id, loc in DELHI_LOCATIONS.items():
        dist = (lat - loc["lat"]) ** 2 + (lon - loc["lon"]) ** 2
        if dist < best_dist:
            best_dist = dist
            best_id = loc_id
    return best_id


# ---------------------------------------------------------------------------
# Combined fetch: try OpenAQ, supplement with simulator
# ---------------------------------------------------------------------------

async def fetch_station_data() -> list[StationMeasurement]:
    """Fetch ground station data: real (OpenAQ) + simulated (CPCB).

    Tries OpenAQ first for real Delhi data, then supplements with
    simulated data to ensure all 7 stations have current readings.

    Returns:
        Combined list of StationMeasurements.
    """
    # Try real data
    real_readings = await fetch_openaq_delhi(limit=100)

    # Always generate current simulated readings for completeness
    now = datetime.utcnow()
    simulated = [
        simulate_station_reading(loc_id, now)
        for loc_id in DELHI_LOCATIONS
    ]

    combined = real_readings + simulated
    logger.info(
        "Station data: %d real (OpenAQ) + %d simulated = %d total",
        len(real_readings), len(simulated), len(combined),
    )
    return combined


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

async def _test():
    """Smoke test — generate current simulated readings + try OpenAQ."""
    print("=" * 60)
    print("STATION INGESTION TEST - Simulated CPCB")
    print("=" * 60)

    now = datetime.utcnow()
    ist_now = now + timedelta(hours=5, minutes=30)
    print(f"  Time: {ist_now.strftime('%Y-%m-%d %H:%M IST')}\n")

    for loc_id in DELHI_LOCATIONS:
        r = simulate_station_reading(loc_id, now)
        loc = DELHI_LOCATIONS[loc_id]
        print(
            f"  {loc['name']:20s} | PM2.5 {r.pm25:6.1f} | PM10 {r.pm10:6.1f} | "
            f"NO2 {r.no2:5.1f} | SO2 {r.so2:4.1f} | O3 {r.o3:5.1f} | "
            f"CO {r.co:6.1f} | {r.temperature_celsius:.0f}C {r.humidity_percent:.0f}%"
        )

    # Seasonal demo — show how values change across months
    print("\n" + "=" * 60)
    print("SEASONAL VARIATION DEMO - Anand Vihar PM2.5 at 9AM IST")
    print("=" * 60)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for m in range(1, 13):
        demo_dt = datetime(2025, m, 15, 3, 30)  # 9 AM IST = 3:30 UTC
        r = simulate_station_reading("anand_vihar", demo_dt, seed=42 + m)
        bar = "#" * int(r.pm25 / 10)
        print(f"  {months[m-1]:3s}: PM2.5 {r.pm25:6.1f} ug/m3 {bar}")

    # Try OpenAQ
    print("\n" + "=" * 60)
    print("OPENAQ TEST - Real Delhi data")
    print("=" * 60)
    openaq_readings = await fetch_openaq_delhi(limit=10)
    if openaq_readings:
        for r in openaq_readings[:5]:
            print(
                f"  {r.station_id:30s} | {r.location_id:15s} | "
                f"PM2.5 {r.pm25:6.1f} | PM10 {r.pm10:6.1f} | {r.source}"
            )
    else:
        print("  [WARN] OpenAQ returned no data (will fall back to simulator)")
    print(f"\n[OK] OpenAQ: {len(openaq_readings)} readings")

    return True


if __name__ == "__main__":
    asyncio.run(_test())

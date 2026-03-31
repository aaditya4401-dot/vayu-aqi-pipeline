"""Pydantic v2 validation schemas for all Vayu data sources.

Enforces type safety, range validation, and unit standardization (μg/m³)
for weather, air quality, and ground station measurements.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DELHI_LOCATIONS: dict[str, dict] = {
    "anand_vihar":    {"name": "Anand Vihar",      "zone": "East Delhi",      "lat": 28.6469, "lon": 77.3164},
    "ito":            {"name": "ITO",               "zone": "Central Delhi",   "lat": 28.6289, "lon": 77.2418},
    "rk_puram":       {"name": "RK Puram",          "zone": "South Delhi",     "lat": 28.5633, "lon": 77.1864},
    "dwarka_sec8":    {"name": "Dwarka Sector 8",   "zone": "West Delhi",      "lat": 28.5709, "lon": 77.0712},
    "igi_airport_t3": {"name": "IGI Airport T3",    "zone": "South-West Delhi","lat": 28.5562, "lon": 77.1000},
    "rohini":         {"name": "Rohini",            "zone": "North-West Delhi","lat": 28.7324, "lon": 77.1198},
    "noida_sec62":    {"name": "Noida Sector 62",   "zone": "NCR",             "lat": 28.6252, "lon": 77.3650},
}


class AQICategory(str, Enum):
    """Indian National AQI categories."""
    GOOD = "Good"                # 0-50
    SATISFACTORY = "Satisfactory"  # 51-100
    MODERATE = "Moderate"          # 101-200
    POOR = "Poor"                  # 201-300
    VERY_POOR = "Very Poor"        # 301-400
    SEVERE = "Severe"              # 401-500


def classify_aqi(aqi: int) -> AQICategory:
    """Map an AQI integer (0-500) to its Indian category."""
    if aqi <= 50:
        return AQICategory.GOOD
    elif aqi <= 100:
        return AQICategory.SATISFACTORY
    elif aqi <= 200:
        return AQICategory.MODERATE
    elif aqi <= 300:
        return AQICategory.POOR
    elif aqi <= 400:
        return AQICategory.VERY_POOR
    else:
        return AQICategory.SEVERE


# ---------------------------------------------------------------------------
# Weather Reading
# ---------------------------------------------------------------------------

class WeatherReading(BaseModel):
    """Validated weather observation for a single location + timestamp."""

    location_id: str
    timestamp: datetime
    temperature_celsius: float = Field(..., ge=-50, le=60)
    humidity_percent: float = Field(..., ge=0, le=100)
    pressure_hpa: float = Field(..., ge=870, le=1085)
    wind_speed_mps: float = Field(..., ge=0, le=120)
    wind_direction_deg: float = Field(..., ge=0, le=360)
    visibility_m: Optional[float] = Field(None, ge=0, le=100_000)
    clouds_percent: Optional[float] = Field(None, ge=0, le=100)
    description: Optional[str] = None
    source: str = "openweathermap"

    @field_validator("location_id")
    @classmethod
    def validate_location(cls, v: str) -> str:
        if v not in DELHI_LOCATIONS:
            raise ValueError(f"Unknown location_id '{v}'. Must be one of {list(DELHI_LOCATIONS.keys())}")
        return v

    @property
    def wind_from_northwest(self) -> bool:
        """True when wind blows from 270°-360° (Punjab crop-smoke direction)."""
        return 270 <= self.wind_direction_deg <= 360


# ---------------------------------------------------------------------------
# Air Quality Reading
# ---------------------------------------------------------------------------

class AQIReading(BaseModel):
    """Validated air quality observation with all pollutant concentrations in μg/m³."""

    location_id: str
    timestamp: datetime
    aqi: int = Field(..., ge=0, le=500)
    pm25: float = Field(..., ge=0, le=1500, description="PM2.5 in μg/m³")
    pm10: float = Field(..., ge=0, le=2000, description="PM10 in μg/m³")
    no2: float = Field(..., ge=0, le=1000, description="NO₂ in μg/m³")
    so2: float = Field(..., ge=0, le=1000, description="SO₂ in μg/m³")
    o3: float = Field(..., ge=0, le=1000, description="O₃ in μg/m³")
    co: float = Field(..., ge=0, le=100_000, description="CO in μg/m³")
    nh3: Optional[float] = Field(None, ge=0, le=500, description="NH₃ in μg/m³")
    category: Optional[AQICategory] = None
    source: str = "openweathermap"

    @field_validator("location_id")
    @classmethod
    def validate_location(cls, v: str) -> str:
        if v not in DELHI_LOCATIONS:
            raise ValueError(f"Unknown location_id '{v}'. Must be one of {list(DELHI_LOCATIONS.keys())}")
        return v

    @model_validator(mode="after")
    def set_category(self) -> "AQIReading":
        """Auto-assign Indian AQI category from numeric AQI."""
        if self.category is None:
            self.category = classify_aqi(self.aqi)
        return self


# ---------------------------------------------------------------------------
# Station / Ground-Level Measurement
# ---------------------------------------------------------------------------

class StationMeasurement(BaseModel):
    """Validated ground-station measurement (real CPCB / simulated sensor)."""

    station_id: str
    location_id: str
    timestamp: datetime
    pm25: float = Field(..., ge=0, le=1500, description="PM2.5 in μg/m³")
    pm10: float = Field(..., ge=0, le=2000, description="PM10 in μg/m³")
    no2: Optional[float] = Field(None, ge=0, le=1000, description="NO₂ in μg/m³")
    so2: Optional[float] = Field(None, ge=0, le=1000, description="SO₂ in μg/m³")
    o3: Optional[float] = Field(None, ge=0, le=1000, description="O₃ in μg/m³")
    co: Optional[float] = Field(None, ge=0, le=100_000, description="CO in μg/m³")
    temperature_celsius: Optional[float] = Field(None, ge=-50, le=60)
    humidity_percent: Optional[float] = Field(None, ge=0, le=100)
    source: str = "simulated_cpcb"

    @field_validator("location_id")
    @classmethod
    def validate_location(cls, v: str) -> str:
        if v not in DELHI_LOCATIONS:
            raise ValueError(f"Unknown location_id '{v}'. Must be one of {list(DELHI_LOCATIONS.keys())}")
        return v


# ---------------------------------------------------------------------------
# OpenWeatherMap API response → validated model helpers
# ---------------------------------------------------------------------------

def owm_weather_to_reading(data: dict, location_id: str) -> WeatherReading:
    """Convert raw OpenWeatherMap /weather or /onecall JSON to a WeatherReading."""
    main = data.get("main", {})
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})
    weather_desc = data.get("weather", [{}])[0].get("description", "")

    return WeatherReading(
        location_id=location_id,
        timestamp=datetime.utcfromtimestamp(data["dt"]),
        temperature_celsius=main["temp"],
        humidity_percent=main["humidity"],
        pressure_hpa=main["pressure"],
        wind_speed_mps=wind.get("speed", 0),
        wind_direction_deg=wind.get("deg", 0),
        visibility_m=data.get("visibility"),
        clouds_percent=clouds.get("all"),
        description=weather_desc,
    )


def owm_aqi_to_reading(item: dict, location_id: str) -> AQIReading:
    """Convert a single item from OpenWeatherMap /air_pollution JSON list to AQIReading.

    OpenWeatherMap returns AQI on a 1-5 scale. We map it to the Indian 0-500 scale
    using PM2.5 as the primary driver.
    """
    components = item["components"]
    pm25 = components.get("pm2_5", 0)

    # Map PM2.5 (μg/m³) to Indian AQI 0-500 using CPCB breakpoints
    aqi = _pm25_to_indian_aqi(pm25)

    return AQIReading(
        location_id=location_id,
        timestamp=datetime.utcfromtimestamp(item["dt"]),
        aqi=aqi,
        pm25=pm25,
        pm10=components.get("pm10", 0),
        no2=components.get("no2", 0),
        so2=components.get("so2", 0),
        o3=components.get("o3", 0),
        co=components.get("co", 0),
        nh3=components.get("nh3"),
    )


def _pm25_to_indian_aqi(pm25: float) -> int:
    """Convert PM2.5 concentration (μg/m³) to Indian AQI using CPCB breakpoints.

    Breakpoints (PM2.5 24-hr avg, μg/m³):
        Good:         0-30    → AQI 0-50
        Satisfactory: 31-60   → AQI 51-100
        Moderate:     61-90   → AQI 101-200
        Poor:         91-120  → AQI 201-300
        Very Poor:    121-250 → AQI 301-400
        Severe:       250+    → AQI 401-500
    """
    breakpoints = [
        (0,   30,  0,   50),
        (31,  60,  51,  100),
        (61,  90,  101, 200),
        (91,  120, 201, 300),
        (121, 250, 301, 400),
        (251, 500, 401, 500),
    ]
    pm25 = max(0, min(pm25, 500))
    for bp_lo, bp_hi, aqi_lo, aqi_hi in breakpoints:
        if pm25 <= bp_hi:
            aqi = ((aqi_hi - aqi_lo) / (bp_hi - bp_lo)) * (pm25 - bp_lo) + aqi_lo
            return int(round(aqi))
    return 500

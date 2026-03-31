"""Vayu data ingestion layer.

Modules:
- weather_ingest: OpenWeatherMap Weather API (current + historical)
- aqi_ingest: OpenWeatherMap Air Pollution API (current + historical + forecast)
- station_ingest: OpenAQ real data + simulated CPCB ground sensors
- validators: Pydantic v2 schemas for all data sources
"""

from src.ingestion.validators import (
    DELHI_LOCATIONS,
    AQICategory,
    AQIReading,
    StationMeasurement,
    WeatherReading,
    classify_aqi,
)

__all__ = [
    "DELHI_LOCATIONS",
    "AQICategory",
    "AQIReading",
    "StationMeasurement",
    "WeatherReading",
    "classify_aqi",
]

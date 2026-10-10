"""Pure helpers for the dashboard: IST display, AQI categories, Delhi season context.

All stored timestamps are UTC. Conversion to IST happens only here, at display time.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from src.ingestion.validators import AQICategory, classify_aqi

IST = ZoneInfo("Asia/Kolkata")

STUBBLE_START = (10, 15)   # Oct 15
STUBBLE_END = (11, 30)     # Nov 30
INVERSION_START = (12, 1)  # Dec 1
INVERSION_END = (2, 15)    # Feb 15

# Muted fills with enough contrast for light text, plus lighter tints for text on dark surfaces.
AQI_FILL: dict[str, str] = {
    "Good": "#2f6b4a",
    "Satisfactory": "#5b7428",
    "Moderate": "#8a6a14",
    "Poor": "#a4551f",
    "Very Poor": "#9a3a33",
    "Severe": "#6b2328",
}
AQI_TEXT: dict[str, str] = {
    "Good": "#6fbf93",
    "Satisfactory": "#a6c35a",
    "Moderate": "#d9b24a",
    "Poor": "#e08a4c",
    "Very Poor": "#e0645a",
    "Severe": "#c4585f",
}
AQI_BANDS: list[tuple[str, int, int]] = [
    ("Good", 0, 50),
    ("Satisfactory", 50, 100),
    ("Moderate", 100, 200),
    ("Poor", 200, 300),
    ("Very Poor", 300, 400),
    ("Severe", 400, 500),
]


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime (matches how timestamps are stored)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_ist(values: pd.Series) -> pd.Series:
    """Convert a UTC timestamp series to naive IST wall-clock time for charts and tables."""
    series = pd.to_datetime(values)
    if series.dt.tz is None:
        series = series.dt.tz_localize("UTC")
    return series.dt.tz_convert(IST).dt.tz_localize(None)


def format_ist(value: object) -> str:
    """Format one UTC timestamp as an IST string such as '09 Oct 2026, 09:30 PM IST'."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(IST).strftime("%d %b %Y, %I:%M %p IST")


def today_ist() -> date:
    """Return today's calendar date in IST."""
    return datetime.now(IST).date()


def aqi_category(aqi: float) -> str:
    """Return the Indian AQI category name for an AQI value."""
    return classify_aqi(int(round(max(0, min(500, aqi))))).value


def aqi_fill(aqi: float) -> str:
    """Return the card fill colour for an AQI value."""
    return AQI_FILL[aqi_category(aqi)]


def aqi_text_color(aqi: float) -> str:
    """Return the text colour (readable on dark surfaces) for an AQI value."""
    return AQI_TEXT[aqi_category(aqi)]


def season_context(today: date) -> tuple[str, str]:
    """Describe the Delhi pollution season for a date.

    Stubble burning runs Oct 15 - Nov 30 and winter inversion runs Dec 1 - Feb 15.

    Args:
        today: Calendar date (IST).

    Returns:
        Tuple of (headline, detail) for the season banner.
    """
    md = (today.month, today.day)
    if STUBBLE_START <= md <= STUBBLE_END:
        return (
            "Stubble burning season",
            "Oct 15 to Nov 30. North-west winds (270 to 360 degrees) carry crop smoke from Punjab.",
        )
    if md >= INVERSION_START or md <= INVERSION_END:
        return (
            "Winter inversion period",
            "Dec 1 to Feb 15. Cold, still air traps pollutants close to the ground.",
        )
    start = date(today.year, *STUBBLE_START)
    days_to_stubble = (start - today).days
    if 0 < days_to_stubble <= 30:
        return (
            f"Stubble burning season starts in {days_to_stubble} days",
            "Expect higher PM2.5 once north-west winds set in after Oct 15.",
        )
    return "Outside peak pollution seasons", "No stubble burning or winter inversion flags are active."


def is_northwest_wind(direction_deg: float) -> bool:
    """True when wind blows from 270 to 360 degrees (the Punjab smoke direction)."""
    return 270 <= direction_deg <= 360


def plain_copy(text: str) -> str:
    """Normalise model-written text for display (swap em dashes for plain hyphens)."""
    return text.replace("—", " - ").replace("–", "-")


__all__ = [
    "AQICategory", "AQI_BANDS", "AQI_FILL", "AQI_TEXT", "IST", "aqi_category", "aqi_fill",
    "aqi_text_color", "format_ist", "is_northwest_wind", "plain_copy", "season_context",
    "to_ist", "today_ist", "utc_now",
]

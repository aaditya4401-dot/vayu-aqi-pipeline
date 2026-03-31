"""AI Diagnostic Agent — LLM-powered health advisory generator.

Reads ALL pipeline signals (anomalies, forecasts, causality insights,
feature store summary, data quality scores) and generates a natural-language
health advisory using OpenAI GPT-4o-mini.

The advisory covers:
- Current AQI status across Delhi NCR zones
- Forecast trend (next 24 hours)
- Anomaly alerts with station context
- Contributing factors (wind, stubble, inversion)
- Health recommendations by population group
- Data quality transparency
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import openai
from dotenv import load_dotenv
from sqlalchemy import desc, func, select, text

from src.ingestion.validators import DELHI_LOCATIONS, classify_aqi
from src.storage.db import get_session
from src.storage.models import (
    Advisory,
    AnomalyLog,
    AQIReadingRow,
    CausalityResult,
    DataQualityScore,
    FeatureStoreRow,
    ForecastRow,
    StationMeasurementRow,
    WeatherReadingRow,
)

load_dotenv()
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
BACKOFF_BASE = 2


# ---------------------------------------------------------------------------
# Signal gathering — query each table for latest data
# ---------------------------------------------------------------------------

def _gather_current_aqi() -> dict:
    """Gather latest AQI readings per location."""
    session = get_session()
    try:
        results = {}
        for loc_id, info in DELHI_LOCATIONS.items():
            row = session.execute(
                select(AQIReadingRow)
                .where(AQIReadingRow.location_id == loc_id)
                .order_by(desc(AQIReadingRow.timestamp))
                .limit(1)
            ).scalar_one_or_none()
            if row:
                results[loc_id] = {
                    "name": info["name"],
                    "zone": info["zone"],
                    "aqi": row.aqi,
                    "category": classify_aqi(row.aqi).value,
                    "pm25": row.pm25,
                    "pm10": row.pm10,
                    "no2": row.no2,
                    "so2": row.so2,
                    "o3": row.o3,
                    "co": row.co,
                    "timestamp": row.timestamp.isoformat(),
                }
        return results
    finally:
        session.close()


def _gather_current_weather() -> dict:
    """Gather latest weather per location."""
    session = get_session()
    try:
        results = {}
        for loc_id, info in DELHI_LOCATIONS.items():
            row = session.execute(
                select(WeatherReadingRow)
                .where(WeatherReadingRow.location_id == loc_id)
                .order_by(desc(WeatherReadingRow.timestamp))
                .limit(1)
            ).scalar_one_or_none()
            if row:
                nw = 270 <= row.wind_direction_deg <= 360
                results[loc_id] = {
                    "name": info["name"],
                    "temp_c": row.temperature_celsius,
                    "humidity": row.humidity_percent,
                    "wind_speed_mps": row.wind_speed_mps,
                    "wind_dir_deg": row.wind_direction_deg,
                    "wind_from_northwest": nw,
                    "visibility_m": row.visibility_m,
                }
        return results
    finally:
        session.close()


def _gather_station_data() -> dict:
    """Gather latest station measurements per location."""
    session = get_session()
    try:
        results = {}
        for loc_id, info in DELHI_LOCATIONS.items():
            row = session.execute(
                select(StationMeasurementRow)
                .where(StationMeasurementRow.location_id == loc_id)
                .order_by(desc(StationMeasurementRow.timestamp))
                .limit(1)
            ).scalar_one_or_none()
            if row:
                results[loc_id] = {
                    "name": info["name"],
                    "pm25": row.pm25,
                    "pm10": row.pm10,
                    "no2": row.no2,
                    "temp_c": row.temperature_celsius,
                    "humidity": row.humidity_percent,
                }
        return results
    finally:
        session.close()


def _gather_anomalies(hours: int = 24) -> list[dict]:
    """Gather recent anomalies from the last N hours."""
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        rows = session.execute(
            select(AnomalyLog)
            .where(AnomalyLog.timestamp >= cutoff)
            .order_by(desc(AnomalyLog.timestamp))
            .limit(20)
        ).scalars().all()

        return [
            {
                "location": DELHI_LOCATIONS.get(r.location_id, {}).get("name", r.location_id),
                "metric": r.metric,
                "value": round(r.value, 1),
                "expected": round(r.expected_value, 1) if r.expected_value else None,
                "z_score": r.z_score,
                "severity": r.severity,
                "method": r.method,
                "description": r.description,
            }
            for r in rows
        ]
    finally:
        session.close()


def _gather_forecasts() -> list[dict]:
    """Gather latest forecasts."""
    session = get_session()
    try:
        rows = session.execute(
            select(ForecastRow)
            .order_by(desc(ForecastRow.created_at))
            .limit(14)
        ).scalars().all()

        return [
            {
                "location": DELHI_LOCATIONS.get(r.location_id, {}).get("name", r.location_id),
                "target_time": r.target_timestamp.isoformat(),
                "predicted_aqi": round(r.predicted_aqi),
                "predicted_category": r.predicted_category,
                "actual_aqi": r.actual_aqi,
            }
            for r in rows
        ]
    finally:
        session.close()


def _gather_causality_insights() -> list[dict]:
    """Gather the most significant causality findings."""
    session = get_session()
    try:
        rows = session.execute(
            select(CausalityResult)
            .where(CausalityResult.is_significant == True)
            .order_by(CausalityResult.p_value.asc())
            .limit(10)
        ).scalars().all()

        return [
            {
                "cause": r.cause_variable,
                "effect": r.effect_variable,
                "lag_hours": r.lag_hours,
                "p_value": r.p_value,
                "f_statistic": r.f_statistic,
                "notes": r.notes,
            }
            for r in rows
        ]
    finally:
        session.close()


def _gather_feature_flags() -> dict:
    """Gather current Delhi-specific flag values from feature store."""
    session = get_session()
    flag_features = [
        "is_stubble_season", "is_winter_inversion", "is_diwali_week",
        "wind_from_northwest", "is_extreme_aqi", "is_rush_hour",
        "wind_stagnation_index", "moisture_trap", "ventilation_index",
    ]
    try:
        results = {}
        for feat in flag_features:
            row = session.execute(
                select(FeatureStoreRow.feature_value)
                .where(FeatureStoreRow.feature_name == feat)
                .order_by(desc(FeatureStoreRow.timestamp))
                .limit(1)
            ).scalar_one_or_none()
            results[feat] = row if row is not None else 0.0

        # Also get rolling averages
        for feat in ["aqi_rolling_mean_24h", "pm25_rolling_mean_24h",
                      "aqi_rolling_mean_7d", "pm25_rolling_mean_7d"]:
            row = session.execute(
                select(FeatureStoreRow.feature_value)
                .where(FeatureStoreRow.feature_name == feat)
                .order_by(desc(FeatureStoreRow.timestamp))
                .limit(1)
            ).scalar_one_or_none()
            results[feat] = round(row, 1) if row is not None else None

        return results
    finally:
        session.close()


def _gather_data_quality() -> list[dict]:
    """Gather latest data quality scores."""
    session = get_session()
    try:
        rows = session.execute(
            select(DataQualityScore)
            .order_by(desc(DataQualityScore.scored_at))
            .limit(5)
        ).scalars().all()

        return [
            {
                "source": r.source,
                "completeness": round(r.completeness, 1),
                "freshness_min": round(r.freshness_seconds / 60, 1) if r.freshness_seconds else None,
                "overall_grade": r.overall_grade,
                "details": r.details,
            }
            for r in rows
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_advisory_prompt(signals: dict) -> str:
    """Build a structured prompt with all gathered signals.

    Args:
        signals: Dict with keys for each signal type.

    Returns:
        System + user prompt for the LLM.
    """
    now_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%B %d, %Y %I:%M %p IST")

    # Format AQI data
    aqi_section = "CURRENT AQI READINGS:\n"
    aqi_data = signals.get("aqi", {})
    if aqi_data:
        for loc_id, d in aqi_data.items():
            aqi_section += (
                f"  {d['name']:20s} | AQI {d['aqi']:3d} ({d['category']}) | "
                f"PM2.5: {d['pm25']:.1f} | PM10: {d['pm10']:.1f} | "
                f"NO2: {d['no2']:.1f} | O3: {d['o3']:.1f}\n"
            )
        aqis = [d["aqi"] for d in aqi_data.values()]
        avg_aqi = sum(aqis) / len(aqis) if aqis else 0
        worst_loc = max(aqi_data.values(), key=lambda x: x["aqi"])
        aqi_section += f"\n  NCR Average AQI: {avg_aqi:.0f} ({classify_aqi(int(avg_aqi)).value})\n"
        aqi_section += f"  Worst zone: {worst_loc['name']} at AQI {worst_loc['aqi']}\n"
    else:
        aqi_section += "  No AQI data available.\n"

    # Format weather data
    weather_section = "\nCURRENT WEATHER:\n"
    weather_data = signals.get("weather", {})
    if weather_data:
        for loc_id, d in weather_data.items():
            nw_flag = " [NW WIND - Punjab smoke risk]" if d.get("wind_from_northwest") else ""
            weather_section += (
                f"  {d['name']:20s} | {d['temp_c']:.1f}C | Humidity: {d['humidity']:.0f}% | "
                f"Wind: {d['wind_speed_mps']:.1f} m/s @ {d['wind_dir_deg']:.0f} deg{nw_flag}\n"
            )

    # Format station data
    station_section = "\nGROUND STATION READINGS (CPCB):\n"
    station_data = signals.get("stations", {})
    if station_data:
        for loc_id, d in station_data.items():
            station_section += (
                f"  {d['name']:20s} | PM2.5: {d['pm25']:.1f} | PM10: {d['pm10']:.1f}"
            )
            if d.get("no2"):
                station_section += f" | NO2: {d['no2']:.1f}"
            station_section += "\n"

    # Format anomalies
    anomaly_section = "\nDETECTED ANOMALIES (last 24h):\n"
    anomalies = signals.get("anomalies", [])
    if anomalies:
        for a in anomalies[:10]:
            anomaly_section += (
                f"  [{a['severity'].upper()}] {a['location']}: {a['metric']} = {a['value']} "
                f"(expected ~{a['expected']}, z-score: {a['z_score']}) [{a['method']}]\n"
            )
        if len(anomalies) > 10:
            anomaly_section += f"  ... and {len(anomalies) - 10} more anomalies\n"
    else:
        anomaly_section += "  No anomalies detected in last 24 hours.\n"

    # Format forecasts
    forecast_section = "\nFORECASTS (next 24h):\n"
    forecasts = signals.get("forecasts", [])
    if forecasts:
        for f in forecasts[:7]:
            forecast_section += (
                f"  {f['location']:20s} | Predicted AQI: {f['predicted_aqi']} "
                f"({f['predicted_category']})\n"
            )
    else:
        forecast_section += "  No forecasts available.\n"

    # Format causality insights
    causality_section = "\nGRANGER CAUSALITY INSIGHTS (significant findings):\n"
    causality = signals.get("causality", [])
    if causality:
        for c in causality[:5]:
            causality_section += (
                f"  {c['cause']} -> {c['effect']} at {c['lag_hours']}h lag "
                f"(F={c['f_statistic']:.2f}, p={c['p_value']:.4f})\n"
            )
    else:
        causality_section += "  No significant causality relationships found yet.\n"

    # Format feature flags
    flags_section = "\nDELHI-SPECIFIC CONDITION FLAGS:\n"
    flags = signals.get("flags", {})
    flag_labels = {
        "is_stubble_season": "Stubble burning season (Oct 15 - Nov 30)",
        "is_winter_inversion": "Winter inversion period (Dec 1 - Feb 15)",
        "is_diwali_week": "Diwali week (+/- 3 days)",
        "wind_from_northwest": "Wind from NW (Punjab smoke direction)",
        "is_extreme_aqi": "Extreme AQI (>300)",
        "is_rush_hour": "Rush hour traffic",
    }
    for flag, label in flag_labels.items():
        val = flags.get(flag, 0)
        status = "ACTIVE" if val > 0.5 else "inactive"
        flags_section += f"  {label:50s}: {status}\n"

    rolling = {k: v for k, v in flags.items() if "rolling" in k and v is not None}
    if rolling:
        flags_section += "\n  Rolling averages:\n"
        for k, v in rolling.items():
            flags_section += f"    {k}: {v}\n"

    # Format data quality
    dq_section = "\nDATA QUALITY:\n"
    dq = signals.get("data_quality", [])
    if dq:
        for d in dq:
            fresh = f"{d['freshness_min']:.0f}min" if d.get("freshness_min") else "N/A"
            dq_section += (
                f"  {d['source']:30s} | Grade: {d['overall_grade']} | "
                f"Completeness: {d['completeness']:.0f}% | Freshness: {fresh}\n"
            )

    # Combine all sections
    data_context = (
        f"DELHI AIR QUALITY INTELLIGENCE REPORT - {now_ist}\n"
        f"{'=' * 60}\n\n"
        f"{aqi_section}\n"
        f"{weather_section}\n"
        f"{station_section}\n"
        f"{anomaly_section}\n"
        f"{forecast_section}\n"
        f"{causality_section}\n"
        f"{flags_section}\n"
        f"{dq_section}"
    )

    return data_context


SYSTEM_PROMPT = """You are an AI air quality analyst for Delhi NCR, India. You receive real-time
sensor data, weather data, statistical anomaly detections, Granger causality test results,
forecast predictions, and data quality metrics from the Vayu monitoring pipeline.

Generate a comprehensive health advisory in this exact format:

DELHI AIR QUALITY ADVISORY - [Date]

CURRENT STATUS:
[Summarize current AQI across zones, identify the worst zone, name the primary pollutant,
compare to WHO guidelines]

FORECAST:
[What does the model predict for the next 24 hours? Reference Granger causality findings
to explain WHY — e.g., "wind speed decline leads AQI deterioration by ~4 hours"]

ANOMALY ALERT:
[Highlight any anomalies detected by the statistical methods. Mention the detection method
(Z-score, IQR, STL decomposition) and severity. If no anomalies, note that conditions are normal]

CONTRIBUTING FACTORS:
[Analyze weather conditions: wind direction (NW = Punjab smoke), temperature inversion risk,
humidity trapping, stagnation index. Reference the Delhi-specific flags: stubble season,
winter inversion, Diwali. Use the causality insights to connect weather to pollution]

HEALTH ADVISORY:
- Sensitive groups: [specific advice]
- General population: [specific advice]
- Schools: [specific advice]
- Best time for outdoor activity: [based on diurnal patterns]

DATA QUALITY:
[Report on data source grades and any gaps or issues]

Be specific with numbers. Reference actual values from the data. Keep it actionable.
Write in a professional but accessible tone. Use the Indian AQI scale categories."""


# ---------------------------------------------------------------------------
# LLM call with retry
# ---------------------------------------------------------------------------

def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI GPT-4o-mini with retry logic.

    Args:
        system_prompt: System instructions.
        user_prompt: Data context + question.

    Returns:
        Generated advisory text.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=2000,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error("OpenAI call failed after %d retries: %s", MAX_RETRIES, exc)
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning(
                "OpenAI attempt %d/%d failed: %s — retrying in %ds",
                attempt, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    return ""


# ---------------------------------------------------------------------------
# Save advisory
# ---------------------------------------------------------------------------

def save_advisory(
    advisory_text: str,
    aqi_data: dict,
) -> int:
    """Save generated advisory to the advisories table.

    Args:
        advisory_text: Full advisory text from LLM.
        aqi_data: AQI readings used to compute summary fields.

    Returns:
        ID of saved advisory.
    """
    session = get_session()
    try:
        # Compute summary fields
        aqis = [d["aqi"] for d in aqi_data.values()] if aqi_data else []
        avg_aqi = int(sum(aqis) / len(aqis)) if aqis else None
        worst = max(aqi_data.items(), key=lambda x: x[1]["aqi"]) if aqi_data else (None, {})
        worst_loc = worst[0]
        worst_aqi = worst[1].get("aqi") if worst[1] else None

        # Extract a summary (first 2 lines of advisory)
        lines = advisory_text.strip().split("\n")
        summary = " ".join(lines[:3])[:500]

        advisory = Advisory(
            advisory_text=advisory_text,
            summary=summary,
            avg_aqi=avg_aqi,
            worst_location=worst_loc,
            worst_aqi=worst_aqi,
            model_used=MODEL,
        )
        session.add(advisory)
        session.commit()
        advisory_id = advisory.id
        logger.info("Saved advisory #%d (avg AQI: %s)", advisory_id, avg_aqi)
        return advisory_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def gather_all_signals() -> dict:
    """Gather all pipeline signals from the database.

    Returns:
        Dict with keys: aqi, weather, stations, anomalies, forecasts,
        causality, flags, data_quality.
    """
    logger.info("Gathering signals from all pipeline tables...")
    signals = {
        "aqi": _gather_current_aqi(),
        "weather": _gather_current_weather(),
        "stations": _gather_station_data(),
        "anomalies": _gather_anomalies(hours=24),
        "forecasts": _gather_forecasts(),
        "causality": _gather_causality_insights(),
        "flags": _gather_feature_flags(),
        "data_quality": _gather_data_quality(),
    }
    logger.info(
        "Signals gathered: %d AQI, %d weather, %d stations, %d anomalies, "
        "%d forecasts, %d causality, %d flags, %d DQ scores",
        len(signals["aqi"]), len(signals["weather"]), len(signals["stations"]),
        len(signals["anomalies"]), len(signals["forecasts"]),
        len(signals["causality"]), len(signals["flags"]),
        len(signals["data_quality"]),
    )
    return signals


def generate_advisory() -> tuple[str, int]:
    """Full advisory pipeline: gather signals, build prompt, call LLM, save.

    Returns:
        Tuple of (advisory_text, advisory_id).
    """
    signals = gather_all_signals()
    prompt = build_advisory_prompt(signals)

    logger.info("Calling %s for advisory generation...", MODEL)
    advisory_text = call_llm(SYSTEM_PROMPT, prompt)

    advisory_id = save_advisory(advisory_text, signals["aqi"])

    return advisory_text, advisory_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 70)
    print("  VAYU AI DIAGNOSTIC AGENT")
    print("=" * 70)

    advisory_text, advisory_id = generate_advisory()

    print(f"\n  Advisory #{advisory_id} generated successfully.\n")
    print("-" * 70)
    print(advisory_text)
    print("-" * 70)
    print(f"\n[OK] Advisory saved to database (id={advisory_id})")

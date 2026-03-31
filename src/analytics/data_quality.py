"""Data quality scoring for the Vayu pipeline.

Three dimensions:
1. Completeness: % non-null values per source per pollutant
2. Freshness: time since last reading per station (staleness detection)
3. Consistency: cross-source validation (OpenWeatherMap vs ground station agreement)

Overall grade per source: A (>95%), B (85-95%), C (70-85%), D (50-70%), F (<50%).
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from src.ingestion.validators import DELHI_LOCATIONS
from src.storage.db import get_session
from src.storage.models import (
    AQIReadingRow,
    DataQualityScore,
    StationMeasurementRow,
    WeatherReadingRow,
)

logger = logging.getLogger(__name__)


def _grade_from_score(score: float) -> str:
    """Convert a 0-100 score to a letter grade."""
    if score >= 95:
        return "A"
    elif score >= 85:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 50:
        return "D"
    else:
        return "F"


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def score_completeness() -> dict[str, dict]:
    """Score data completeness per source.

    Checks % of non-null values across key fields.

    Returns:
        Dict mapping source name to completeness details.
    """
    session = get_session()
    results = {}

    try:
        # Weather completeness
        w_total = session.query(func.count(WeatherReadingRow.id)).scalar() or 0
        if w_total > 0:
            w_nulls = {
                "temperature": session.query(func.count()).filter(
                    WeatherReadingRow.temperature_celsius.is_(None)).scalar() or 0,
                "humidity": session.query(func.count()).filter(
                    WeatherReadingRow.humidity_percent.is_(None)).scalar() or 0,
                "wind_speed": session.query(func.count()).filter(
                    WeatherReadingRow.wind_speed_mps.is_(None)).scalar() or 0,
                "visibility": session.query(func.count()).filter(
                    WeatherReadingRow.visibility_m.is_(None)).scalar() or 0,
            }
            completeness_pcts = {k: (1 - v / w_total) * 100 for k, v in w_nulls.items()}
            avg_score = np.mean(list(completeness_pcts.values()))
            results["openweathermap_weather"] = {
                "total_rows": w_total,
                "field_completeness": completeness_pcts,
                "avg_completeness": round(avg_score, 1),
                "grade": _grade_from_score(avg_score),
            }

        # AQI completeness
        a_total = session.query(func.count(AQIReadingRow.id)).scalar() or 0
        if a_total > 0:
            a_nulls = {
                "pm25": session.query(func.count()).filter(
                    AQIReadingRow.pm25.is_(None)).scalar() or 0,
                "pm10": session.query(func.count()).filter(
                    AQIReadingRow.pm10.is_(None)).scalar() or 0,
                "no2": session.query(func.count()).filter(
                    AQIReadingRow.no2.is_(None)).scalar() or 0,
                "nh3": session.query(func.count()).filter(
                    AQIReadingRow.nh3.is_(None)).scalar() or 0,
            }
            completeness_pcts = {k: (1 - v / a_total) * 100 for k, v in a_nulls.items()}
            avg_score = np.mean(list(completeness_pcts.values()))
            results["openweathermap_aqi"] = {
                "total_rows": a_total,
                "field_completeness": completeness_pcts,
                "avg_completeness": round(avg_score, 1),
                "grade": _grade_from_score(avg_score),
            }

        # Station completeness
        s_total = session.query(func.count(StationMeasurementRow.id)).scalar() or 0
        if s_total > 0:
            s_nulls = {
                "pm25": session.query(func.count()).filter(
                    StationMeasurementRow.pm25.is_(None)).scalar() or 0,
                "pm10": session.query(func.count()).filter(
                    StationMeasurementRow.pm10.is_(None)).scalar() or 0,
                "no2": session.query(func.count()).filter(
                    StationMeasurementRow.no2.is_(None)).scalar() or 0,
                "temperature": session.query(func.count()).filter(
                    StationMeasurementRow.temperature_celsius.is_(None)).scalar() or 0,
            }
            completeness_pcts = {k: (1 - v / s_total) * 100 for k, v in s_nulls.items()}
            avg_score = np.mean(list(completeness_pcts.values()))
            results["ground_stations"] = {
                "total_rows": s_total,
                "field_completeness": completeness_pcts,
                "avg_completeness": round(avg_score, 1),
                "grade": _grade_from_score(avg_score),
            }

    finally:
        session.close()

    return results


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def score_freshness() -> dict[str, dict]:
    """Score data freshness per source.

    Measures staleness = seconds since last reading.

    Returns:
        Dict mapping source to freshness details.
    """
    session = get_session()
    results = {}
    now = datetime.utcnow()

    try:
        # Weather freshness per location
        weather_latest = {}
        for loc_id in DELHI_LOCATIONS:
            latest = session.query(func.max(WeatherReadingRow.timestamp)).filter(
                WeatherReadingRow.location_id == loc_id
            ).scalar()
            if latest:
                weather_latest[loc_id] = (now - latest).total_seconds()

        if weather_latest:
            avg_staleness = np.mean(list(weather_latest.values()))
            # Grade: A if <1hr, B if <3hr, C if <6hr, D if <24hr, F if >24hr
            freshness_score = max(0, 100 - (avg_staleness / 3600) * 10)
            results["openweathermap_weather"] = {
                "per_station_staleness_sec": {k: round(v) for k, v in weather_latest.items()},
                "avg_staleness_seconds": round(avg_staleness),
                "avg_staleness_minutes": round(avg_staleness / 60, 1),
                "grade": _grade_from_score(min(100, freshness_score)),
            }

        # AQI freshness
        aqi_latest = {}
        for loc_id in DELHI_LOCATIONS:
            latest = session.query(func.max(AQIReadingRow.timestamp)).filter(
                AQIReadingRow.location_id == loc_id
            ).scalar()
            if latest:
                aqi_latest[loc_id] = (now - latest).total_seconds()

        if aqi_latest:
            avg_staleness = np.mean(list(aqi_latest.values()))
            freshness_score = max(0, 100 - (avg_staleness / 3600) * 10)
            results["openweathermap_aqi"] = {
                "per_station_staleness_sec": {k: round(v) for k, v in aqi_latest.items()},
                "avg_staleness_seconds": round(avg_staleness),
                "avg_staleness_minutes": round(avg_staleness / 60, 1),
                "grade": _grade_from_score(min(100, freshness_score)),
            }

        # Station freshness
        station_latest = {}
        for loc_id in DELHI_LOCATIONS:
            latest = session.query(func.max(StationMeasurementRow.timestamp)).filter(
                StationMeasurementRow.location_id == loc_id
            ).scalar()
            if latest:
                station_latest[loc_id] = (now - latest).total_seconds()

        if station_latest:
            avg_staleness = np.mean(list(station_latest.values()))
            freshness_score = max(0, 100 - (avg_staleness / 3600) * 10)
            results["ground_stations"] = {
                "per_station_staleness_sec": {k: round(v) for k, v in station_latest.items()},
                "avg_staleness_seconds": round(avg_staleness),
                "avg_staleness_minutes": round(avg_staleness / 60, 1),
                "grade": _grade_from_score(min(100, freshness_score)),
            }

    finally:
        session.close()

    return results


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

def score_consistency() -> dict:
    """Score cross-source consistency.

    Compares OpenWeatherMap AQI vs ground station PM2.5 for same location+time.
    Lower delta = higher consistency.

    Returns:
        Dict with consistency metrics.
    """
    session = get_session()
    try:
        # Get AQI PM2.5 readings
        aqi_rows = session.execute(
            select(
                AQIReadingRow.location_id,
                AQIReadingRow.timestamp,
                AQIReadingRow.pm25,
            ).order_by(AQIReadingRow.location_id, AQIReadingRow.timestamp)
        ).all()

        # Get station PM2.5 readings
        station_rows = session.execute(
            select(
                StationMeasurementRow.location_id,
                StationMeasurementRow.timestamp,
                StationMeasurementRow.pm25,
            ).order_by(StationMeasurementRow.location_id, StationMeasurementRow.timestamp)
        ).all()
    finally:
        session.close()

    if not aqi_rows or not station_rows:
        return {"status": "insufficient_data", "grade": "N/A"}

    aqi_df = pd.DataFrame(aqi_rows, columns=["location_id", "timestamp", "pm25_aqi"])
    station_df = pd.DataFrame(station_rows, columns=["location_id", "timestamp", "pm25_station"])

    # Align by location and nearest hour
    aqi_df["hour"] = aqi_df["timestamp"].dt.floor("h")
    station_df["hour"] = station_df["timestamp"].dt.floor("h")

    merged = pd.merge(aqi_df, station_df, on=["location_id", "hour"], how="inner",
                      suffixes=("_aqi", "_station"))

    if merged.empty:
        return {"status": "no_overlapping_data", "grade": "N/A"}

    # Compute PM2.5 delta between sources
    merged["pm25_delta"] = abs(merged["pm25_aqi"] - merged["pm25_station"])
    merged["pm25_pct_diff"] = merged["pm25_delta"] / merged[["pm25_aqi", "pm25_station"]].mean(axis=1) * 100

    avg_delta = merged["pm25_delta"].mean()
    avg_pct = merged["pm25_pct_diff"].mean()

    # Grade: A if <10% diff, B if <25%, C if <50%, D if <75%, F if >75%
    consistency_score = max(0, 100 - avg_pct)

    return {
        "status": "ok",
        "matching_records": len(merged),
        "avg_pm25_delta_ugm3": round(avg_delta, 1),
        "avg_pm25_pct_diff": round(avg_pct, 1),
        "consistency_score": round(consistency_score, 1),
        "grade": _grade_from_score(consistency_score),
        "per_location": {
            loc: {
                "avg_delta": round(g["pm25_delta"].mean(), 1),
                "avg_pct_diff": round(g["pm25_pct_diff"].mean(), 1),
            }
            for loc, g in merged.groupby("location_id")
        },
    }


# ---------------------------------------------------------------------------
# Save scores
# ---------------------------------------------------------------------------

def save_quality_scores(
    completeness: dict[str, dict],
    freshness: dict[str, dict],
    consistency: dict,
) -> int:
    """Save data quality scores to the data_quality_scores table.

    Returns:
        Number of score rows saved.
    """
    session = get_session()
    count = 0
    try:
        for source in set(list(completeness.keys()) + list(freshness.keys())):
            comp = completeness.get(source, {})
            fresh = freshness.get(source, {})
            comp_score = comp.get("avg_completeness", 0)
            fresh_seconds = fresh.get("avg_staleness_seconds")

            # Average grades
            grades = [comp.get("grade", "F"), fresh.get("grade", "F")]
            grade_map = {"A": 95, "B": 87, "C": 77, "D": 60, "F": 30}
            avg = np.mean([grade_map.get(g, 30) for g in grades])

            # Factor in consistency if available
            if consistency.get("grade") not in (None, "N/A"):
                avg = np.mean([avg, grade_map.get(consistency["grade"], 30)])

            overall_grade = _grade_from_score(avg)

            details = (
                f"completeness={comp_score:.0f}%, "
                f"freshness={fresh.get('avg_staleness_minutes', 'N/A')}min"
            )

            session.add(DataQualityScore(
                source=source,
                completeness=float(comp_score),
                freshness_seconds=float(fresh_seconds) if fresh_seconds is not None else None,
                consistency=float(consistency["consistency_score"]) if consistency.get("consistency_score") is not None else None,
                overall_grade=overall_grade,
                details=details,
            ))
            count += 1

        session.commit()
        logger.info("Saved %d data quality scores", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_data_quality_pipeline() -> dict:
    """Full data quality pipeline: score all dimensions, save.

    Returns:
        Summary dict with scores per source.
    """
    completeness = score_completeness()
    freshness = score_freshness()
    consistency = score_consistency()

    saved = save_quality_scores(completeness, freshness, consistency)

    return {
        "completeness": completeness,
        "freshness": freshness,
        "consistency": consistency,
        "scores_saved": saved,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("DATA QUALITY SCORING")
    print("=" * 60)

    results = run_data_quality_pipeline()

    print("\n  COMPLETENESS:")
    for source, data in results["completeness"].items():
        print(f"    {source:30s} | Grade: {data['grade']} | Avg: {data['avg_completeness']:.0f}% | Rows: {data['total_rows']}")
        for field, pct in data["field_completeness"].items():
            print(f"      {field:20s}: {pct:.0f}%")

    print("\n  FRESHNESS:")
    for source, data in results["freshness"].items():
        print(f"    {source:30s} | Grade: {data['grade']} | Staleness: {data['avg_staleness_minutes']:.0f} min")

    print("\n  CONSISTENCY:")
    con = results["consistency"]
    if con.get("status") == "ok":
        print(f"    Grade: {con['grade']} | PM2.5 avg delta: {con['avg_pm25_delta_ugm3']} ug/m3 | Pct diff: {con['avg_pm25_pct_diff']:.0f}%")
    else:
        print(f"    Status: {con.get('status', 'N/A')}")

    print(f"\n  Scores saved: {results['scores_saved']}")
    print(f"\n[OK] Data quality scoring complete")

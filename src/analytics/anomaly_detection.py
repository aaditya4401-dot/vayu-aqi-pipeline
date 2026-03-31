"""Anomaly detection on Delhi AQI and PM2.5 data.

Three methods:
- Z-score: Simple deviation from mean per station
- IQR: Robust to Delhi's heavily right-skewed AQI distribution
- STL decomposition: Seasonal-aware — separates daily/weekly cycles from genuine anomalies

Severity levels adjust by season: PM2.5 of 300 in November is seasonal,
but 300 in July is critical.
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, text

from src.storage.db import get_session
from src.storage.models import AnomalyLog, AQIReadingRow, StationMeasurementRow

logger = logging.getLogger(__name__)

# Season-specific sigma thresholds for severity classification
# In winter/stubble season, higher baselines mean we need wider bands
SEASON_SIGMA_MULTIPLIER: dict[str, float] = {
    "winter": 1.4,       # Nov-Feb: pollution naturally high
    "post_monsoon": 1.2, # Oct: transition
    "summer": 1.0,       # Mar-Jun: normal thresholds
    "monsoon": 0.8,      # Jul-Sep: very clean air, smaller deviations matter
}


def _get_season(dt: datetime) -> str:
    """Determine season from datetime."""
    month = dt.month
    if month in (12, 1, 2):
        return "winter"
    elif month == 11:
        return "winter"  # treat Nov as winter for AQI purposes
    elif month == 10:
        return "post_monsoon"
    elif month in (3, 4, 5, 6):
        return "summer"
    else:
        return "monsoon"


def _classify_severity(z_score: float, season: str) -> str:
    """Classify anomaly severity adjusted for season.

    Args:
        z_score: Absolute z-score of the observation.
        season: Current season string.

    Returns:
        Severity level: 'low', 'medium', 'high', or 'critical'.
    """
    multiplier = SEASON_SIGMA_MULTIPLIER.get(season, 1.0)
    adjusted_z = z_score / multiplier

    if adjusted_z >= 3.0:
        return "critical"
    elif adjusted_z >= 2.5:
        return "high"
    elif adjusted_z >= 2.0:
        return "medium"
    else:
        return "low"


# ---------------------------------------------------------------------------
# Z-Score Detection
# ---------------------------------------------------------------------------

def detect_zscore_anomalies(
    df: pd.DataFrame,
    value_col: str = "pm25",
    threshold: float = 2.0,
) -> pd.DataFrame:
    """Detect anomalies using Z-score per station.

    Args:
        df: DataFrame with columns [location_id, timestamp, <value_col>].
        value_col: Column to analyze (default pm25).
        threshold: Z-score threshold for flagging (default 2.0).

    Returns:
        DataFrame of detected anomalies with z_score and severity.
    """
    anomalies = []

    for location_id, group in df.groupby("location_id"):
        values = group[value_col].dropna()
        if len(values) < 5:
            continue

        mean = values.mean()
        std = values.std()
        if std == 0:
            continue

        for _, row in group.iterrows():
            val = row[value_col]
            if pd.isna(val):
                continue
            z = abs(val - mean) / std
            if z >= threshold:
                season = _get_season(row["timestamp"])
                anomalies.append({
                    "location_id": location_id,
                    "timestamp": row["timestamp"],
                    "metric": value_col,
                    "value": val,
                    "expected_value": mean,
                    "z_score": round(z, 2),
                    "method": "z_score",
                    "severity": _classify_severity(z, season),
                    "description": f"{value_col} z-score={z:.2f} (mean={mean:.1f}, std={std:.1f})",
                })

    return pd.DataFrame(anomalies)


# ---------------------------------------------------------------------------
# IQR Detection
# ---------------------------------------------------------------------------

def detect_iqr_anomalies(
    df: pd.DataFrame,
    value_col: str = "pm25",
    iqr_multiplier: float = 1.5,
) -> pd.DataFrame:
    """Detect outliers using IQR method (robust for right-skewed Delhi AQI).

    Args:
        df: DataFrame with columns [location_id, timestamp, <value_col>].
        value_col: Column to analyze.
        iqr_multiplier: Fence width (1.5 = standard, 3.0 = extreme only).

    Returns:
        DataFrame of detected anomalies.
    """
    anomalies = []

    for location_id, group in df.groupby("location_id"):
        values = group[value_col].dropna()
        if len(values) < 5:
            continue

        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        upper_fence = q3 + iqr_multiplier * iqr
        lower_fence = q1 - iqr_multiplier * iqr
        median = values.median()

        for _, row in group.iterrows():
            val = row[value_col]
            if pd.isna(val):
                continue
            if val > upper_fence or val < lower_fence:
                # Approximate z-score for severity classification
                std = values.std()
                z = abs(val - values.mean()) / std if std > 0 else 2.0
                season = _get_season(row["timestamp"])
                direction = "above" if val > upper_fence else "below"
                anomalies.append({
                    "location_id": location_id,
                    "timestamp": row["timestamp"],
                    "metric": value_col,
                    "value": val,
                    "expected_value": median,
                    "z_score": round(z, 2),
                    "method": "iqr",
                    "severity": _classify_severity(z, season),
                    "description": (
                        f"{value_col} {direction} IQR fence "
                        f"(val={val:.1f}, upper={upper_fence:.1f}, lower={lower_fence:.1f})"
                    ),
                })

    return pd.DataFrame(anomalies)


# ---------------------------------------------------------------------------
# STL Decomposition
# ---------------------------------------------------------------------------

def detect_stl_anomalies(
    df: pd.DataFrame,
    value_col: str = "pm25",
    period: int = 24,
    threshold: float = 2.0,
) -> pd.DataFrame:
    """Detect anomalies using STL decomposition on the residual component.

    Separates daily cycle (period=24 for hourly data) so that normal
    morning/evening spikes aren't flagged. Anomalies in the residual
    represent genuinely unusual events.

    Args:
        df: DataFrame with columns [location_id, timestamp, <value_col>],
            sorted by timestamp.
        value_col: Column to decompose.
        period: Seasonal period in observations (24 = daily for hourly data).
        threshold: Z-score threshold on residuals.

    Returns:
        DataFrame of detected anomalies from residual analysis.
    """
    from statsmodels.tsa.seasonal import seasonal_decompose

    anomalies = []

    for location_id, group in df.groupby("location_id"):
        series = group.set_index("timestamp")[value_col].dropna().sort_index()

        # Need at least 2 full periods for decomposition
        if len(series) < period * 2:
            logger.debug(
                "Skipping STL for %s: only %d points (need %d)",
                location_id, len(series), period * 2,
            )
            continue

        try:
            result = seasonal_decompose(series, model="additive", period=period)
            residuals = result.resid.dropna()

            if len(residuals) == 0:
                continue

            resid_mean = residuals.mean()
            resid_std = residuals.std()
            if resid_std == 0:
                continue

            for ts, resid_val in residuals.items():
                z = abs(resid_val - resid_mean) / resid_std
                if z >= threshold:
                    original_val = series.get(ts, np.nan)
                    trend_val = result.trend.get(ts, np.nan)
                    seasonal_val = result.seasonal.get(ts, np.nan)
                    season = _get_season(ts)
                    anomalies.append({
                        "location_id": location_id,
                        "timestamp": ts,
                        "metric": value_col,
                        "value": float(original_val) if not pd.isna(original_val) else 0,
                        "expected_value": float(trend_val + seasonal_val)
                            if not (pd.isna(trend_val) or pd.isna(seasonal_val)) else None,
                        "z_score": round(z, 2),
                        "method": "stl_residual",
                        "severity": _classify_severity(z, season),
                        "description": (
                            f"STL residual anomaly: z={z:.2f}, "
                            f"residual={resid_val:.1f}, trend={trend_val:.1f}"
                        ),
                    })
        except Exception as e:
            logger.warning("STL decomposition failed for %s: %s", location_id, e)

    return pd.DataFrame(anomalies)


# ---------------------------------------------------------------------------
# Save to database
# ---------------------------------------------------------------------------

def save_anomalies(anomalies_df: pd.DataFrame) -> int:
    """Save detected anomalies to the anomaly_log table.

    Args:
        anomalies_df: DataFrame with anomaly detection results.

    Returns:
        Number of anomalies saved.
    """
    if anomalies_df.empty:
        return 0

    session = get_session()
    count = 0
    try:
        for _, row in anomalies_df.iterrows():
            session.add(AnomalyLog(
                location_id=row["location_id"],
                timestamp=row["timestamp"],
                metric=row["metric"],
                value=row["value"],
                expected_value=row.get("expected_value"),
                z_score=row.get("z_score"),
                method=row["method"],
                severity=row["severity"],
                description=row.get("description"),
            ))
            count += 1
        session.commit()
        logger.info("Saved %d anomalies to anomaly_log", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


# ---------------------------------------------------------------------------
# Main runner: load data, run all detectors, save
# ---------------------------------------------------------------------------

def load_aqi_data() -> pd.DataFrame:
    """Load AQI readings from database into a DataFrame."""
    session = get_session()
    try:
        rows = session.execute(
            select(
                AQIReadingRow.location_id,
                AQIReadingRow.timestamp,
                AQIReadingRow.aqi,
                AQIReadingRow.pm25,
                AQIReadingRow.pm10,
            ).order_by(AQIReadingRow.location_id, AQIReadingRow.timestamp)
        ).all()
        return pd.DataFrame(rows, columns=["location_id", "timestamp", "aqi", "pm25", "pm10"])
    finally:
        session.close()


def load_station_data() -> pd.DataFrame:
    """Load station measurements from database into a DataFrame."""
    session = get_session()
    try:
        rows = session.execute(
            select(
                StationMeasurementRow.location_id,
                StationMeasurementRow.timestamp,
                StationMeasurementRow.pm25,
                StationMeasurementRow.pm10,
            ).order_by(StationMeasurementRow.location_id, StationMeasurementRow.timestamp)
        ).all()
        return pd.DataFrame(rows, columns=["location_id", "timestamp", "pm25", "pm10"])
    finally:
        session.close()


def run_anomaly_detection() -> dict[str, int]:
    """Run all anomaly detection methods on available data.

    Returns:
        Dict mapping method name to count of anomalies detected.
    """
    results: dict[str, int] = {}

    # Load data from both sources
    aqi_df = load_aqi_data()
    station_df = load_station_data()
    combined = pd.concat([aqi_df, station_df], ignore_index=True)

    if combined.empty:
        logger.warning("No data available for anomaly detection")
        return results

    logger.info("Running anomaly detection on %d records", len(combined))

    # Z-score on PM2.5
    z_pm25 = detect_zscore_anomalies(combined, "pm25", threshold=2.0)
    results["z_score_pm25"] = len(z_pm25)

    # Z-score on AQI (only from aqi_df which has the column)
    if "aqi" in aqi_df.columns and not aqi_df.empty:
        z_aqi = detect_zscore_anomalies(aqi_df, "aqi", threshold=2.0)
        results["z_score_aqi"] = len(z_aqi)
    else:
        z_aqi = pd.DataFrame()
        results["z_score_aqi"] = 0

    # IQR on PM2.5
    iqr_pm25 = detect_iqr_anomalies(combined, "pm25", iqr_multiplier=1.5)
    results["iqr_pm25"] = len(iqr_pm25)

    # STL on PM2.5 (needs sufficient time series data)
    stl_pm25 = detect_stl_anomalies(combined, "pm25", period=24, threshold=2.0)
    results["stl_pm25"] = len(stl_pm25)

    # Combine and save all anomalies
    all_anomalies = pd.concat([z_pm25, z_aqi, iqr_pm25, stl_pm25], ignore_index=True)
    if not all_anomalies.empty:
        saved = save_anomalies(all_anomalies)
        results["total_saved"] = saved

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("ANOMALY DETECTION")
    print("=" * 60)
    results = run_anomaly_detection()
    for method, count in results.items():
        print(f"  {method:20s}: {count} anomalies")
    print(f"\n[OK] Anomaly detection complete")

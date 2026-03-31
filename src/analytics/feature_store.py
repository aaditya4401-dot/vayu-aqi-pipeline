"""Engineered feature store for the Vayu pipeline.

Five feature categories:
1. Lag features: AQI at T-1, T-2, T-6, T-12, T-24
2. Rolling stats: 6h/12h/24h/7d rolling mean, std for PM2.5 and AQI
3. Rate of change: aqi_delta_1h, pm25_delta_1h
4. Weather interactions: wind_stagnation, moisture_trap, ventilation_index
5. Temporal + Delhi flags: hour, day_of_week, is_rush_hour, is_stubble_season, etc.

Features are saved to the feature_store table with computation timestamps.
Prophet and other models consume directly from this store.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.storage.db import get_session
from src.storage.models import (
    AQIReadingRow,
    FeatureStoreRow,
    StationMeasurementRow,
    WeatherReadingRow,
)

logger = logging.getLogger(__name__)

# Diwali dates for flag computation
DIWALI_DATES = {
    2023: "2023-11-12", 2024: "2024-11-01",
    2025: "2025-10-20", 2026: "2026-11-08",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_data() -> pd.DataFrame:
    """Load and merge weather + AQI + station data aligned by location + hour.

    Returns:
        Merged DataFrame sorted by (location_id, timestamp).
    """
    session = get_session()
    try:
        # Weather
        w_rows = session.execute(
            select(
                WeatherReadingRow.location_id,
                WeatherReadingRow.timestamp,
                WeatherReadingRow.temperature_celsius,
                WeatherReadingRow.humidity_percent,
                WeatherReadingRow.pressure_hpa,
                WeatherReadingRow.wind_speed_mps,
                WeatherReadingRow.wind_direction_deg,
                WeatherReadingRow.visibility_m,
                WeatherReadingRow.clouds_percent,
            ).order_by(WeatherReadingRow.location_id, WeatherReadingRow.timestamp)
        ).all()
        weather = pd.DataFrame(w_rows, columns=[
            "location_id", "timestamp", "temperature_celsius", "humidity_percent",
            "pressure_hpa", "wind_speed_mps", "wind_direction_deg", "visibility_m",
            "clouds_percent",
        ])

        # AQI
        a_rows = session.execute(
            select(
                AQIReadingRow.location_id,
                AQIReadingRow.timestamp,
                AQIReadingRow.aqi,
                AQIReadingRow.pm25,
                AQIReadingRow.pm10,
                AQIReadingRow.no2,
                AQIReadingRow.o3,
            ).order_by(AQIReadingRow.location_id, AQIReadingRow.timestamp)
        ).all()
        aqi = pd.DataFrame(a_rows, columns=[
            "location_id", "timestamp", "aqi", "pm25", "pm10", "no2", "o3",
        ])
    finally:
        session.close()

    if weather.empty and aqi.empty:
        return pd.DataFrame()

    # Truncate to hour and merge
    for df in [weather, aqi]:
        if not df.empty:
            df["hour"] = df["timestamp"].dt.floor("h")

    if not weather.empty and not aqi.empty:
        merged = pd.merge(weather, aqi, on=["location_id", "hour"], how="outer",
                          suffixes=("_w", "_a"))
        merged["timestamp"] = merged["timestamp_w"].fillna(merged["timestamp_a"])
        merged = merged.drop(columns=["timestamp_w", "timestamp_a", "hour"])
    elif not aqi.empty:
        merged = aqi.drop(columns=["hour"], errors="ignore")
    else:
        merged = weather.drop(columns=["hour"], errors="ignore")

    return merged.sort_values(["location_id", "timestamp"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def compute_lag_features(group: pd.DataFrame) -> pd.DataFrame:
    """Compute lag features for a single location's time series.

    Lags: AQI at T-1, T-2, T-6, T-12, T-24 hours.
    """
    for lag in [1, 2, 6, 12, 24]:
        if "aqi" in group.columns:
            group[f"aqi_lag_{lag}h"] = group["aqi"].shift(lag)
        if "pm25" in group.columns:
            group[f"pm25_lag_{lag}h"] = group["pm25"].shift(lag)
    return group


def compute_rolling_features(group: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling statistics for a single location.

    Windows: 6h, 12h, 24h, 168h (7 days) for PM2.5 and AQI.
    """
    for window, label in [(6, "6h"), (12, "12h"), (24, "24h"), (168, "7d")]:
        if "aqi" in group.columns:
            group[f"aqi_rolling_mean_{label}"] = group["aqi"].rolling(window, min_periods=1).mean()
            group[f"aqi_rolling_std_{label}"] = group["aqi"].rolling(window, min_periods=1).std()
        if "pm25" in group.columns:
            group[f"pm25_rolling_mean_{label}"] = group["pm25"].rolling(window, min_periods=1).mean()
            group[f"pm25_rolling_std_{label}"] = group["pm25"].rolling(window, min_periods=1).std()
    return group


def compute_rate_of_change(group: pd.DataFrame) -> pd.DataFrame:
    """Compute rate of change features (delta over 1 hour)."""
    if "aqi" in group.columns:
        group["aqi_delta_1h"] = group["aqi"].diff()
    if "pm25" in group.columns:
        group["pm25_delta_1h"] = group["pm25"].diff()
    return group


def compute_weather_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """Compute weather interaction features.

    - wind_stagnation_index: 1 / (wind_speed + 0.1) — low wind = trapped pollution
    - moisture_trap: humidity * pm25 / 100 — humid air traps particulates
    - ventilation_index: wind_speed * (100 - clouds) / 100 — dispersion capacity
    - inversion_proxy: flags when conditions favor temperature inversion
    """
    if "wind_speed_mps" in df.columns:
        df["wind_stagnation_index"] = 1.0 / (df["wind_speed_mps"] + 0.1)

    if "humidity_percent" in df.columns and "pm25" in df.columns:
        df["moisture_trap"] = df["humidity_percent"] * df["pm25"] / 100.0

    if "wind_speed_mps" in df.columns and "clouds_percent" in df.columns:
        clouds = df["clouds_percent"].fillna(50)
        df["ventilation_index"] = df["wind_speed_mps"] * (100 - clouds) / 100.0

    if "temperature_celsius" in df.columns and "humidity_percent" in df.columns:
        df["inversion_proxy"] = (
            (df["temperature_celsius"] < 15) &
            (df["humidity_percent"] > 70) &
            (df.get("wind_speed_mps", pd.Series(dtype=float)).fillna(5) < 2)
        ).astype(float)

    return df


def compute_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute temporal features from timestamp."""
    ts = df["timestamp"]
    # Use IST for time-of-day features (UTC + 5:30)
    ist = ts + pd.Timedelta(hours=5, minutes=30)

    df["hour_of_day"] = ist.dt.hour.astype(float)
    df["day_of_week"] = ist.dt.dayofweek.astype(float)
    df["is_weekend"] = (ist.dt.dayofweek >= 5).astype(float)
    df["month"] = ist.dt.month.astype(float)

    # Rush hours: 8-10 AM and 5-8 PM IST
    hour = ist.dt.hour
    df["is_rush_hour"] = (
        ((hour >= 8) & (hour <= 10)) | ((hour >= 17) & (hour <= 20))
    ).astype(float)

    # Season encoding
    df["season_winter"] = ist.dt.month.isin([11, 12, 1, 2]).astype(float)
    df["season_monsoon"] = ist.dt.month.isin([7, 8, 9]).astype(float)
    df["season_summer"] = ist.dt.month.isin([4, 5, 6]).astype(float)

    return df


def compute_delhi_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Delhi-specific binary flags.

    - is_stubble_season: Oct 15 - Nov 30 (Punjab crop burning)
    - is_winter_inversion: Dec 1 - Feb 15 (cold traps pollution)
    - is_diwali_week: +/- 3 days around Diwali
    - wind_from_northwest: wind 270-360 deg (Punjab smoke direction)
    - is_extreme_aqi: AQI > 300 (severe category)
    """
    ts = df["timestamp"]

    # Stubble burning season: Oct 15 - Nov 30
    df["is_stubble_season"] = (
        ((ts.dt.month == 10) & (ts.dt.day >= 15)) |
        (ts.dt.month == 11)
    ).astype(float)

    # Winter inversion: Dec 1 - Feb 15
    df["is_winter_inversion"] = (
        (ts.dt.month == 12) |
        (ts.dt.month == 1) |
        ((ts.dt.month == 2) & (ts.dt.day <= 15))
    ).astype(float)

    # Diwali week (+/- 3 days)
    diwali_flag = pd.Series(False, index=df.index)
    for year, date_str in DIWALI_DATES.items():
        diwali = pd.Timestamp(date_str)
        mask = (ts >= diwali - pd.Timedelta(days=3)) & (ts <= diwali + pd.Timedelta(days=3))
        diwali_flag = diwali_flag | mask
    df["is_diwali_week"] = diwali_flag.astype(float)

    # NW wind
    if "wind_direction_deg" in df.columns:
        df["wind_from_northwest"] = (
            (df["wind_direction_deg"] >= 270) & (df["wind_direction_deg"] <= 360)
        ).astype(float)

    # Extreme AQI
    if "aqi" in df.columns:
        df["is_extreme_aqi"] = (df["aqi"] > 300).astype(float)

    return df


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all feature categories on the merged dataset.

    Args:
        df: Merged weather + AQI DataFrame with timestamp and location_id.

    Returns:
        DataFrame with all original columns plus computed features.
    """
    if df.empty:
        return df

    # Per-location features (lag, rolling, rate of change)
    groups = []
    for loc_id, group in df.groupby("location_id"):
        group = group.sort_values("timestamp").copy()
        group = compute_lag_features(group)
        group = compute_rolling_features(group)
        group = compute_rate_of_change(group)
        groups.append(group)
    df = pd.concat(groups, ignore_index=True)

    # Global features
    df = compute_weather_interactions(df)
    df = compute_temporal_features(df)
    df = compute_delhi_flags(df)

    return df


# ---------------------------------------------------------------------------
# Save to feature_store table
# ---------------------------------------------------------------------------

# These are the feature columns we persist (exclude raw data columns)
FEATURE_COLUMNS = [
    # Lag features
    "aqi_lag_1h", "aqi_lag_2h", "aqi_lag_6h", "aqi_lag_12h", "aqi_lag_24h",
    "pm25_lag_1h", "pm25_lag_2h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h",
    # Rolling features
    "aqi_rolling_mean_6h", "aqi_rolling_std_6h",
    "aqi_rolling_mean_12h", "aqi_rolling_std_12h",
    "aqi_rolling_mean_24h", "aqi_rolling_std_24h",
    "aqi_rolling_mean_7d", "aqi_rolling_std_7d",
    "pm25_rolling_mean_6h", "pm25_rolling_std_6h",
    "pm25_rolling_mean_12h", "pm25_rolling_std_12h",
    "pm25_rolling_mean_24h", "pm25_rolling_std_24h",
    "pm25_rolling_mean_7d", "pm25_rolling_std_7d",
    # Rate of change
    "aqi_delta_1h", "pm25_delta_1h",
    # Weather interactions
    "wind_stagnation_index", "moisture_trap", "ventilation_index", "inversion_proxy",
    # Temporal
    "hour_of_day", "day_of_week", "is_weekend", "is_rush_hour", "month",
    "season_winter", "season_monsoon", "season_summer",
    # Delhi flags
    "is_stubble_season", "is_winter_inversion", "is_diwali_week",
    "wind_from_northwest", "is_extreme_aqi",
]


def save_features(df: pd.DataFrame) -> int:
    """Save computed features to the feature_store table (long format).

    Each (location_id, timestamp, feature_name) becomes one row.

    Args:
        df: DataFrame with location_id, timestamp, and feature columns.

    Returns:
        Number of feature rows saved.
    """
    if df.empty:
        return 0

    session = get_session()
    count = 0
    computed_at = datetime.utcnow()

    try:
        for _, row in df.iterrows():
            loc = row["location_id"]
            ts = row["timestamp"]
            for feat_name in FEATURE_COLUMNS:
                if feat_name not in row.index:
                    continue
                val = row[feat_name]
                if pd.isna(val):
                    continue

                # Upsert: update if exists, insert if not
                existing = session.execute(
                    select(FeatureStoreRow).where(
                        FeatureStoreRow.location_id == loc,
                        FeatureStoreRow.timestamp == ts,
                        FeatureStoreRow.feature_name == feat_name,
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.feature_value = float(val)
                    existing.computed_at = computed_at
                else:
                    session.add(FeatureStoreRow(
                        location_id=loc,
                        timestamp=ts,
                        feature_name=feat_name,
                        feature_value=float(val),
                        computed_at=computed_at,
                    ))
                count += 1

            # Batch flush every 500 features
            if count % 500 == 0:
                session.flush()

        session.commit()
        logger.info("Saved %d feature values to feature_store", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_feature_pipeline() -> dict:
    """Full feature pipeline: load data, compute features, save.

    Returns:
        Summary dict with feature counts.
    """
    df = load_all_data()

    if df.empty:
        logger.warning("No data available for feature computation")
        return {"status": "no_data", "features_computed": 0}

    logger.info("Computing features on %d rows x %d locations", len(df),
                df["location_id"].nunique())

    featured = compute_all_features(df)

    # Count how many feature columns have values
    available_features = [c for c in FEATURE_COLUMNS if c in featured.columns]
    non_null_counts = {f: featured[f].notna().sum() for f in available_features}

    saved = save_features(featured)

    return {
        "status": "ok",
        "input_rows": len(df),
        "locations": int(df["location_id"].nunique()),
        "features_available": len(available_features),
        "features_total_catalog": len(FEATURE_COLUMNS),
        "feature_values_saved": saved,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("FEATURE STORE COMPUTATION")
    print("=" * 60)
    summary = run_feature_pipeline()
    for k, v in summary.items():
        print(f"  {k:25s}: {v}")
    print(f"\n[OK] Feature store complete")

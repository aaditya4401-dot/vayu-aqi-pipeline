"""Granger causality testing: weather -> AQI relationships.

Tests whether past values of weather variables improve AQI predictions
beyond AQI's own history. Includes ADF stationarity tests and differencing.

Primary hypotheses:
- wind_speed Granger-causes AQI (low wind -> AQI rises)
- wind_from_northwest Granger-causes PM2.5 (NW = Punjab smoke)
- temperature Granger-causes AQI (winter inversion traps pollutants)
- humidity Granger-causes PM2.5 (moisture traps particulates)
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

from src.storage.db import get_session
from src.storage.models import (
    AQIReadingRow,
    CausalityResult,
    WeatherReadingRow,
)

logger = logging.getLogger(__name__)

# Lags to test (in hours)
TEST_LAGS = [1, 2, 4, 6, 12, 24]

# Variable pairs to test: (cause_variable, effect_variable)
CAUSALITY_PAIRS = [
    ("wind_speed_mps", "aqi"),
    ("wind_speed_mps", "pm25"),
    ("wind_direction_nw", "pm25"),
    ("temperature_celsius", "aqi"),
    ("humidity_percent", "pm25"),
    ("humidity_percent", "aqi"),
    ("pressure_hpa", "aqi"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_weather_aqi_aligned() -> pd.DataFrame:
    """Load weather and AQI data aligned by location + hour.

    Returns:
        DataFrame with weather + AQI columns, indexed by (location_id, timestamp).
    """
    session = get_session()
    try:
        # Load weather
        weather_rows = session.execute(
            select(
                WeatherReadingRow.location_id,
                WeatherReadingRow.timestamp,
                WeatherReadingRow.temperature_celsius,
                WeatherReadingRow.humidity_percent,
                WeatherReadingRow.pressure_hpa,
                WeatherReadingRow.wind_speed_mps,
                WeatherReadingRow.wind_direction_deg,
            ).order_by(WeatherReadingRow.location_id, WeatherReadingRow.timestamp)
        ).all()
        weather_df = pd.DataFrame(weather_rows, columns=[
            "location_id", "timestamp", "temperature_celsius",
            "humidity_percent", "pressure_hpa", "wind_speed_mps", "wind_direction_deg",
        ])

        # Load AQI
        aqi_rows = session.execute(
            select(
                AQIReadingRow.location_id,
                AQIReadingRow.timestamp,
                AQIReadingRow.aqi,
                AQIReadingRow.pm25,
            ).order_by(AQIReadingRow.location_id, AQIReadingRow.timestamp)
        ).all()
        aqi_df = pd.DataFrame(aqi_rows, columns=[
            "location_id", "timestamp", "aqi", "pm25",
        ])
    finally:
        session.close()

    if weather_df.empty or aqi_df.empty:
        return pd.DataFrame()

    # Truncate to hour for alignment
    weather_df["hour"] = weather_df["timestamp"].dt.floor("h")
    aqi_df["hour"] = aqi_df["timestamp"].dt.floor("h")

    # Merge on location + hour
    merged = pd.merge(
        weather_df, aqi_df,
        on=["location_id", "hour"],
        how="inner",
        suffixes=("_weather", "_aqi"),
    )

    # Derive wind_from_northwest as binary
    merged["wind_direction_nw"] = (
        (merged["wind_direction_deg"] >= 270) & (merged["wind_direction_deg"] <= 360)
    ).astype(float)

    # Use the weather timestamp as primary
    merged["timestamp"] = merged["timestamp_weather"]
    merged = merged.drop(columns=["timestamp_weather", "timestamp_aqi", "hour"])

    return merged


# ---------------------------------------------------------------------------
# Stationarity testing
# ---------------------------------------------------------------------------

def test_stationarity(series: pd.Series, significance: float = 0.05) -> tuple[bool, float]:
    """Run Augmented Dickey-Fuller test for stationarity.

    Args:
        series: Time series to test.
        significance: p-value threshold (default 0.05).

    Returns:
        Tuple of (is_stationary, p_value).
    """
    series = series.dropna()
    if len(series) < 20:
        return True, 0.0  # insufficient data, assume stationary

    try:
        result = adfuller(series, autolag="AIC")
        p_value = result[1]
        return p_value < significance, p_value
    except Exception as e:
        logger.warning("ADF test failed: %s", e)
        return True, 0.0


def make_stationary(series: pd.Series, max_diffs: int = 2) -> tuple[pd.Series, int]:
    """Difference the series until stationary (up to max_diffs times).

    Args:
        series: Input time series.
        max_diffs: Maximum differencing order.

    Returns:
        Tuple of (stationary_series, number_of_diffs_applied).
    """
    current = series.dropna()
    for d in range(max_diffs + 1):
        is_stat, p = test_stationarity(current)
        if is_stat:
            return current, d
        current = current.diff().dropna()
    return current, max_diffs


# ---------------------------------------------------------------------------
# Granger causality testing
# ---------------------------------------------------------------------------

def run_granger_test(
    cause_series: pd.Series,
    effect_series: pd.Series,
    max_lag: int,
    cause_name: str = "",
    effect_name: str = "",
) -> list[dict]:
    """Run Granger causality test for a single variable pair.

    Ensures stationarity first, then tests at the specified max_lag.

    Args:
        cause_series: Potential causal variable.
        effect_series: Potential effect variable.
        max_lag: Maximum lag to test (tests all lags up to this).
        cause_name: Name of cause variable for logging.
        effect_name: Name of effect variable for logging.

    Returns:
        List of result dicts, one per lag tested.
    """
    # Align series
    combined = pd.DataFrame({
        "cause": cause_series,
        "effect": effect_series,
    }).dropna()

    if len(combined) < max_lag + 10:
        logger.debug(
            "Insufficient data for Granger test %s->%s at lag %d (have %d rows)",
            cause_name, effect_name, max_lag, len(combined),
        )
        return []

    # Test and enforce stationarity
    cause_stat, cause_diffs = make_stationary(combined["cause"])
    effect_stat, effect_diffs = make_stationary(combined["effect"])
    cause_is_stat, _ = test_stationarity(cause_stat)
    effect_is_stat, _ = test_stationarity(effect_stat)

    # Re-align after differencing
    aligned = pd.DataFrame({
        "effect": effect_stat,
        "cause": cause_stat,
    }).dropna()

    if len(aligned) < max_lag + 10:
        return []

    results = []
    try:
        # grangercausalitytests expects [effect, cause] column order
        test_data = aligned[["effect", "cause"]].values
        gc_results = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)

        for lag in range(1, max_lag + 1):
            if lag not in gc_results:
                continue
            # Extract F-test results (most commonly used)
            f_test = gc_results[lag][0]["ssr_ftest"]
            f_stat = f_test[0]
            p_value = f_test[1]

            results.append({
                "cause_variable": cause_name,
                "effect_variable": effect_name,
                "lag_hours": lag,
                "f_statistic": round(float(f_stat), 4),
                "p_value": round(float(p_value), 6),
                "is_significant": p_value < 0.05,
                "adf_stationary_cause": cause_is_stat,
                "adf_stationary_effect": effect_is_stat,
            })
    except Exception as e:
        logger.warning("Granger test failed for %s->%s: %s", cause_name, effect_name, e)

    return results


def run_all_causality_tests(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run Granger causality tests for all defined variable pairs and lags.

    Args:
        df: Optional pre-loaded aligned weather+AQI DataFrame.
            If None, loads from database.

    Returns:
        DataFrame with all test results.
    """
    if df is None:
        df = load_weather_aqi_aligned()

    if df.empty:
        logger.warning("No aligned weather+AQI data for causality testing")
        return pd.DataFrame()

    all_results = []
    max_lag = max(TEST_LAGS)

    for cause_var, effect_var in CAUSALITY_PAIRS:
        if cause_var not in df.columns or effect_var not in df.columns:
            logger.debug("Skipping %s->%s: column not found", cause_var, effect_var)
            continue

        # Test per location for location-specific effects
        for location_id, group in df.groupby("location_id"):
            group = group.sort_values("timestamp")
            cause = group[cause_var]
            effect = group[effect_var]

            results = run_granger_test(
                cause, effect, max_lag,
                cause_name=cause_var, effect_name=effect_var,
            )
            for r in results:
                r["notes"] = f"location={location_id}"
            all_results.extend(results)

        # Also test across all locations pooled
        pooled = df.sort_values("timestamp")
        results = run_granger_test(
            pooled[cause_var], pooled[effect_var], max_lag,
            cause_name=cause_var, effect_name=effect_var,
        )
        for r in results:
            r["notes"] = "pooled_all_locations"
        all_results.extend(results)

    return pd.DataFrame(all_results)


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_causality_results(results_df: pd.DataFrame) -> int:
    """Save causality test results to causality_results table.

    Args:
        results_df: DataFrame from run_all_causality_tests().

    Returns:
        Number of results saved.
    """
    if results_df.empty:
        return 0

    session = get_session()
    count = 0
    now = datetime.utcnow()
    try:
        for _, row in results_df.iterrows():
            session.add(CausalityResult(
                cause_variable=row["cause_variable"],
                effect_variable=row["effect_variable"],
                lag_hours=row["lag_hours"],
                f_statistic=row["f_statistic"],
                p_value=row["p_value"],
                is_significant=row["is_significant"],
                test_period_start=now,  # placeholder — actual range from data
                test_period_end=now,
                adf_stationary_cause=row.get("adf_stationary_cause"),
                adf_stationary_effect=row.get("adf_stationary_effect"),
                notes=row.get("notes"),
            ))
            count += 1
        session.commit()
        logger.info("Saved %d causality results", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


def run_causality_pipeline() -> dict:
    """Full causality pipeline: load data, test, save.

    Returns:
        Summary dict with counts and significant findings.
    """
    df = load_weather_aqi_aligned()
    results = run_all_causality_tests(df)

    summary: dict = {
        "total_tests": len(results),
        "significant": 0,
        "pairs_tested": 0,
    }

    if results.empty:
        logger.warning("No causality results produced (need more data)")
        return summary

    summary["significant"] = int(results["is_significant"].sum())
    summary["pairs_tested"] = len(results.groupby(["cause_variable", "effect_variable"]))

    saved = save_causality_results(results)
    summary["saved"] = saved

    # Log significant findings
    sig = results[results["is_significant"]]
    if not sig.empty:
        logger.info("Significant Granger causality findings:")
        for _, row in sig.iterrows():
            logger.info(
                "  %s -> %s at lag %dh (F=%.2f, p=%.4f) [%s]",
                row["cause_variable"], row["effect_variable"],
                row["lag_hours"], row["f_statistic"], row["p_value"],
                row.get("notes", ""),
            )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("GRANGER CAUSALITY TESTING")
    print("=" * 60)
    summary = run_causality_pipeline()
    for k, v in summary.items():
        print(f"  {k:20s}: {v}")
    print(f"\n[OK] Causality testing complete")

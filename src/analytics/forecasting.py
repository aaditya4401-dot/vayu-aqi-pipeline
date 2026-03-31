"""AQI forecasting using Prophet with feature store regressors.

Produces 24-hour AQI forecasts per zone. Features consumed from
the feature_store table include wind_speed, temperature, humidity,
and Delhi-specific seasonal flags.

Evaluation: MAPE, RMSE, and AQI category accuracy.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.ingestion.validators import DELHI_LOCATIONS, classify_aqi
from src.storage.db import get_session
from src.storage.models import (
    AQIReadingRow,
    FeatureStoreRow,
    ForecastRow,
    WeatherReadingRow,
)

logger = logging.getLogger(__name__)

FORECAST_HORIZON_HOURS = 24


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_aqi_series() -> pd.DataFrame:
    """Load AQI time series for all locations."""
    session = get_session()
    try:
        rows = session.execute(
            select(
                AQIReadingRow.location_id,
                AQIReadingRow.timestamp,
                AQIReadingRow.aqi,
            ).order_by(AQIReadingRow.location_id, AQIReadingRow.timestamp)
        ).all()
        return pd.DataFrame(rows, columns=["location_id", "timestamp", "aqi"])
    finally:
        session.close()


def _load_regressors() -> pd.DataFrame:
    """Load regressor features from the feature store.

    Pivots from long format (feature_name, feature_value) to wide format.
    """
    regressor_features = [
        "wind_stagnation_index", "moisture_trap", "ventilation_index",
        "is_stubble_season", "is_winter_inversion", "is_rush_hour",
        "season_winter", "season_monsoon",
    ]

    session = get_session()
    try:
        rows = session.execute(
            select(
                FeatureStoreRow.location_id,
                FeatureStoreRow.timestamp,
                FeatureStoreRow.feature_name,
                FeatureStoreRow.feature_value,
            ).where(FeatureStoreRow.feature_name.in_(regressor_features))
            .order_by(FeatureStoreRow.location_id, FeatureStoreRow.timestamp)
        ).all()
        if not rows:
            return pd.DataFrame()
        long_df = pd.DataFrame(rows, columns=[
            "location_id", "timestamp", "feature_name", "feature_value",
        ])
        # Pivot to wide format
        wide = long_df.pivot_table(
            index=["location_id", "timestamp"],
            columns="feature_name",
            values="feature_value",
            aggfunc="first",
        ).reset_index()
        wide.columns.name = None
        return wide
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Prophet model
# ---------------------------------------------------------------------------

def forecast_location(
    aqi_df: pd.DataFrame,
    regressor_df: pd.DataFrame | None,
    location_id: str,
    horizon_hours: int = FORECAST_HORIZON_HOURS,
) -> tuple[pd.DataFrame, dict]:
    """Run Prophet forecast for a single location.

    Args:
        aqi_df: AQI time series (ds, y columns for Prophet).
        regressor_df: Optional regressor features aligned by timestamp.
        location_id: Location identifier for logging.
        horizon_hours: Hours to forecast ahead.

    Returns:
        Tuple of (forecast_df, metrics_dict).
    """
    try:
        from prophet import Prophet
    except ImportError:
        logger.error("Prophet not installed. Install with: pip install prophet")
        return pd.DataFrame(), {}

    loc_data = aqi_df[aqi_df["location_id"] == location_id].copy()
    if len(loc_data) < 10:
        logger.debug("Insufficient data for %s (%d rows), skipping", location_id, len(loc_data))
        return pd.DataFrame(), {}

    # Prophet requires 'ds' and 'y' columns
    prophet_df = loc_data[["timestamp", "aqi"]].rename(columns={"timestamp": "ds", "aqi": "y"})
    prophet_df = prophet_df.sort_values("ds").drop_duplicates(subset="ds")

    # Merge regressors if available
    regressor_cols = []
    if regressor_df is not None and not regressor_df.empty:
        loc_regs = regressor_df[regressor_df["location_id"] == location_id].copy()
        if not loc_regs.empty:
            loc_regs = loc_regs.rename(columns={"timestamp": "ds"})
            available_regs = [c for c in loc_regs.columns if c not in ("location_id", "ds")]
            prophet_df = pd.merge(prophet_df, loc_regs[["ds"] + available_regs],
                                  on="ds", how="left")
            # Fill NaN regressors with 0 (flags) or median
            for col in available_regs:
                if prophet_df[col].isna().all():
                    prophet_df.drop(columns=[col], inplace=True)
                else:
                    prophet_df[col] = prophet_df[col].fillna(prophet_df[col].median())
                    regressor_cols.append(col)

    # Train/test split respecting temporal order
    split_idx = int(len(prophet_df) * 0.8)
    if split_idx < 5:
        split_idx = len(prophet_df) - 1  # use all for training if too small

    train = prophet_df.iloc[:split_idx].copy()
    test = prophet_df.iloc[split_idx:].copy()

    # Build model
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True if len(train) >= 168 else False,  # need 1 week of data
        yearly_seasonality=False,  # typically not enough data
        changepoint_prior_scale=0.05,
    )

    for col in regressor_cols:
        model.add_regressor(col)

    # Suppress Prophet's verbose output
    model.fit(train)

    # Create future dataframe
    future = model.make_future_dataframe(periods=horizon_hours, freq="h")

    # Add regressors to future
    for col in regressor_cols:
        if col in prophet_df.columns:
            merged = pd.merge(future, prophet_df[["ds", col]], on="ds", how="left")
            future[col] = merged[col].fillna(prophet_df[col].median())
        else:
            future[col] = 0

    forecast = model.predict(future)

    # Compute metrics on test set
    metrics = {}
    if len(test) > 0:
        test_forecast = forecast[forecast["ds"].isin(test["ds"])].copy()
        if len(test_forecast) > 0:
            merged_test = pd.merge(test, test_forecast[["ds", "yhat"]], on="ds")
            actual = merged_test["y"].values
            predicted = merged_test["yhat"].values

            # Clamp predictions to valid AQI range
            predicted = np.clip(predicted, 0, 500)

            # MAPE
            nonzero = actual > 0
            if nonzero.sum() > 0:
                metrics["mape"] = float(np.mean(np.abs(
                    (actual[nonzero] - predicted[nonzero]) / actual[nonzero]
                )) * 100)

            # RMSE
            metrics["rmse"] = float(np.sqrt(np.mean((actual - predicted) ** 2)))

            # Category accuracy
            actual_cats = [classify_aqi(int(round(a))).value for a in actual]
            pred_cats = [classify_aqi(int(round(max(0, min(500, p))))).value for p in predicted]
            metrics["category_accuracy"] = float(
                sum(a == p for a, p in zip(actual_cats, pred_cats)) / len(actual_cats) * 100
            )

    # Get the forecast portion (future predictions only)
    last_known = prophet_df["ds"].max()
    future_forecast = forecast[forecast["ds"] > last_known][["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
    future_forecast["location_id"] = location_id
    future_forecast["yhat"] = future_forecast["yhat"].clip(0, 500)

    return future_forecast, metrics


# ---------------------------------------------------------------------------
# Save forecasts
# ---------------------------------------------------------------------------

def save_forecasts(forecast_df: pd.DataFrame) -> int:
    """Save forecast results to the forecasts table.

    Args:
        forecast_df: DataFrame with location_id, ds (target timestamp), yhat.

    Returns:
        Number of forecast rows saved.
    """
    if forecast_df.empty:
        return 0

    session = get_session()
    count = 0
    now = datetime.utcnow()
    try:
        for _, row in forecast_df.iterrows():
            predicted_aqi = int(round(row["yhat"]))
            session.add(ForecastRow(
                location_id=row["location_id"],
                forecast_timestamp=now,
                target_timestamp=row["ds"],
                predicted_aqi=predicted_aqi,
                predicted_category=classify_aqi(max(0, min(500, predicted_aqi))).value,
                model_version="prophet_v1",
            ))
            count += 1
        session.commit()
        logger.info("Saved %d forecast rows", count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run_forecast_pipeline() -> dict:
    """Full forecast pipeline: load data, train Prophet, forecast, save.

    Returns:
        Summary dict with metrics per location.
    """
    aqi_df = _load_aqi_series()
    regressor_df = _load_regressors()

    if aqi_df.empty:
        logger.warning("No AQI data available for forecasting")
        return {"status": "no_data"}

    logger.info("Running Prophet forecasts for %d locations",
                aqi_df["location_id"].nunique())

    all_forecasts = []
    all_metrics: dict[str, dict] = {}

    for location_id in aqi_df["location_id"].unique():
        logger.info("  Forecasting %s...", location_id)
        forecast, metrics = forecast_location(
            aqi_df, regressor_df, location_id,
        )
        if not forecast.empty:
            all_forecasts.append(forecast)
        if metrics:
            all_metrics[location_id] = metrics

    # Combine and save
    if all_forecasts:
        combined = pd.concat(all_forecasts, ignore_index=True)
        saved = save_forecasts(combined)
    else:
        saved = 0

    return {
        "status": "ok",
        "locations_forecasted": len(all_forecasts),
        "forecast_rows_saved": saved,
        "metrics": all_metrics,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("AQI FORECASTING (Prophet)")
    print("=" * 60)
    summary = run_forecast_pipeline()
    print(f"  Status: {summary.get('status')}")
    print(f"  Locations forecasted: {summary.get('locations_forecasted', 0)}")
    print(f"  Rows saved: {summary.get('forecast_rows_saved', 0)}")
    metrics = summary.get("metrics", {})
    if metrics:
        print(f"\n  Metrics per location:")
        for loc, m in metrics.items():
            name = DELHI_LOCATIONS.get(loc, {}).get("name", loc)
            mape = m.get("mape", "N/A")
            rmse = m.get("rmse", "N/A")
            cat_acc = m.get("category_accuracy", "N/A")
            mape_str = f"{mape:.1f}%" if isinstance(mape, float) else mape
            rmse_str = f"{rmse:.1f}" if isinstance(rmse, float) else rmse
            cat_str = f"{cat_acc:.0f}%" if isinstance(cat_acc, float) else cat_acc
            print(f"    {name:20s} | MAPE: {mape_str:>6s} | RMSE: {rmse_str:>6s} | Cat Acc: {cat_str}")
    print(f"\n[OK] Forecasting complete")

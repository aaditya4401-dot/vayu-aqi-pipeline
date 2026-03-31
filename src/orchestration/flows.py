"""Prefect flow definitions for the Vayu pipeline.

Main flow chains all tasks in the correct order:
1. Ingest weather + AQI + stations (concurrent)
2. dbt transformations
3. Feature store computation
4. Anomaly detection + forecasting (concurrent)
5. Granger causality (daily only)
6. Data quality scoring
7. AI health advisory generation

Supports manual trigger and scheduled (hourly) runs.
"""

import logging
from datetime import datetime

from prefect.flows import flow

from src.orchestration.tasks import (
    compute_data_quality,
    compute_feature_store,
    generate_advisory,
    ingest_aqi,
    ingest_stations,
    ingest_weather,
    run_anomaly_detection,
    run_dbt_transforms,
    run_forecasting,
    run_granger_causality,
)

logger = logging.getLogger(__name__)


@flow(
    name="vayu_pipeline",
    log_prints=True,
    retries=0,
)
def vayu_pipeline(run_causality: bool = False) -> dict:
    """Main Vayu pipeline flow.

    Runs the complete data pipeline from ingestion to AI advisory.

    Args:
        run_causality: If True, run Granger causality tests (expensive,
                       normally daily only). Defaults to False.

    Returns:
        Summary dict with results from each stage.
    """
    run_start = datetime.utcnow()
    summary: dict = {"start": run_start.isoformat()}

    print("=" * 60)
    print("  VAYU PIPELINE - Starting full run")
    print("=" * 60)

    # ---------------------------------------------------------------
    # Stage 0: Ensure schema exists
    # ---------------------------------------------------------------
    print("\n[Stage 0] Ensuring database schema...")
    from src.storage.init_db import create_tables, seed_dimensions
    create_tables()
    seed_dimensions()

    # ---------------------------------------------------------------
    # Stage 1: Ingest data (concurrent via .submit())
    # ---------------------------------------------------------------
    print("\n[Stage 1] Ingesting data from 3 sources (concurrent)...")
    weather_future = ingest_weather.submit()
    aqi_future = ingest_aqi.submit()
    stations_future = ingest_stations.submit()

    # Wait for all ingestion to complete
    weather_count = weather_future.result()
    aqi_count = aqi_future.result()
    stations_count = stations_future.result()

    summary["ingestion"] = {
        "weather": weather_count,
        "aqi": aqi_count,
        "stations": stations_count,
    }
    print(f"  Ingestion complete: {weather_count} weather, {aqi_count} AQI, {stations_count} stations")

    # ---------------------------------------------------------------
    # Stage 2: dbt transformations
    # ---------------------------------------------------------------
    print("\n[Stage 2] Running dbt transformations...")
    dbt_ok = run_dbt_transforms()
    summary["dbt"] = dbt_ok
    print(f"  dbt complete: {dbt_ok}")

    # ---------------------------------------------------------------
    # Stage 3: Feature store
    # ---------------------------------------------------------------
    print("\n[Stage 3] Computing feature store...")
    feature_summary = compute_feature_store()
    summary["feature_store"] = feature_summary

    # ---------------------------------------------------------------
    # Stage 4: Anomaly detection + Forecasting (concurrent)
    # ---------------------------------------------------------------
    print("\n[Stage 4] Running anomaly detection + forecasting (concurrent)...")
    anomaly_future = run_anomaly_detection.submit()
    forecast_future = run_forecasting.submit()

    anomaly_results = anomaly_future.result()
    forecast_results = forecast_future.result()

    summary["anomalies"] = anomaly_results
    summary["forecasting"] = forecast_results

    # ---------------------------------------------------------------
    # Stage 5: Granger causality (conditional - daily only)
    # ---------------------------------------------------------------
    if run_causality:
        print("\n[Stage 5] Running Granger causality tests...")
        causality_summary = run_granger_causality()
        summary["causality"] = causality_summary
    else:
        print("\n[Stage 5] Skipping causality (daily-only, use run_causality=True)")
        summary["causality"] = "skipped"

    # ---------------------------------------------------------------
    # Stage 6: Data quality scoring
    # ---------------------------------------------------------------
    print("\n[Stage 6] Computing data quality scores...")
    dq_results = compute_data_quality()
    summary["data_quality"] = dq_results

    # ---------------------------------------------------------------
    # Stage 7: AI advisory generation
    # ---------------------------------------------------------------
    print("\n[Stage 7] Generating AI health advisory...")
    advisory_id = generate_advisory()
    summary["advisory_id"] = advisory_id

    # ---------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------
    run_end = datetime.utcnow()
    duration = (run_end - run_start).total_seconds()
    summary["end"] = run_end.isoformat()
    summary["duration_seconds"] = round(duration, 1)

    print("\n" + "=" * 60)
    print(f"  VAYU PIPELINE - Complete in {duration:.1f}s")
    print("=" * 60)
    print(f"  Weather:    {weather_count} readings")
    print(f"  AQI:        {aqi_count} readings")
    print(f"  Stations:   {stations_count} readings")
    print(f"  dbt:        {'OK' if dbt_ok else 'FAILED'}")
    print(f"  Features:   {feature_summary.get('feature_values_saved', 0)} values")
    print(f"  Anomalies:  {anomaly_results.get('total_saved', 0)} detected")
    print(f"  Forecast:   {forecast_results.get('locations_forecasted', 0)} locations")
    causality_str = summary['causality'] if isinstance(summary['causality'], str) else f"{summary['causality'].get('significant', 0)} significant"
    print(f"  Causality:  {causality_str}")
    print(f"  DQ scores:  {dq_results.get('scores_saved', 0)} saved")
    print(f"  Advisory:   #{advisory_id}")
    print("=" * 60)

    return summary


@flow(
    name="vayu_pipeline_daily",
    log_prints=True,
)
def vayu_pipeline_daily() -> dict:
    """Daily pipeline run that includes Granger causality testing."""
    return vayu_pipeline(run_causality=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    run_causality = "--causality" in sys.argv
    vayu_pipeline(run_causality=run_causality)

"""Prefect task definitions for every step in the Vayu pipeline.

Each task wraps one pipeline component with retries, logging, and
clear return values for downstream dependency tracking.
"""

import asyncio
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from prefect.tasks import task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ingestion tasks (run concurrently)
# ---------------------------------------------------------------------------

@task(name="ingest_weather", retries=2, retry_delay_seconds=30, log_prints=True)
def ingest_weather() -> int:
    """Fetch current weather for all 7 Delhi NCR locations."""
    from src.ingestion.weather_ingest import fetch_all_current_weather
    from src.storage.init_db import upsert_weather_readings

    readings = asyncio.run(fetch_all_current_weather())
    count = upsert_weather_readings(readings)
    print(f"Weather: ingested {len(readings)} readings, upserted {count}")
    return count


@task(name="ingest_aqi", retries=2, retry_delay_seconds=30, log_prints=True)
def ingest_aqi() -> int:
    """Fetch current AQI for all 7 Delhi NCR locations."""
    from src.ingestion.aqi_ingest import fetch_all_current_aqi
    from src.storage.init_db import upsert_aqi_readings

    readings = asyncio.run(fetch_all_current_aqi())
    count = upsert_aqi_readings(readings)
    print(f"AQI: ingested {len(readings)} readings, upserted {count}")
    return count


@task(name="ingest_stations", retries=2, retry_delay_seconds=30, log_prints=True)
def ingest_stations() -> int:
    """Fetch ground station data (OpenAQ + simulated CPCB)."""
    from src.ingestion.station_ingest import fetch_station_data
    from src.storage.init_db import upsert_station_measurements

    readings = asyncio.run(fetch_station_data())
    count = upsert_station_measurements(readings)
    print(f"Stations: ingested {len(readings)} readings, upserted {count}")
    return count


# ---------------------------------------------------------------------------
# dbt transformation task
# ---------------------------------------------------------------------------

@task(name="run_dbt_transforms", retries=2, retry_delay_seconds=15, log_prints=True)
def run_dbt_transforms() -> bool:
    """Run dbt models against the vayu database.

    Uses dbt Python API directly instead of subprocess to avoid
    venv Python path issues.
    """
    from src.storage.db import is_postgres

    # dbt-postgres can't target the SQLite fallback
    if not is_postgres():
        print("WARNING: PostgreSQL unavailable (using SQLite), skipping dbt transformations")
        return False

    dbt_project_dir = Path(__file__).resolve().parent.parent.parent / "dbt_project"
    print(f"Running dbt from: {dbt_project_dir}")

    # Try running dbt via Python API (works regardless of which venv we're in)
    try:
        from dbt.cli.main import dbtRunner
        runner = dbtRunner()
        result = runner.invoke([
            "run",
            "--project-dir", str(dbt_project_dir),
            "--profiles-dir", str(dbt_project_dir),
        ])
        if not result.success:
            raise RuntimeError(f"dbt run failed: {result.exception}")
        print("dbt run: models built successfully (via API)")
        return True
    except ImportError:
        pass

    # Fallback: try subprocess with multiple Python paths
    for python_path in [sys.executable, "python", "python3"]:
        try:
            cmd = [
                python_path, "-c",
                "from dbt.cli.main import cli; cli()",
                "--", "run",
                "--project-dir", str(dbt_project_dir),
                "--profiles-dir", str(dbt_project_dir),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                pass_count = result.stdout.count("OK created")
                print(f"dbt run: {pass_count} models built successfully")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    print("WARNING: dbt not available, skipping transformations")
    return True


# ---------------------------------------------------------------------------
# Analytics tasks
# ---------------------------------------------------------------------------

@task(name="compute_feature_store", retries=2, retry_delay_seconds=15, log_prints=True)
def compute_feature_store() -> dict:
    """Compute all engineered features and save to feature_store table."""
    from src.analytics.feature_store import run_feature_pipeline

    summary = run_feature_pipeline()
    print(
        f"Feature store: {summary.get('features_available', 0)} features, "
        f"{summary.get('feature_values_saved', 0)} values saved"
    )
    return summary


@task(name="run_anomaly_detection", retries=2, retry_delay_seconds=15, log_prints=True)
def run_anomaly_detection() -> dict:
    """Run Z-score, IQR, and STL anomaly detection."""
    from src.analytics.anomaly_detection import run_anomaly_detection as _run

    results = _run()
    total = results.get("total_saved", 0)
    print(f"Anomaly detection: {total} anomalies saved")
    return results


@task(name="run_forecasting", retries=2, retry_delay_seconds=15, log_prints=True)
def run_forecasting() -> dict:
    """Run Prophet AQI forecast for all locations."""
    from src.analytics.forecasting import run_forecast_pipeline

    summary = run_forecast_pipeline()
    print(f"Forecasting: {summary.get('locations_forecasted', 0)} locations, "
          f"{summary.get('forecast_rows_saved', 0)} rows saved")
    return summary


@task(name="run_granger_causality", retries=2, retry_delay_seconds=15, log_prints=True)
def run_granger_causality() -> dict:
    """Run Granger causality tests (weather -> AQI).

    This is computationally heavier and should only run daily, not hourly.
    """
    from src.analytics.causality import run_causality_pipeline

    summary = run_causality_pipeline()
    print(
        f"Causality: {summary.get('total_tests', 0)} tests, "
        f"{summary.get('significant', 0)} significant"
    )
    return summary


@task(name="compute_data_quality", retries=2, retry_delay_seconds=15, log_prints=True)
def compute_data_quality() -> dict:
    """Score data quality across all sources."""
    from src.analytics.data_quality import run_data_quality_pipeline

    results = run_data_quality_pipeline()
    print(f"Data quality: {results.get('scores_saved', 0)} scores saved")
    return results


# ---------------------------------------------------------------------------
# AI advisory task
# ---------------------------------------------------------------------------

@task(name="generate_advisory", retries=2, retry_delay_seconds=30, log_prints=True)
def generate_advisory() -> int:
    """Generate AI health advisory from all pipeline signals."""
    from src.agent.advisory_agent import generate_advisory as _generate

    advisory_text, advisory_id = _generate()
    # Print first 200 chars as preview
    preview = advisory_text[:200].replace("\n", " ")
    print(f"Advisory #{advisory_id} generated: {preview}...")
    return advisory_id

# Vayu (वायु) — Delhi Air Quality Intelligence Pipeline

> *Sanskrit for wind/air. Because the air you breathe shouldn't be a mystery.*

A data engineering and data science pipeline that ingests air quality and weather data (plus simulated CPCB-style ground stations) for Delhi NCR, detects pollution anomalies, forecasts next-day AQI using Prophet, uncovers causal relationships between weather and pollution via Granger causality testing, and generates AI-powered health advisories — all orchestrated by Prefect and visualized in a Streamlit dashboard.

---

## Why This Exists

I grew up breathing Delhi air. AQI 400+ in winter isn't a statistic to me — it's personal. I built three AI-heavy projects but realized I'd never built the data infrastructure that feeds AI systems.

Vayu is that missing piece: a complete data pipeline — ingestion from 3 real APIs, transformation with dbt, statistical analysis including Granger causality testing, demand forecasting, and an LLM that turns raw sensor data into actionable health advisories. It's data engineering meets data science meets AI — on a problem I actually care about.

---

## Architecture

```
+-----------------------------------------------------------------+
|                    PREFECT ORCHESTRATION                         |
|                (Schedules & Monitors Everything)                 |
+--------+------------------+------------------+------------------+
         |                  |                  |
  +------v------+   +------v------+   +------v------+
  |   WEATHER   |   | AIR QUALITY |   |  GROUND     |
  |  INGESTION  |   |  INGESTION  |   |  STATIONS   |
  | OpenWeather |   | OpenWeather |   |  Simulated  |
  | Weather API |   | AirPoll API |   |  CPCB       |
  +------+------+   +------+------+   +------+------+
         |                  |                  |
         v                  v                  v
  +----------------------------------------------+
  |          VALIDATION & CLEANING                |
  |  (Pydantic v2 schemas, dedup, unit std)       |
  +---------------------+------------------------+
                        |
                        v
  +----------------------------------------------+
  |          PostgreSQL DATA WAREHOUSE            |
  |  Fact: aqi_readings, weather_readings,        |
  |        station_measurements                   |
  |  Dim: dim_stations, dim_pollutants            |
  +---------------------+------------------------+
                        |
                 +------v------+
                 |   dbt-core  |
                 |  Transform  |
                 +------+------+
                        |
         +--------------+--------------+
         v              v              v
  +------------+  +------------+  +------------+
  |  ANOMALY   |  |   AQI      |  |   DATA     |
  | DETECTION  |  |  FORECAST  |  |  QUALITY   |
  | (3 methods)|  |  (Prophet) |  |  SCORING   |
  +------+-----+  +------+-----+  +------+-----+
         |              |              |
         v              v              v
  +------+-----+  +------------+
  |  GRANGER   |  |  FEATURE   |
  | CAUSALITY  |  |   STORE    |
  | (weather   |  | (45 feats) |
  |  -> AQI)   |  |            |
  +------+-----+  +------+-----+
         |              |
         v              v
  +----------------------------------------------+
  |        LLM DIAGNOSTIC AGENT (GPT-4o-mini)     |
  |  Reads all signals -> Health advisory          |
  +---------------------+------------------------+
                        |
                        v
  +----------------------------------------------+
  |           STREAMLIT DASHBOARD                 |
  |  10 tabs: AQI overview, trends, anomalies,   |
  |  causality heatmap, features, AI advisory     |
  +----------------------------------------------+
```

### Prefect Pipeline DAG

![Prefect DAG](docs/screenshots/prefect_dag.png)

---

## Tech Stack

| Component | Tool | Why |
|-----------|------|-----|
| **Orchestration** | Prefect 2.x | Python-native, no Docker needed, local UI at localhost:4200 |
| **Data Warehouse** | PostgreSQL | Industry standard, proper star schema with SQLite fallback |
| **Transformations** | dbt-core | 10 models across staging/intermediate/marts, 54 data tests |
| **Weather Data** | OpenWeatherMap API | Free, real-time temp/humidity/wind for 7 Delhi NCR locations |
| **Air Quality Data** | OpenWeatherMap Air Pollution API | PM2.5, PM10, NO2, SO2, O3, CO, NH3 + historical backfill |
| **Ground Stations** | Simulated CPCB + OpenAQ | Realistic Delhi sensor patterns with seasonal dynamics |
| **Anomaly Detection** | scipy + statsmodels | Z-score, IQR, STL seasonal decomposition |
| **Causality Testing** | statsmodels | Granger causality with ADF stationarity tests |
| **Feature Engineering** | pandas | 45 features: lags, rolling stats, weather interactions, Delhi flags |
| **Forecasting** | Prophet | 24-hour AQI forecast per zone with feature store regressors |
| **AI Agent** | OpenAI GPT-4o-mini | Natural language health advisories from all pipeline signals |
| **Dashboard** | Streamlit + Plotly | 10-tab flat dark dashboard, IST display, skeleton loaders, SQLite-safe queries |
| **Data Validation** | Pydantic v2 | Schema enforcement on all data sources |

---

## Key Features

### Data Engineering
- **3 concurrent data sources** — weather, AQI, ground stations ingested in parallel via async httpx
- **Star schema warehouse** — 3 fact tables, 2 dimension tables, 5 results tables with upsert logic
- **dbt transformations** — 10 models (3 staging views, 3 intermediate views, 4 mart tables), 54 passing tests
- **Idempotent pipeline** — safe to re-run, all upserts handle duplicates gracefully

### Data Science
- **Granger Causality Testing** — 1,344 tests (24 lags x 7 weather/pollutant pairs x 7 stations + pooled) with ADF stationarity checks and differencing; see [Results and Limitations](#results-and-limitations) for what the tests do and do not show
- **Seasonal Anomaly Detection** — STL decomposition separates daily/weekly cycles so PM2.5 of 300 in November isn't flagged, but 300 in July is critical
- **45 Engineered Features** — lag (T-1 to T-24), rolling (6h/12h/24h/7d), weather interactions (wind stagnation, moisture trap, ventilation index), temporal, and 5 Delhi-specific flags (stubble season, winter inversion, Diwali week)
- **Prophet Forecasting** — 24-hour AQI forecast per zone with feature store regressors, evaluated by rolling backtest against naive baselines (see [Results and Limitations](#results-and-limitations))

### AI Layer
- **GPT-4o-mini Health Advisories** — reads anomalies, forecasts, causality insights, feature flags, and data quality scores to generate actionable health guidance by population group
- **Data Quality Transparency** — completeness, freshness, and cross-source consistency grades included in every advisory

---

## Monitoring Locations

| Station | Zone | Known For |
|---------|------|-----------|
| Anand Vihar | East Delhi | Consistently worst AQI in Delhi |
| ITO | Central Delhi | Traffic hotspot |
| RK Puram | South Delhi | Residential + traffic |
| Dwarka Sector 8 | West Delhi | Suburban reference |
| IGI Airport T3 | South-West | Open area baseline |
| Rohini | North-West Delhi | Industrial proximity |
| Noida Sector 62 | NCR | NCR expansion zone |

---

## Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 16+ (or SQLite fallback — auto-detected)
- OpenWeatherMap API key ([free signup](https://openweathermap.org/api))
- OpenAI API key ([get one](https://platform.openai.com/api-keys))
- OpenAQ API key (optional, [free](https://explore.openaq.org)); without it the pipeline uses the simulator only
- macOS without Homebrew: [Postgres.app](https://postgresapp.com) works well; allow your terminal under App Permissions

### Setup

```bash
# Clone and enter project
git clone <repo-url>
cd vayu-project

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and database credentials

# Create the database (PostgreSQL)
createdb vayu                   # or via psql: CREATE DATABASE vayu;

# Initialize schema and seed dimensions
python -m src.storage.init_db

# Load 30 days of history (AQI, simulated stations, Open-Meteo weather)
# Needed for forecasting, anomaly detection and causality to produce results
python -m src.orchestration.backfill --days 30

# Run the full pipeline
python -m src.orchestration.flows

# Run with Granger causality (daily)
python -m src.orchestration.flows --causality

# Launch the dashboard
python -m streamlit run src/ui/app.py
# Open http://localhost:8501

# Run the tests
python -m pytest

# Start Prefect UI (optional)
prefect server start
# Open http://localhost:4200
```

---

## Project Structure

```
vayu-project/
|-- src/
|   |-- ingestion/              # Layer 1: Data Ingestion
|   |   |-- weather_ingest.py   # OpenWeatherMap Weather API
|   |   |-- aqi_ingest.py       # OpenWeatherMap Air Pollution API
|   |   |-- station_ingest.py   # Simulated CPCB + OpenAQ
|   |   +-- validators.py       # Pydantic v2 schemas
|   |
|   |-- storage/                # Layer 2: Database
|   |   |-- db.py               # Connection manager (PG + SQLite fallback)
|   |   |-- models.py           # SQLAlchemy 2.0 ORM (11 tables)
|   |   +-- init_db.py          # Schema init, seed, upsert helpers
|   |
|   |-- analytics/              # Layer 3: Data Science
|   |   |-- anomaly_detection.py  # Z-score, IQR, STL decomposition
|   |   |-- causality.py         # Granger causality + ADF tests
|   |   |-- feature_store.py     # 45 engineered features
|   |   |-- forecasting.py       # Prophet AQI forecasting
|   |   +-- data_quality.py      # Completeness/freshness/consistency
|   |
|   |-- agent/                  # Layer 4: AI Agent
|   |   +-- advisory_agent.py   # GPT-4o-mini health advisories
|   |
|   |-- orchestration/          # Layer 5: Prefect
|   |   |-- tasks.py            # 9 @task definitions
|   |   +-- flows.py            # Pipeline DAG with concurrency
|   |
|   +-- ui/                     # Layer 6: Dashboard
|       |-- app.py              # Entry point + navigation (Dashboard, Terms, Privacy)
|       |-- dashboard.py        # Header and the 10 tabs
|       |-- data.py             # Cached, backend-agnostic SQLAlchemy loaders
|       |-- helpers.py          # IST conversion, AQI categories, season context
|       |-- theme.py            # Flat theme, skeleton loaders, components
|       +-- views/              # Tab renderers (live, analytics, ops, legal)
|
|-- dbt_project/                # dbt transformations
|   |-- models/staging/         # stg_weather, stg_aqi, stg_stations
|   |-- models/intermediate/    # hourly_zone, weather_aqi_joined, pollutants
|   +-- models/marts/           # daily_report, anomaly_log, station_comparison
|
|-- tests/                      # Test suite
|-- data/simulated/             # Simulated CPCB sensor output
|-- notebooks/                  # EDA notebooks
+-- docs/                       # Architecture docs + interview prep
```

---

## Sample AI Advisory Output

*Illustrative output from an earlier run; real advisories vary with current data.*

```
DELHI AIR QUALITY ADVISORY - March 31, 2026

CURRENT STATUS: Delhi NCR average AQI at 14 (Good). All zones within
safe limits. Primary pollutant: O3 (ground-level ozone, photochemical).

FORECAST: Granger causality analysis indicates temperature influences
AQI with an 11-hour lag (F=7.83, p<0.001). Rising afternoon temperatures
may elevate ozone levels by evening.

ANOMALY ALERT: RK Puram station PM2.5 at 291.1 ug/m3 (z-score: 3.18,
detected via Z-score method). Anand Vihar PM2.5 at 335.0 ug/m3
(z-score: 2.46). Both flagged from ground station simulated data.

CONTRIBUTING FACTORS: NW winds detected across multiple stations
(Punjab smoke vector). Wind stagnation index elevated at IGI Airport.
Stubble burning season inactive. No temperature inversion conditions.

HEALTH ADVISORY:
- Sensitive groups: Limit outdoor activities during peak hours
- General population: Normal activities safe
- Schools: Outdoor activities permitted
- Best time for outdoor activity: Early morning (before 9 AM IST)

DATA QUALITY: All sources Grade A completeness (100%). Weather data
fresh within 3 minutes. AQI data within 26 minutes.
```

![AI Advisory](docs/screenshots/ai_advisory.png)

---

## What Makes This Different

This isn't a standard ETL project. Three things set it apart:

1. **Granger causality testing** proves causal relationships, not just correlation — we can predict AQI deterioration hours before it happens using wind data alone.

2. **The feature store** decouples feature engineering from modeling — a production ML pattern. Adding a new feature doesn't require model code changes. 45 features across 5 categories.

3. **The AI advisory agent** synthesizes everything — anomalies, forecasts, causality insights, feature flags, and data quality scores — into actionable health guidance. It doesn't just report numbers; it explains *why* and *what to do*.

---

## Screenshots

### Dashboard Overview
![Dashboard Overview](docs/screenshots/dashboard_overview.png)

### Granger Causality Heatmap
![Causality Heatmap](docs/screenshots/causality_heatmap.png)

*Screenshots predate the dashboard redesign and the numbers in Results and Limitations.*

---

## Results and Limitations

Measured on 30 days of hourly data (Sep 10 to Oct 10, 2026) across the 7 locations. Reproduce with `python -m src.orchestration.backfill`, then `python -m src.orchestration.flows --causality` (Granger) and `python -m src.analytics.backtest` (forecast accuracy).

| Measure | Result |
|---------|--------|
| Granger tests run | 1,344 |
| Significant at p < 0.05 | 595 |
| Significant after Bonferroni correction | 199 |
| Wind speed to AQI | Weak: 11 of 192 tests significant |
| Temperature and humidity to pollution | Significant almost everywhere, likely driven by the shared daily cycle |
| Prophet 24h category accuracy (rolling backtest, 1,708 hourly forecasts) | 69.4% |
| Baseline: predict the last observed value | 75.9% |
| Baseline: same hour yesterday | 70.8% |

What this means:
- **Prophet does not beat naive baselines in this window.** Most days are Good or Satisfactory, so a flat guess scores well. The model should be re-evaluated over the stubble and winter seasons, when AQI varies far more.
- **Many significant lags overstate the evidence.** Neighbouring lags are correlated, and the raw p < 0.05 count is not corrected for multiple testing (the Bonferroni figure above uses a stricter threshold). Granger tests show predictive value, not physical causation.
- **Stubble season findings are untested.** Oct 15 to Nov 30 had not started when these numbers were measured.
- **Ground-station data is simulated.** AQI comes from OpenWeatherMap and weather history from Open-Meteo; the CPCB-style stations come from a simulator.

---

## Future Improvements

- **Real-time streaming**: Replace batch ingestion with Kafka for live CPCB station feeds
- **Containerization**: Docker Compose for PostgreSQL + Prefect + Streamlit
- **Alerting**: WhatsApp/Telegram alerts when AQI breaches severity thresholds
- **Real CPCB API**: Integrate with actual Central Pollution Control Board data feeds
- **Cloud deployment**: Prefect Cloud + BigQuery/Snowflake for scale
- **Model registry**: MLflow for Prophet model versioning and A/B testing
- **Mobile-first dashboard**: React Native app for on-the-go AQI monitoring

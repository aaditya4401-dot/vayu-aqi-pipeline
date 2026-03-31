# Vayu — Delhi Air Quality Intelligence Pipeline

> *Vayu (वायु) — Sanskrit for wind/air. Because the air you breathe shouldn't be a mystery.*

## What This Is
A production-grade data engineering pipeline that ingests real-time air quality, weather, and ground-station data for Delhi NCR, detects pollution anomalies, forecasts next-day AQI, uncovers causal relationships between weather and pollution, and generates AI-powered health advisories. Built to demonstrate end-to-end data engineering with embedded data science and an intelligent AI layer.

## Why This Exists (Interview Story)
"I grew up breathing Delhi air. AQI 400+ in winter isn't a statistic to me — it's personal. I built three AI-heavy projects but realized I'd never built the data infrastructure that feeds AI systems. Vayu is that missing piece: a complete data pipeline — ingestion from 3 real APIs, transformation with dbt, statistical analysis including Granger causality testing, demand forecasting, and an LLM that turns raw sensor data into actionable health advisories. It's data engineering meets data science meets AI — on a problem I actually care about."

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PREFECT ORCHESTRATION                        │
│                    (Schedules & Monitors Everything)                 │
└──────────┬──────────────────┬──────────────────┬────────────────────┘
           │                  │                  │
    ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │   WEATHER   │   │ AIR QUALITY │   │  GROUND     │
    │  INGESTION  │   │  INGESTION  │   │  STATIONS   │
    │ OpenWeather │   │ OpenWeather │   │  OpenAQ /   │
    │ Weather API │   │ AirPoll API │   │  Simulated  │
    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
           │                  │                  │
           ▼                  ▼                  ▼
    ┌─────────────────────────────────────────────────┐
    │              VALIDATION & CLEANING               │
    │  (Pydantic schemas, dedup, missing values,       │
    │   unit standardization μg/m³)                    │
    └──────────────────────┬──────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────┐
    │              PostgreSQL DATA WAREHOUSE           │
    │  Fact: aqi_readings, weather_readings,           │
    │        station_measurements                      │
    │  Dim: stations, pollutants, locations, time_dim  │
    └──────────────────────┬──────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │   dbt-core  │
                    │  Transform  │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   ANOMALY    │  │   AQI        │  │   DATA       │
│  DETECTION   │  │  FORECAST    │  │  QUALITY     │
│  (Stats/DS)  │  │  (Prophet)   │  │  SCORING     │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐
│   GRANGER    │  │   FEATURE    │
│  CAUSALITY   │  │   STORE      │
│  (weather →  │  │  (lags, rolls│
│   pollution) │  │   interactions│
└──────┬───────┘  └──────┬───────┘
       │                 │
       ▼                 ▼
┌─────────────────────────────────────────────────┐
│          LLM DIAGNOSTIC AGENT (OpenAI)           │
│  Reads all signals → Generates health advisory   │
│  "Delhi AQI projected to breach 400 tomorrow.    │
│   Wind speed dropping + stubble burning season   │
│   = severe smog. Avoid outdoor exercise."        │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│           STREAMLIT DASHBOARD                    │
│  Live AQI map, anomaly timeline, forecasts,      │
│  causality matrix, AI advisories, data quality   │
└─────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Tool | Why |
|-----------|------|-----|
| Orchestration | **Prefect** | Python-native, no Docker needed, local UI at localhost:4200 |
| Data Warehouse | **PostgreSQL** | Industry standard, proper star schema |
| Transformations | **dbt-core** | #1 DE tool hiring managers look for |
| Weather Data | **OpenWeatherMap Weather API** | Free, real-time temp/humidity/wind for Delhi |
| Air Quality Data | **OpenWeatherMap Air Pollution API** | Free, PM2.5/PM10/NO2/SO2/O3/CO/NH3 + AQI, history back to Nov 2020 |
| Ground Stations | **OpenAQ API + Simulated CPCB** | Real Delhi station data + simulated sensor network |
| Anomaly Detection | **scipy + statsmodels** | Z-score, IQR, STL seasonal decomposition |
| Causality Testing | **statsmodels** | Granger causality, ADF stationarity tests |
| Feature Engineering | **pandas + custom** | Lag features, rolling stats, weather interactions |
| Forecasting | **Prophet** | Industry standard time series forecasting |
| AI Agent | **OpenAI GPT-4o-mini** | Generates natural language health advisories |
| Dashboard | **Streamlit** | Interactive, demo-ready |
| Data Validation | **Pydantic v2** | Schema enforcement |

---

## Delhi NCR Monitoring Locations

We'll track AQI across these Delhi NCR zones (real CPCB station locations):

| Station | Zone | Lat | Lon | Known For |
|---------|------|-----|-----|-----------|
| Anand Vihar | East Delhi | 28.6469 | 77.3164 | Consistently worst AQI in Delhi |
| ITO | Central Delhi | 28.6289 | 77.2418 | Traffic hotspot |
| RK Puram | South Delhi | 28.5633 | 77.1864 | Residential + traffic |
| Dwarka Sector 8 | West Delhi | 28.5709 | 77.0712 | Suburban reference |
| IGI Airport T3 | South-West | 28.5562 | 77.1000 | Open area baseline |
| Rohini | North-West Delhi | 28.7324 | 77.1198 | Industrial proximity |
| Noida Sector 62 | NCR | 28.6252 | 77.3650 | NCR expansion zone |

---

## Folder Structure

```
vayu-aqi-pipeline/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env
├── .gitignore
│
├── src/
│   ├── __init__.py
│   │
│   ├── ingestion/               # Layer 1: Data Ingestion
│   │   ├── __init__.py
│   │   ├── weather_ingest.py    # OpenWeatherMap Weather API (temp, humidity, wind)
│   │   ├── aqi_ingest.py        # OpenWeatherMap Air Pollution API (PM2.5, PM10, etc.)
│   │   ├── station_ingest.py    # OpenAQ ground stations + simulated CPCB sensors
│   │   └── validators.py        # Pydantic schemas for all data sources
│   │
│   ├── storage/                 # Layer 2: Database
│   │   ├── __init__.py
│   │   ├── db.py                # PostgreSQL connection + SQLAlchemy
│   │   ├── models.py            # SQLAlchemy ORM models (fact + dim tables)
│   │   └── init_db.py           # Create schema, seed dimensions
│   │
│   ├── analytics/               # Layer 3: Data Science
│   │   ├── __init__.py
│   │   ├── anomaly_detection.py # Z-score, IQR, STL decomposition on AQI
│   │   ├── forecasting.py       # Prophet AQI forecasting using feature store
│   │   ├── data_quality.py      # Completeness, freshness, consistency scoring
│   │   ├── causality.py         # Granger causality: weather → AQI
│   │   └── feature_store.py     # Engineered features: lags, rolling, interactions
│   │
│   ├── agent/                   # Layer 4: AI Diagnostic Agent
│   │   ├── __init__.py
│   │   └── advisory_agent.py    # LLM health advisory generator
│   │
│   ├── orchestration/           # Layer 5: Prefect Flows
│   │   ├── __init__.py
│   │   ├── flows.py             # Main pipeline flow
│   │   └── tasks.py             # Prefect task definitions
│   │
│   └── ui/                      # Layer 6: Dashboard
│       └── app.py               # Streamlit dashboard
│
├── dbt_project/                 # dbt transformations
│   ├── dbt_project.yml
│   ├── profiles.yml
│   └── models/
│       ├── staging/
│       │   ├── stg_weather.sql
│       │   ├── stg_aqi.sql
│       │   └── stg_stations.sql
│       ├── intermediate/
│       │   ├── int_hourly_zone_aqi.sql
│       │   ├── int_weather_aqi_joined.sql
│       │   └── int_pollutant_breakdown.sql
│       └── marts/
│           ├── mart_daily_aqi_report.sql
│           ├── mart_anomaly_log.sql
│           ├── mart_station_comparison.sql
│           └── mart_forecast_accuracy.sql
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_anomaly_detection.py
│   ├── test_causality.py
│   └── test_data_quality.py
│
├── data/
│   └── simulated/               # Simulated CPCB sensor output
│
├── notebooks/
│   └── eda_delhi_aqi.ipynb
│
└── docs/
    ├── architecture.md
    └── INTERVIEW_PREP.md
```

---

## Implementation Order (Build Sequence)

### Step 1: Project Setup
- Initialize repo, virtual env, requirements.txt
- Set up PostgreSQL locally (or SQLite fallback)
- Create `.env` with API keys
- Create CLAUDE.md

### Step 2: Data Ingestion Layer
- **`weather_ingest.py`** — Fetch current weather for all 7 Delhi NCR locations
  - Data: temperature, humidity, wind_speed, wind_direction, pressure, visibility
  - Wind direction is CRITICAL for Delhi — NW wind carries Punjab stubble smoke
  - Also fetch historical weather (backfill 30 days for model training)

- **`aqi_ingest.py`** — Fetch air pollution data for all 7 locations
  - Current: AQI, PM2.5, PM10, NO2, SO2, O3, CO, NH3
  - Historical: Backfill 30 days from OpenWeatherMap history endpoint
  - Forecast: 4-day hourly AQI forecast (built into the API!)

- **`station_ingest.py`** — Ground station data
  - Try OpenAQ for real Delhi CPCB station data
  - Supplement with simulated sensor network that generates realistic Delhi patterns:
    - Morning rush hour spike (8-10am)
    - Evening cooking + traffic spike (6-9pm)
    - Winter inversion amplification (Nov-Feb)
    - Stubble burning season overlay (Oct-Nov)
    - Diwali spike simulation
    - Weekend vs weekday patterns

- **`validators.py`** — Pydantic v2 models
  - WeatherReading, AQIReading, StationMeasurement schemas
  - Unit standardization (everything to μg/m³)
  - Range validation (PM2.5 can't be negative, AQI 0-500)

### Step 3: Storage Layer
- SQLAlchemy ORM models:
  - **Fact tables**: `weather_readings`, `aqi_readings`, `station_measurements`
  - **Dimension tables**: `dim_stations`, `dim_pollutants`, `dim_locations`, `dim_time`
  - **Feature table**: `feature_store` (computed features with timestamps)
  - **Results tables**: `anomaly_log`, `forecasts`, `causality_results`, `advisories`
- Upsert logic for idempotent re-runs
- Index on (location_id, timestamp) for fast time series queries

### Step 4: dbt Transformations
- **Staging**: Clean raw data, standardize column names, handle nulls
  - `stg_weather.sql` — weather readings with derived fields
  - `stg_aqi.sql` — AQI readings with Indian AQI category labels (Good/Satisfactory/Moderate/Poor/Very Poor/Severe)
  - `stg_stations.sql` — ground station measurements
- **Intermediate**: Join and enrich
  - `int_hourly_zone_aqi.sql` — average AQI per zone per hour
  - `int_weather_aqi_joined.sql` — weather + AQI aligned by location and timestamp
  - `int_pollutant_breakdown.sql` — which pollutant is driving AQI at each station
- **Marts**: Business-ready aggregates
  - `mart_daily_aqi_report.sql` — daily summary per zone with min/max/avg/dominant pollutant
  - `mart_anomaly_log.sql` — all detected anomalies with context
  - `mart_station_comparison.sql` — cross-station analysis (which zone is worst?)
  - `mart_forecast_accuracy.sql` — predicted vs actual AQI tracking
- **dbt tests**: unique, not_null, accepted_values (AQI categories), relationships

### Step 5: Analytics / Data Science Layer

- **`anomaly_detection.py`**:
  - Z-score detection on PM2.5 and AQI per station
  - IQR method for outlier detection (robust to Delhi's skewed AQI distribution)
  - STL Decomposition — separates AQI into trend + seasonal + residual
    - Seasonal component captures: daily cycle (morning/evening peaks), weekly (weekday vs weekend)
    - Anomalies in RESIDUAL = genuinely unusual events (construction, fire, unusual weather)
    - "PM2.5 of 300 in November is bad but seasonal — PM2.5 of 300 in July is a real anomaly"
  - Severity levels: low/medium/high/critical with different thresholds per season

- **`causality.py`** (Granger Causality Testing):
  - **Primary tests**:
    - Does wind_speed Granger-cause AQI? (hypothesis: low wind → AQI rises)
    - Does wind_direction Granger-cause PM2.5? (NW wind from Punjab = smoke)
    - Does temperature Granger-cause AQI? (winter inversion traps pollutants)
    - Does humidity Granger-cause PM2.5? (moisture traps particulates)
  - **Test at multiple lags**: 1h, 2h, 4h, 6h, 12h, 24h
  - **Stationarity**: ADF test first — difference if needed
  - **Output**: Causality matrix with p-values per variable pair per lag
  - **Interview gold**: "Wind speed Granger-causes AQI at a 4-hour lag with p < 0.01 — we can predict AQI deterioration 4 hours before it happens using wind data alone"
  - **Delhi-specific insight**: "NW wind direction (carrying Punjab crop smoke) Granger-causes PM2.5 spikes at a 6-hour lag during October-November"

- **`feature_store.py`** (Engineered Feature Store):
  - **Lag features**: AQI at T-1, T-2, T-6, T-12, T-24 (same hour yesterday)
  - **Rolling statistics**: 6h/12h/24h/7d rolling mean, std, min, max for PM2.5 and AQI
  - **Rate of change**: aqi_delta_1h, pm25_delta_1h (is pollution rising or falling?)
  - **Weather interaction features**:
    - `wind_stagnation_index` = 1 / (wind_speed + 0.1) — low wind = trapped pollution
    - `inversion_proxy` = surface_temp - (estimated upper air temp) — temperature inversion indicator
    - `moisture_trap` = humidity * pm25 — humid air traps more particulates
    - `ventilation_index` = wind_speed * mixing_height_proxy — atmosphere's ability to disperse pollutants
  - **Temporal features**: hour_of_day, day_of_week, is_weekend, is_rush_hour (8-10am, 5-8pm), month, season
  - **Delhi-specific binary flags**:
    - `is_stubble_season` — Oct 15 to Nov 30 (Punjab crop burning)
    - `is_winter_inversion` — Dec 1 to Feb 15 (cold traps pollution at ground level)
    - `is_diwali_week` — ±3 days around Diwali (fireworks spike)
    - `is_extreme_aqi` — AQI > 300 (severe category)
    - `wind_from_northwest` — wind direction 270°-360° (Punjab smoke direction)
  - Store in `feature_store` table, versioned with timestamps
  - Prophet model consumes FROM this store

- **`forecasting.py`**:
  - Prophet model for 24-hour AQI forecast per zone
  - Regressors from feature store: wind_speed, temperature, humidity, is_stubble_season
  - Train/test split respecting temporal order
  - Evaluation: MAPE, RMSE, and category accuracy (did we predict the right AQI band?)
  - Compare forecast vs actual on dashboard

- **`data_quality.py`**:
  - Completeness: % non-null per source per pollutant
  - Freshness: staleness per station (some CPCB stations go offline)
  - Consistency: do OpenWeatherMap AQI and ground station AQI agree? Cross-source validation
  - Overall grade per source: A/B/C/D/F

### Step 6: AI Diagnostic Agent
- **`advisory_agent.py`**:
  - Receives ALL signals: anomalies, forecast, causality insights, feature store summary, data quality
  - Generates a health advisory in natural language
  - Example output:
    ```
    🌫️ DELHI AIR QUALITY ADVISORY — March 31, 2026

    CURRENT STATUS: Delhi NCR average AQI at 287 (Poor). Worst zone:
    Anand Vihar at 384 (Very Poor). Primary pollutant: PM2.5 at 
    198 μg/m³ — 8x WHO guideline.

    FORECAST: AQI projected to worsen to 350-400 (Very Poor → Severe)
    over the next 24 hours. Wind speed dropping from 12 km/h to 4 km/h
    by tomorrow morning. Granger analysis confirms: wind speed decline
    leads AQI deterioration by ~4 hours. Expect worst conditions 
    between 6am-10am tomorrow.

    ANOMALY ALERT: Rohini station showing PM10 at 3.2 standard 
    deviations above seasonal norm. 7-day rolling average up 22%.
    Possible construction activity or localized industrial source.

    CONTRIBUTING FACTORS: Wind from NW direction (Punjab) detected.
    Stubble burning season active. Temperature inversion forming
    (surface temp 18°C, humidity 85%). Ventilation index critically low.

    HEALTH ADVISORY:
    - Sensitive groups: Avoid ALL outdoor activity
    - General population: Limit outdoor exposure, use N95 masks
    - Schools: Recommend indoor activities only
    - Best time for outdoor activity: 2pm-4pm (typical daily AQI minimum)
    
    DATA QUALITY: OpenWeatherMap: Grade A (real-time). Ground stations:
    Grade B (2 of 7 stations reporting 15-min delay). Feature store:
    24 features computed, latest batch 8 minutes ago.
    ```

### Step 7: Prefect Orchestration
- Prefect flow chains all steps:
  1. Ingest weather data for all 7 locations (task)
  2. Ingest AQI data for all 7 locations (task)
  3. Ingest/generate ground station data (task)
  4. Validate all data with Pydantic (task)
  5. Load to PostgreSQL (task)
  6. Run dbt transformations (task)
  7. Compute feature store (task)
  8. Run anomaly detection (task)
  9. Run AQI forecast using feature store (task)
  10. Run Granger causality tests (task — daily, not hourly)
  11. Calculate data quality scores (task)
  12. Generate AI health advisory (task)
- Retry logic on API failures
- Prefect UI at localhost:4200 shows full DAG
- Schedule: hourly (or manual trigger for demo)

### Step 8: Streamlit Dashboard
- **Overview page**: 
  - AQI cards per zone (color-coded: green/yellow/orange/red/purple/maroon per AQI band)
  - Delhi NCR map with color-coded markers
  - Current dominant pollutant
- **AQI Trend chart**: Line chart of AQI over time per zone (selectable)
- **Pollutant Breakdown**: Stacked bar — which pollutants contribute most at each station
- **Anomaly Timeline**: Scatter plot of detected anomalies with severity coloring
- **Forecast vs Actual**: Line chart comparing predicted AQI to reality
- **Causality Matrix tab**: Heatmap of Granger causality p-values (weather vars × AQI vars × lags)
  - This visual makes interviewers stop and ask questions
- **Feature Store tab**: Feature catalog with distributions and drift tracking
- **AI Advisory panel**: Latest health advisory with timestamp
- **Data Quality tab**: Source-by-source scores
- **Pipeline Health tab**: Prefect run status, task durations

### Step 9: Polish & Deploy
- Clean README with architecture diagram, setup instructions, demo screenshots
- Add INTERVIEW_PREP.md
- Record 2-3 minute demo video
- Push to GitHub

---

## API Keys Needed

```
# .env file
OPENWEATHER_API_KEY=xxx        # Free: openweathermap.org (covers BOTH weather + air pollution)
OPENAI_API_KEY=xxx             # For AI advisory agent
# OpenAQ is free and doesn't require a key for basic access
```

Note: You only need TWO API keys (OpenWeatherMap + OpenAI). OpenAQ is keyless for basic queries.

---

## PostgreSQL Setup

Option A (recommended): Install PostgreSQL locally
- Mac: `brew install postgresql@16 && brew services start postgresql`
- Windows: Download from postgresql.org, use installer
- Linux: `sudo apt install postgresql && sudo systemctl start postgresql`
- Create database: `createdb vayu`

Option B (fallback): Use SQLite
- Code should detect if Postgres is unavailable and fall back to SQLite
- Less impressive in interviews but functional for demo

---

## Key Interview Talking Points

1. **"Why this project?"** — "I grew up in Delhi. AQI 400+ isn't a number to me, it's the reason my grandmother can't step outside in November. I wanted to build a system that turns raw sensor data into actionable intelligence."

2. **"Why Prefect over Airflow?"** — Python-native, no Docker dependency, easier local dev. Increasingly adopted by modern data teams. Airflow requires more infrastructure overhead for what's fundamentally a scheduling problem.

3. **"Why dbt?"** — Industry standard for transformation. Brings software engineering practices (version control, testing, documentation) to SQL. Every serious data team uses it.

4. **"What makes this different from a standard ETL project?"** — Three things: (1) Granger causality testing proves causal relationships, not just correlation — we can predict AQI deterioration hours before it happens. (2) The feature store decouples feature engineering from modeling — production ML pattern. (3) The AI advisory agent synthesizes everything into actionable health guidance.

5. **"Explain the Granger causality."** — "I test whether past values of weather variables improve predictions of AQI beyond what AQI's own history provides. Wind speed Granger-causes AQI at a 4-hour lag — meaning dropping wind speed predicts pollution 4 hours early. During stubble burning season, NW wind direction Granger-causes PM2.5 at a 6-hour lag. I ran ADF tests first to ensure stationarity."

6. **"What's in the feature store?"** — "Five categories: lag features (same-hour-yesterday AQI), rolling statistics (7-day trend), weather interactions (wind stagnation index, ventilation index, moisture trap), temporal features, and Delhi-specific flags (stubble season, winter inversion, Diwali week). Prophet consumes from the store directly — adding a feature doesn't require model code changes."

7. **"How do you handle data quality?"** — "Three dimensions: completeness (null rates per station — some CPCB stations go offline), freshness (staleness detection), and consistency (do OpenWeatherMap and ground station readings agree?). Each source gets a letter grade. The AI agent references data quality in its advisory."

8. **"How would you scale this?"** — "Replace PostgreSQL with BigQuery/Snowflake, Prefect local with Prefect Cloud, add Kafka for real-time streaming from actual CPCB stations, containerize with Docker, add alerting via Twilio/WhatsApp for health advisories."

9. **"Walk me through the anomaly detection."** — "Three methods: Z-score for simple deviation, IQR for robustness (Delhi AQI is heavily right-skewed), and STL decomposition for seasonal awareness. STL separates daily cycles and weekly patterns — so the system knows PM2.5 of 300 in November is seasonal, but 300 in July is a genuine anomaly worth investigating."

---

## Success Criteria

1. Pipeline ingests from 3 sources (weather, AQI, stations) successfully
2. Data lands in PostgreSQL with proper star schema
3. dbt models run and produce correct aggregations + pass all tests
4. Anomaly detection flags realistic anomalies with correct severity
5. Granger causality identifies significant weather → AQI relationships with p-values
6. Feature store computes 20+ features per location per timestamp
7. Prophet forecast produces reasonable AQI predictions (MAPE < 25%)
8. AI advisory is coherent, actionable, and references causality + feature insights
9. Prefect UI shows full DAG with successful runs
10. Streamlit dashboard displays all components including causality heatmap
11. Full pipeline runs end-to-end in under 90 seconds

---

## CLAUDE.md Content

```
# Project: Vayu — Delhi Air Quality Intelligence Pipeline

## Context
Data engineering + data science pipeline for Delhi NCR air quality monitoring.
Follow the implementation order in project_brief.md strictly.

## Tech Rules
- Python 3.10+
- Use Prefect for orchestration (@flow and @task decorators)
- Use SQLAlchemy 2.0 for database ORM
- Use Pydantic v2 for all data validation
- Use dbt-core with dbt-postgres adapter for transformations
- Type hints on ALL functions
- Docstrings on ALL public functions
- async where it makes sense (API calls)

## Architecture Rules
- All API calls must have retry logic (3 retries with exponential backoff)
- Handle PostgreSQL connection failures gracefully — fall back to SQLite
- All timestamps in UTC, convert to IST only in dashboard display
- AQI values always stored as integers (0-500 scale)
- Pollutant concentrations in μg/m³
- Feature store table must be versioned with computation timestamps

## Delhi-Specific
- 7 monitoring locations (see project brief for coordinates)
- Indian AQI categories: Good (0-50), Satisfactory (51-100), Moderate (101-200), Poor (201-300), Very Poor (301-400), Severe (401-500)
- Stubble burning season: Oct 15 - Nov 30
- Winter inversion period: Dec 1 - Feb 15
- NW wind (270°-360°) carries Punjab crop smoke
```

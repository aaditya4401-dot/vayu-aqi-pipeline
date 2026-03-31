# Vayu — Delhi Air Quality Intelligence Pipeline

> *Vayu (वायु) — Sanskrit for wind/air. Because the air you breathe shouldn't be a mystery.*

A production-grade data engineering pipeline that ingests real-time air quality, weather, and ground-station data for Delhi NCR, detects pollution anomalies, forecasts next-day AQI, uncovers causal relationships between weather and pollution, and generates AI-powered health advisories.

## Architecture

```
API Sources (OpenWeatherMap + OpenAQ)
        │
        ▼
Ingestion Layer (async, Pydantic validated)
        │
        ▼
PostgreSQL Data Warehouse (star schema)
        │
        ▼
dbt Transformations (staging → intermediate → marts)
        │
        ▼
Analytics (anomaly detection, Granger causality, feature store, Prophet forecast)
        │
        ▼
AI Advisory Agent (GPT-4o-mini health advisories)
        │
        ▼
Streamlit Dashboard (live AQI, forecasts, causality heatmap)
```

**Orchestrated by Prefect** — full DAG visible at `localhost:4200`.

## Tech Stack

| Component | Tool |
|-----------|------|
| Orchestration | Prefect |
| Data Warehouse | PostgreSQL |
| Transformations | dbt-core |
| Weather + AQI Data | OpenWeatherMap API |
| Ground Stations | OpenAQ + Simulated CPCB |
| Anomaly Detection | scipy, statsmodels (Z-score, IQR, STL) |
| Causality Testing | statsmodels (Granger, ADF) |
| Forecasting | Prophet |
| AI Agent | OpenAI GPT-4o-mini |
| Dashboard | Streamlit |
| Validation | Pydantic v2 |

## Monitoring Locations

7 Delhi NCR zones: Anand Vihar, ITO, RK Puram, Dwarka Sector 8, IGI Airport T3, Rohini, Noida Sector 62.

## Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 16 (or SQLite fallback)
- OpenWeatherMap API key (free)
- OpenAI API key

### Setup

```bash
# Clone and enter project
git clone <repo-url>
cd vayu-project

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Initialize database
python -m src.storage.init_db

# Run the pipeline
python -m src.orchestration.flows

# Launch dashboard
streamlit run src/ui/app.py
```

## Project Structure

```
vayu-project/
├── src/
│   ├── ingestion/       # API fetchers + validators
│   ├── storage/         # DB connection + ORM models
│   ├── analytics/       # Anomaly, causality, forecasting, features
│   ├── agent/           # LLM health advisory
│   ├── orchestration/   # Prefect flows & tasks
│   └── ui/              # Streamlit dashboard
├── dbt_project/         # dbt transformations
├── tests/               # Test suite
├── data/simulated/      # Simulated sensor data
├── notebooks/           # EDA notebooks
└── docs/                # Architecture docs
```

## Key Features

- **Granger Causality Testing** — Proves wind speed predicts AQI deterioration 4 hours early
- **Seasonal Anomaly Detection** — STL decomposition distinguishes seasonal patterns from genuine anomalies
- **Feature Store** — 20+ engineered features (lag, rolling, weather interactions, Delhi-specific flags)
- **AI Health Advisories** — LLM synthesizes all signals into actionable guidance
- **Data Quality Scoring** — Completeness, freshness, and cross-source consistency grading

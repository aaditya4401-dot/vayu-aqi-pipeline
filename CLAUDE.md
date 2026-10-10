# Project: Vayu — Delhi Air Quality Intelligence Pipeline

## Context
Data engineering + data science pipeline for Delhi NCR air quality monitoring.
Follow the implementation order in Vayu_Project_Brief.md strictly.

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

## Project Structure
- `src/ingestion/` — API data fetchers + Pydantic validators
- `src/storage/` — PostgreSQL connection, SQLAlchemy models, schema init
- `src/analytics/` — Anomaly detection, forecasting, causality, feature store, data quality
- `src/agent/` — LLM health advisory generator
- `src/orchestration/` — Prefect flows and tasks
- `src/ui/` — Streamlit dashboard
- `dbt_project/` — dbt models (staging → intermediate → marts)
- `tests/` — pytest test suite
- `data/simulated/` — Simulated CPCB sensor output

## Frontend Design: Banned Patterns
When building or editing any frontend (including `src/ui/` and any website or landing page), NEVER use the following. Treat this as a hard constraint.

### Color and surfaces
- Harsh gradients
- Rainbow coloring
- Purple and black color scheme
- Neon colors
- Basic pastel colors
- Pure white background
- Liquid glass effects
- Radial orbs
- Dot grids

### Typography
- Inter, Geist, or Space Grotesk fonts
- Em dashes in any UI copy
- "It's not X, it's Y" phrasing in copy
- Emojis

### Iconography
- Lucide icons
- Sparkle icons
- Animated arrows

### Layout and components
- Drop shadows
- Soft corner radius (rounded, pill-like corners)
- Colored left stripe on cards or callouts
- 3 feature cards in a row
- Bento grids
- Checkmark bullets
- 3 pricing tiers
- Terminal window mockups
- Hover animations

### Content and completeness
- Fake testimonials
- Missing real product demos (show the actual working product)
- Missing skeleton loaders (loading states must use skeleton loaders)
- Missing Terms of Service page
- Missing Privacy Policy page

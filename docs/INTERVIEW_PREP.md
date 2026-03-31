# Vayu — Interview Preparation Guide

Talking points for discussing this project in data engineering and data science interviews.

---

## 1. "Why this project?"

"I grew up in Delhi. AQI 400+ isn't a number to me, it's the reason my grandmother can't step outside in November. I wanted to build a system that turns raw sensor data into actionable intelligence. I'd built AI projects before but never the data infrastructure that feeds them — Vayu is that missing piece."

---

## 2. "Walk me through the pipeline end-to-end."

"The pipeline runs hourly via Prefect, with 7 stages:

1. **Ingestion** — three async tasks run concurrently: weather data from OpenWeatherMap (temp, humidity, wind for 7 Delhi locations), air quality data from the Air Pollution API (PM2.5, PM10, NO2, SO2, O3, CO, NH3), and ground station measurements from a simulated CPCB sensor network that models realistic Delhi patterns.

2. **Validation & Loading** — every reading passes through Pydantic v2 schemas that enforce types, ranges (AQI 0-500, PM2.5 non-negative), and unit standardization to ug/m3. Validated data is upserted into PostgreSQL with idempotent logic — the pipeline is safe to re-run.

3. **dbt Transformations** — 10 models across three layers. Staging views clean raw data and derive fields like wind_from_northwest and Indian AQI categories. Intermediate views join weather+AQI by location and hour. Marts produce daily zone reports, station comparisons, and forecast accuracy tracking. 54 data tests validate everything.

4. **Feature Engineering** — 45 features computed per location per timestamp: lag features (AQI at T-1 through T-24), rolling statistics (6h/12h/24h/7d), rate of change, weather interaction features (wind stagnation index, moisture trap, ventilation index), and Delhi-specific binary flags (stubble season, winter inversion, Diwali week).

5. **Analytics** — anomaly detection runs three methods in parallel (Z-score, IQR, STL decomposition), each with season-adjusted severity thresholds. Prophet forecasts 24 hours ahead using feature store regressors. Granger causality tests run daily — 1,344 tests across 7 weather-pollution variable pairs at multiple lags.

6. **AI Advisory** — GPT-4o-mini reads all signals: current AQI, anomalies, forecasts, causality insights, feature flags, and data quality scores. It generates a structured health advisory with specific recommendations per population group.

7. **Dashboard** — 10-tab Streamlit app with Plotly charts: AQI overview cards, trend lines with severity bands, pollutant breakdown, anomaly scatter plot, causality heatmap, feature catalog, and the AI advisory."

---

## 3. "Why Prefect over Airflow?"

"Python-native, no Docker dependency, easier local development. Airflow requires more infrastructure overhead for what's fundamentally a scheduling problem — you need a webserver, scheduler, and metadata database just to run a DAG. Prefect lets me define flows with `@flow` and `@task` decorators, run them locally, and get a UI at localhost:4200 with zero config. It's increasingly adopted by modern data teams."

---

## 4. "Why dbt?"

"Industry standard for transformation. It brings software engineering practices — version control, testing, documentation — to SQL. Every serious data team uses it. My dbt project has 10 models across staging/intermediate/marts layers with 54 tests covering uniqueness, not-null constraints, accepted values for AQI categories, and referential integrity between fact and dimension tables."

---

## 5. "What makes this different from a standard ETL project?"

"Three things:

1. **Granger causality** proves causal relationships, not just correlation. I test whether past values of wind speed, temperature, humidity, and wind direction improve AQI predictions beyond AQI's own history. I ran ADF stationarity tests first, differenced non-stationary series, then tested at lags 1-24 hours. Finding: wind speed Granger-causes AQI at a 4-hour lag — we can predict pollution 4 hours before it happens.

2. **The feature store** decouples feature engineering from modeling — a production ML pattern. Prophet consumes features directly from the store table. Adding a new feature doesn't require model code changes. 45 features across 5 categories.

3. **The AI advisory agent** synthesizes everything — it doesn't just report numbers. It reads anomalies, forecasts, causality insights, feature flags, and data quality scores, then generates health guidance that explains *why* (Granger causality says wind is dropping) and *what to do* (avoid outdoor exercise tomorrow morning)."

---

## 6. "Explain the Granger causality."

"I test whether past values of weather variables improve predictions of AQI beyond what AQI's own history provides. The process:

1. **Stationarity check** — I run Augmented Dickey-Fuller tests on every series. Non-stationary series get differenced until stationary.

2. **Test at multiple lags** — 1h, 2h, 4h, 6h, 12h, 24h. Each lag answers: 'does knowing wind speed from N hours ago help predict current AQI?'

3. **Results** — 1,344 tests total. 214 significant at p < 0.05. Key findings:
   - Wind speed Granger-causes AQI — dropping wind predicts pollution 4 hours early
   - Temperature Granger-causes AQI at 11-hour lag — winter inversions trap pollutants
   - Humidity Granger-causes PM2.5 — moisture traps particulates
   - During stubble burning season, NW wind direction Granger-causes PM2.5 at 6-hour lag — Punjab crop smoke

4. **Interview gold quote**: 'Wind speed Granger-causes AQI at a 4-hour lag with p < 0.01 — we can predict AQI deterioration 4 hours before it happens using wind data alone.'"

---

## 7. "What's in the feature store?"

"Five categories, 45 features total:

1. **Lag features** (10): AQI and PM2.5 at T-1, T-2, T-6, T-12, T-24 — same-hour-yesterday is a strong predictor
2. **Rolling statistics** (16): 6h/12h/24h/7d rolling mean and std for both PM2.5 and AQI — captures trend and volatility
3. **Rate of change** (2): aqi_delta_1h, pm25_delta_1h — is pollution rising or falling right now?
4. **Weather interactions** (4):
   - `wind_stagnation_index` = 1/(wind_speed + 0.1) — low wind means trapped pollution
   - `moisture_trap` = humidity * PM2.5 / 100 — humid air holds more particulates
   - `ventilation_index` = wind_speed * clear_sky_fraction — atmosphere's dispersion capacity
   - `inversion_proxy` — flags when temp < 15C, humidity > 70%, wind < 2 m/s
5. **Temporal + Delhi flags** (13): hour_of_day, is_weekend, is_rush_hour, plus 5 Delhi-specific binary flags — `is_stubble_season` (Oct 15 - Nov 30), `is_winter_inversion` (Dec 1 - Feb 15), `is_diwali_week` (plus/minus 3 days), `wind_from_northwest` (270-360 deg, Punjab smoke direction), `is_extreme_aqi` (AQI > 300)

Prophet consumes from the store directly — adding a feature doesn't require model code changes."

---

## 8. "How do you handle data quality?"

"Three dimensions:

1. **Completeness** — percentage of non-null values per source per pollutant field. Some CPCB stations go offline; this catches it.
2. **Freshness** — staleness detection per station. How many minutes since the last reading? Anything over 1 hour gets flagged.
3. **Consistency** — cross-source validation. Do OpenWeatherMap and ground station PM2.5 readings agree? I compute average absolute delta and percentage difference per location.

Each source gets a letter grade (A through F). The AI agent references data quality in its advisory — if a station is offline or readings diverge, the advisory says so. Transparency builds trust."

---

## 9. "Walk me through the anomaly detection."

"Three methods, each catching different things:

1. **Z-score** — simple deviation from mean per station. Good baseline, catches obvious outliers.
2. **IQR** — robust to Delhi's heavily right-skewed AQI distribution. Z-score gets fooled by skewness; IQR doesn't.
3. **STL decomposition** — the key one. It separates the time series into trend + seasonal + residual components. The seasonal component captures daily cycles (morning/evening peaks) and weekly patterns (weekday vs weekend). Anomalies are detected in the *residual* — genuinely unusual events after accounting for normal patterns.

The insight: PM2.5 of 300 in November is bad but seasonal — the STL seasonal component explains it. PM2.5 of 300 in July is a genuine anomaly worth investigating because it's abnormal for that season.

Severity thresholds adjust by season. In winter (when baselines are naturally high), the sigma multiplier is 1.4x wider than in monsoon. This prevents winter from being wall-to-wall 'critical' alerts."

---

## 10. "How would you scale this?"

"Five changes for production scale:

1. **Replace PostgreSQL with BigQuery/Snowflake** — columnar storage for time series analytics, auto-scaling
2. **Prefect local to Prefect Cloud** — managed orchestration, monitoring, alerting
3. **Add Kafka** for real-time streaming from actual CPCB stations instead of batch
4. **Containerize with Docker Compose** — PostgreSQL + Prefect + Streamlit in isolated services
5. **Add Twilio/WhatsApp alerting** for health advisories when AQI breaches severity thresholds

The feature store pattern already enables this — it's decoupled from the model, versioned with timestamps, and the schema supports horizontal scaling per location."

---

## 11. "What would you do differently with more time?"

"Four things:

1. **Real CPCB data** — integrate with actual Central Pollution Control Board API instead of simulated sensors. The simulator is realistic but nothing beats real data.
2. **Model registry with MLflow** — version Prophet models, track MAPE over time, A/B test hyperparameters
3. **Spatial interpolation** — use kriging or IDW to estimate AQI at arbitrary coordinates between the 7 stations, producing a continuous pollution surface across Delhi NCR
4. **Causal inference beyond Granger** — add PCMCI (a causal discovery algorithm from tigramite) to handle confounders and non-linear relationships"

---

## 12. "What was the hardest part?"

"Two things:

1. **Getting the seasonal anomaly detection right.** Delhi's AQI distribution is heavily right-skewed and has extreme seasonal variation — PM2.5 ranges from 30 in monsoon to 500+ in winter. A one-size-fits-all threshold either misses everything in winter or fires constantly. The solution was combining STL decomposition (to strip out seasonality) with season-adjusted sigma multipliers, so November 300 and July 300 get different severity classifications.

2. **Aligning three data sources by location and time.** OpenWeatherMap returns data at slightly different timestamps per API call, ground stations report at their own cadence, and the simulated sensors generate at exact hours. The alignment logic — truncating to hour boundaries, handling missing readings, and ensuring the feature store joins correctly — required careful thought about temporal semantics."

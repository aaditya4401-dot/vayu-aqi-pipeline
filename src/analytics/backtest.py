"""Rolling-origin backtest of 24-hour AQI forecasts against naive baselines.

Usage: python -m src.analytics.backtest [--origins 10]

For each station and each of the last N daily origins, Prophet is trained on data before
the origin and scored on the next 24 hours, next to two baselines: persistence (repeat the
last observed value) and same-hour-yesterday. Reports MAE and AQI category accuracy.
"""

import argparse
import logging
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

from src.analytics.forecasting import _load_aqi_series
from src.ingestion.validators import classify_aqi

HORIZON_HOURS = 24
MIN_TRAIN_ROWS = 100
MIN_TEST_ROWS = 12


def _category(aqi: float) -> str:
    """Indian AQI category for a (clamped) AQI value."""
    return classify_aqi(int(round(min(500, max(0, aqi))))).value


def run_backtest(origins: int = 10) -> pd.DataFrame:
    """Run the rolling backtest.

    Args:
        origins: Number of daily forecast origins, counted back from the latest full day.

    Returns:
        One row per model with n, MAE, and category accuracy (percent).
    """
    from prophet import Prophet

    warnings.filterwarnings("ignore")
    logging.getLogger("cmdstanpy").setLevel(logging.CRITICAL)
    logging.getLogger("prophet").setLevel(logging.CRITICAL)

    series = _load_aqi_series()
    series = series[series["timestamp"] <= datetime.utcnow()]
    last_day = series["timestamp"].max().floor("D")
    starts = [last_day - pd.Timedelta(days=d) for d in range(origins, 0, -1)]

    scores: dict[str, list[tuple[float, bool]]] = {"prophet": [], "persistence": [], "yesterday": []}
    for _, group in series.groupby("location_id"):
        s = group.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")["aqi"]
        for origin in starts:
            train = s[s.index < origin]
            test = s[(s.index >= origin) & (s.index < origin + pd.Timedelta(hours=HORIZON_HOURS))]
            if len(train) < MIN_TRAIN_ROWS or len(test) < MIN_TEST_ROWS:
                continue
            model = Prophet(daily_seasonality=True, weekly_seasonality=False, yearly_seasonality=False)
            model.fit(train.reset_index().rename(columns={"timestamp": "ds", "aqi": "y"}))
            prophet_pred = model.predict(pd.DataFrame({"ds": test.index})).set_index("ds")["yhat"].clip(0, 500).values
            preds = {
                "prophet": prophet_pred,
                "persistence": np.full(len(test), train.iloc[-1], dtype=float),
                "yesterday": train.reindex(test.index - pd.Timedelta(hours=24)).values,
            }
            for name, pred in preds.items():
                ok = ~np.isnan(pred)
                scores[name] += [(abs(t - p), _category(t) == _category(p)) for t, p in zip(test.values[ok], pred[ok])]

    return pd.DataFrame(
        [
            {"model": name, "n": len(v), "mae": np.mean([x[0] for x in v]), "category_accuracy_pct": np.mean([x[1] for x in v]) * 100}
            for name, v in scores.items() if v
        ]
    ).round(1)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Backtest 24h AQI forecasts against baselines.")
    parser.add_argument("--origins", type=int, default=10, help="Daily forecast origins (default 10)")
    args = parser.parse_args()
    print(run_backtest(args.origins).to_string(index=False))


if __name__ == "__main__":
    main()

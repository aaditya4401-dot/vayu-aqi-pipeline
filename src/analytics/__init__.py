"""Vayu analytics / data science layer.

Modules:
- anomaly_detection: Z-score, IQR, STL seasonal decomposition
- causality: Granger causality testing (weather -> AQI)
- feature_store: Engineered features (lag, rolling, interactions, Delhi flags)
- forecasting: Prophet AQI forecasting with feature store regressors
- data_quality: Completeness, freshness, consistency scoring
"""

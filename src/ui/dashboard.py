"""Main dashboard page: header, ten tabs, footer."""

import logging
from collections.abc import Callable

import streamlit as st

from src.ui.helpers import format_ist, utc_now
from src.ui.theme import note
from src.ui.views import analytics, live, ops

logger = logging.getLogger(__name__)

TABS: list[tuple[str, Callable[[], None]]] = [
    ("Overview", live.render_overview),
    ("AQI Trends", live.render_trends),
    ("Pollutants", live.render_pollutants),
    ("Anomalies", analytics.render_anomalies),
    ("Forecast", analytics.render_forecast),
    ("Causality", analytics.render_causality),
    ("Features", analytics.render_features),
    ("Advisory", ops.render_advisory),
    ("Data Quality", ops.render_data_quality),
    ("Pipeline", ops.render_pipeline),
]


def _render_safely(renderer: Callable[[], None]) -> None:
    """Run one tab renderer; show a note instead of crashing the whole page on failure."""
    try:
        renderer()
    except Exception as exc:  # noqa: BLE001 - one broken tab must not take down the rest
        logger.exception("Tab %s failed", renderer.__name__)
        note("This tab could not load", f"{type(exc).__name__}: {exc}")


def render_dashboard() -> None:
    """Render the full Vayu dashboard page."""
    brand, clock = st.columns([3, 1])
    with brand:
        st.markdown("# VAYU")
        st.caption("Delhi NCR air quality intelligence. Seven monitoring zones, updated each pipeline run.")
    with clock:
        st.caption(f"As of {format_ist(utc_now())}")
        if st.button("Refresh data"):
            st.cache_data.clear()
            st.rerun()

    for tab, (_, renderer) in zip(st.tabs([label for label, _ in TABS]), TABS):
        with tab:
            _render_safely(renderer)

    st.divider()
    st.caption(
        "Data: OpenWeatherMap, OpenAQ, Open-Meteo and simulated CPCB-style stations. "
        "Built with Prefect, dbt, Prophet, GPT-4o-mini and Streamlit. Information only, not medical advice."
    )

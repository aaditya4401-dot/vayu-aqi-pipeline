"""Vayu: Delhi Air Quality Intelligence Dashboard (Streamlit entry point).

Run with: python -m streamlit run src/ui/app.py
Pages: Dashboard (ten tabs), Terms of Service, Privacy Policy.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.ui.dashboard import render_dashboard  # noqa: E402
from src.ui.theme import apply_theme  # noqa: E402
from src.ui.views.legal import render_privacy, render_terms  # noqa: E402

st.set_page_config(
    page_title="Vayu: Delhi Air Quality Intelligence",
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_theme()

page = st.navigation(
    [
        st.Page(render_dashboard, title="Dashboard", url_path="dashboard", default=True),
        st.Page(render_terms, title="Terms of Service", url_path="terms"),
        st.Page(render_privacy, title="Privacy Policy", url_path="privacy"),
    ],
    position="top",
)
page.run()

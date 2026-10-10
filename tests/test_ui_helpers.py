"""Tests for dashboard helpers: IST display, AQI categories, Delhi season context."""

from datetime import date

import pandas as pd
import pytest

from src.ui.helpers import (
    aqi_category, format_ist, is_northwest_wind, plain_copy, season_context, to_ist,
)


@pytest.mark.parametrize(
    "aqi,expected",
    [(0, "Good"), (50, "Good"), (51, "Satisfactory"), (100, "Satisfactory"), (101, "Moderate"),
     (200, "Moderate"), (201, "Poor"), (300, "Poor"), (301, "Very Poor"), (400, "Very Poor"),
     (401, "Severe"), (500, "Severe"), (620, "Severe"), (-5, "Good")],
)
def test_aqi_category_boundaries(aqi: int, expected: str) -> None:
    assert aqi_category(aqi) == expected


def test_to_ist_shifts_utc_by_five_thirty() -> None:
    out = to_ist(pd.Series(pd.to_datetime(["2026-10-09 18:30:00"])))
    assert out.iloc[0] == pd.Timestamp("2026-10-10 00:00:00")


def test_format_ist_labels_timezone() -> None:
    assert format_ist(pd.Timestamp("2026-10-09 06:30:00")) == "09 Oct 2026, 12:00 PM IST"


@pytest.mark.parametrize(
    "day,headline",
    [(date(2026, 10, 15), "Stubble burning season"), (date(2026, 11, 30), "Stubble burning season"),
     (date(2026, 12, 1), "Winter inversion period"), (date(2027, 2, 15), "Winter inversion period"),
     (date(2026, 7, 1), "Outside peak pollution seasons")],
)
def test_season_context(day: date, headline: str) -> None:
    assert season_context(day)[0] == headline


def test_season_countdown_before_stubble() -> None:
    assert season_context(date(2026, 10, 9))[0] == "Stubble burning season starts in 6 days"


@pytest.mark.parametrize("deg,expected", [(269, False), (270, True), (315, True), (360, True), (0, False), (90, False)])
def test_northwest_wind(deg: float, expected: bool) -> None:
    assert is_northwest_wind(deg) is expected


def test_plain_copy_removes_em_dashes() -> None:
    assert "—" not in plain_copy("Poor air — stay indoors")

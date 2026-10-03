"""
Tests for India NAQI calculator.
Run: python -m pytest pipeline/test_aqi_calc.py -v
"""

import pytest
from .aqi_calc import calculate, _sub_index


class TestSubIndex:
    def test_pm25_good(self):
        assert _sub_index("pm25", 15.0) == 25

    def test_pm25_satisfactory(self):
        idx = _sub_index("pm25", 45.0)
        assert 51 <= idx <= 100

    def test_pm25_severe(self):
        assert _sub_index("pm25", 400.0) == 500

    def test_pm10_good(self):
        assert _sub_index("pm10", 25.0) == 25

    def test_co_mg_per_m3(self):
        # CO uses mg/m³ breakpoints — 1.0 mg/m³ = top of Good range
        assert _sub_index("co", 1.0) == 50

    def test_unknown_pollutant(self):
        assert _sub_index("lead", 100.0) is None

    def test_negative_concentration(self):
        assert _sub_index("pm25", -5.0) is None

    def test_above_max_breakpoint(self):
        assert _sub_index("pm25", 9999.0) == 500


class TestCalculate:
    def test_returns_none_when_no_data(self):
        assert calculate() is None

    def test_single_pollutant(self):
        result = calculate(pm25=15.0)
        assert result is not None
        assert result.aqi == 25
        assert result.category == "Good"
        assert result.dominant_pollutant == "pm25"

    def test_dominant_is_max(self):
        # pm10 sub-index will be higher than pm25 here
        result = calculate(pm25=15.0, pm10=200.0)
        assert result is not None
        assert result.dominant_pollutant == "pm10"

    def test_categories(self):
        cases = [
            (25.0, None, "Good"),
            (50.0, None, "Satisfactory"),
            (75.0, None, "Moderate"),
            (100.0, None, "Poor"),
            (150.0, None, "Very Poor"),
            (300.0, None, "Severe"),
        ]
        for pm25, pm10, expected_cat in cases:
            result = calculate(pm25=pm25)
            assert result.category == expected_cat, f"pm25={pm25}: expected {expected_cat}, got {result.category}"

    def test_sub_indices_populated(self):
        result = calculate(pm25=60.0, pm10=80.0, no2=50.0)
        assert "pm25" in result.sub_indices
        assert "pm10" in result.sub_indices
        assert "no2" in result.sub_indices
        assert len(result.sub_indices) == 3

    def test_none_values_ignored(self):
        result = calculate(pm25=None, pm10=50.0, no2=None)
        assert result is not None
        assert "pm25" not in result.sub_indices
        assert "pm10" in result.sub_indices

    def test_real_delhi_reading(self):
        # Typical Delhi winter: very unhealthy
        result = calculate(pm25=180.0, pm10=320.0, no2=85.0, so2=30.0)
        assert result is not None
        assert result.aqi >= 200
        assert result.category in ("Poor", "Very Poor", "Severe")

"""
Tests for the data cleaner.
Run: python -m pytest pipeline/test_cleaner.py -v
"""

import pytest
from .cleaner import clean, clean_batch


def _base_record(**overrides):
    base = {
        "location_name": "Anand Vihar",
        "latitude": 28.6466,
        "longitude": 77.3152,
        "source": "openaq",
        "pm25": 85.0,
        "pm10": 160.0,
        "no2": 55.0,
        "so2": None,
        "co": None,
        "o3": None,
        "nh3": None,
        "timestamp": "2026-03-26T10:00:00+00:00",
        "raw": {},
    }
    base.update(overrides)
    return base


class TestClean:
    def test_valid_record_passes(self):
        result = clean(_base_record())
        assert result is not None
        assert result["station_name"] == "Anand Vihar"
        assert result["aqi"] is not None
        assert result["category"] is not None

    def test_missing_name_dropped(self):
        assert clean(_base_record(location_name="")) is None

    def test_missing_coordinates_dropped(self):
        assert clean(_base_record(latitude=None)) is None
        assert clean(_base_record(longitude=None)) is None

    def test_no_pm_data_dropped(self):
        assert clean(_base_record(pm25=None, pm10=None)) is None

    def test_out_of_bounds_pm25_discarded_not_record(self):
        # pm25 is out of bounds but pm10 is valid — record survives, pm25 set to None
        result = clean(_base_record(pm25=9999.0, pm10=100.0))
        assert result is not None
        assert result["pm25"] is None
        assert result["pm10"] == 100.0

    def test_out_of_bounds_both_pm_drops_record(self):
        assert clean(_base_record(pm25=-1.0, pm10=9999.0)) is None

    def test_timestamp_normalized_to_iso(self):
        result = clean(_base_record(timestamp="2026-03-26T10:00:00Z"))
        assert result is not None
        assert "+" in result["timestamp"] or result["timestamp"].endswith("Z") or "UTC" not in result["timestamp"]

    def test_missing_timestamp_uses_now(self):
        result = clean(_base_record(timestamp=None))
        assert result is not None
        assert result["timestamp"] is not None

    def test_aqi_calculated_correctly(self):
        # pm25=85 → sub-index in Poor range (201-300)
        result = clean(_base_record(pm25=85.0, pm10=None))
        assert result["aqi"] > 100

    def test_source_preserved(self):
        result = clean(_base_record(source="cpcb"))
        assert result["source"] == "cpcb"


class TestCleanBatch:
    def test_valid_batch(self):
        records = [_base_record(location_name=f"Station {i}") for i in range(5)]
        cleaned = clean_batch(records)
        assert len(cleaned) == 5

    def test_drops_invalid_silently(self):
        records = [
            _base_record(),
            _base_record(location_name=""),    # invalid
            _base_record(latitude=None),        # invalid
            _base_record(location_name="Valid Station 2"),
        ]
        cleaned = clean_batch(records)
        assert len(cleaned) == 2

    def test_empty_batch(self):
        assert clean_batch([]) == []

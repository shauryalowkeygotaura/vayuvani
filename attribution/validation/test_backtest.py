"""Backtest report runs on an empty store and on synthetic attributions."""

from attribution import synthetic
from attribution.engine import attribute
from attribution.store import LocalStore
from attribution.validation import backtest


def test_report_empty_store(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    p = backtest.write_report("2025-10-01", "2025-11-30", store=s, out_path=str(tmp_path / "R.md"))
    text = open(p, encoding="utf-8").read()
    assert "no data" in text and "Not run" in text and "Honest limits" in text


def test_report_with_records(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    obs, wind = synthetic.generate()
    s.upsert("kaun_stations", [{"id": k, **v} for k, v in synthetic.STATIONS.items()])
    s.upsert("attributions", attribute.run(obs, wind, [], synthetic.STATIONS))
    p = backtest.write_report("2026-10-01", "2026-11-02", store=s, out_path=str(tmp_path / "R.md"))
    text = open(p, encoding="utf-8").read()
    assert "Attributions in range:" in text
    assert "Sub-grid spikes" in text

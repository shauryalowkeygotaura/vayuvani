"""Evidence fusion and upwind land use."""

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from attribution.engine import fusion
from attribution.ingest import landuse

H = [pd.Timestamp("2026-11-01T15:00:00Z")]   # 20:30 IST


def test_fuse_is_a_distribution_and_explains_itself():
    out = fusion.fuse({"a": {"traffic": 2.0}, "b": {"traffic": 1.0, "dust": 0.5}, "c": {"industry": 0.2}})
    assert math.isclose(sum(out["posterior"].values()), 1.0, abs_tol=1e-3)
    assert out["top"] == "traffic" and out["agreeing_terms"] == 2
    assert set(out["terms"]) == {"a", "b", "c"}
    assert 0 <= out["entropy"] <= 1


def test_no_evidence_is_uniform():
    out = fusion.fuse({})
    assert max(out["posterior"].values()) - min(out["posterior"].values()) < 1e-6


def test_fresh_no_favours_traffic():
    assert fusion.term_fresh_no({"no": 60.0, "no2": 60.0})["traffic"] > 0      # NO-rich (~0.6 by moles)
    assert fusion.term_fresh_no({"no": 5.0, "no2": 120.0})["traffic"] < 0      # aged
    assert fusion.term_fresh_no({"no": None, "no2": 50.0}) == {}
    assert fusion.term_fresh_no({"no": 1.0, "no2": 2.0}) == {}                 # too small to read


def test_humid_fine_weak_combustion_is_secondary():
    r = {"fine_fraction": 0.85, "pct_co_pm": 0.2, "pct_no2_pm": 0.2}
    humid = fusion.term_secondary(r, 92.0)
    dry = fusion.term_secondary(r, 35.0)
    assert humid["secondary"] > 0 > dry["secondary"]
    assert humid["biomass_burning"] < 0


def test_cold_night_favours_burning():
    t = fusion.term_time_temp(H, traffic_prior=0.5, temp=11.0)
    assert t["biomass_burning"] > 0
    assert "biomass_burning" not in fusion.term_time_temp(H, 0.5, 25.0)


def test_landuse_upwind_enrichment():
    grid = {f: {s: 0.0 for s in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")} for f in landuse.FEATURES}
    grid["landfill"]["E"] = 2.0
    grid["industrial"]["W"] = 3.0
    east = fusion.term_landuse(grid, {"sector": "E", "calm": False})
    west = fusion.term_landuse(grid, {"sector": "W", "calm": False})
    assert east["biomass_burning"] > 0 and east["industry"] < 0
    assert west["industry"] > 0 and west["biomass_burning"] < 0
    assert fusion.term_landuse(grid, {"sector": None, "calm": True}) == {}


def test_landuse_calm_uses_neighbourhood_vs_fleet():
    grid = {f: {s: 0.0 for s in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")} for f in landuse.FEATURES}
    grid["near"] = {f: 0.0 for f in landuse.FEATURES}
    grid["near"]["industrial"] = 4.0            # Bawana-like: industry all around
    fleet = {f: 0.0 for f in landuse.FEATURES}
    fleet["industrial"] = 0.5
    fleet["roads"] = 20.0
    calm = {"sector": None, "calm": True}
    t = fusion.term_landuse(grid, calm, fleet)
    assert t["industry"] > 0 and t["traffic"] < 0   # fewer arterial roads than typical
    assert fusion.term_landuse(grid, calm) == {}       # no fleet reference: no claim
    assert fusion.term_landuse({"roads": {"N": 1.0}}, calm, fleet) == {}   # v1 grid has no neighbourhood


def test_named_candidates_follow_the_wind():
    grid = {"features": [
        {"name": "Sector 3", "feature": "industrial", "km": 0.9, "sector": "N"},
        {"name": "Pragati-III", "feature": "power", "km": 3.0, "sector": "NE"},
        {"name": "Ghazipur landfill", "feature": "landfill", "km": 6.0, "sector": "E"},
        {"name": "Far works", "feature": "industrial", "km": 9.0, "sector": "SW"},
    ]}
    ne = landuse.candidates(grid, "industry", {"sector": "NE", "calm": False})
    assert [c["name"] for c in ne] == ["Pragati-III", "Sector 3"]        # sector first, then neighbours
    calm = landuse.candidates(grid, "industry", {"sector": None, "calm": True})
    assert [c["name"] for c in calm] == ["Sector 3", "Pragati-III"]      # within 4 km, nearest first
    assert landuse.candidates(grid, "biomass_burning", {"sector": "E", "calm": False})[0]["type"] == "landfill / waste site"
    assert landuse.candidates(grid, "secondary", {"sector": "E"}) == []
    assert landuse.candidates(None, "industry", {"sector": "E"}) == []


def test_cbpf_marker_signature():
    cb = {"so2": {"N": 0.1, "NE": 0.1, "E": 0.7, "SE": 0.1, "S": 0.1, "SW": 0.1, "W": 0.1, "NW": 0.1}}
    assert fusion.term_cbpf(cb, {"sector": "E"})["industry"] > 0
    assert fusion.term_cbpf(cb, {"sector": "W"})["industry"] < 0


def test_overpass_query_whitelisted():
    q = landuse.build_query(28.5308, 77.2713)
    assert q.startswith("[out:json]") and "around:10000,28.53080,77.27130" in q
    with pytest.raises(ValueError):
        landuse.build_query(51.5, -0.1)          # outside NCR
    with pytest.raises((ValueError, TypeError)):
        landuse.build_query("28.5);out;", 77.2)  # injection attempt never reaches the string


def test_landuse_summarise_overpass_shape():
    payload = {"elements": [
        {"type": "way", "id": 1, "tags": {"landuse": "landfill"}, "center": {"lat": 28.5308, "lon": 77.2913}},
        {"type": "way", "id": 1, "tags": {"landuse": "landfill"}, "center": {"lat": 28.5308, "lon": 77.2913}},
        {"type": "node", "id": 2, "tags": {"power": "plant"}, "lat": 28.60, "lon": 77.2713},
        {"type": "way", "id": 3, "tags": {"highway": "trunk"},
         "geometry": [{"lat": 28.5208, "lon": 77.2613}, {"lat": 28.5208, "lon": 77.2813}]},
        {"type": "way", "id": 4, "tags": {"shop": "x"}, "center": {"lat": 28.53, "lon": 77.27}},
    ]}
    g = landuse.summarise(payload, 28.5308, 77.2713)
    assert g["landfill"]["E"] == 1.0                       # ~2 km east, deduplicated
    assert g["power"]["N"] == 0.25                         # ~7.7 km north
    assert sum(g["roads"].values()) > 1.0                  # ~2 km of trunk road south
    with pytest.raises(Exception):
        landuse.summarise({"remark": "runtime error"}, 28.5, 77.2)


def test_landuse_refresh_caches(tmp_path, monkeypatch):
    from attribution.store import LocalStore
    s = LocalStore(str(tmp_path))
    calls = []
    monkeypatch.setattr(landuse, "fetch_station",
                        lambda lat, lon: calls.append(1) or {"roads": {"N": 1.0}, "version": landuse.VERSION})
    monkeypatch.setattr(landuse.time, "sleep", lambda x: None)
    st = [{"id": f"s{i}", "latitude": 28.6, "longitude": 77.2} for i in range(3)]
    assert landuse.refresh(s, st, per_run=2) == 2
    assert landuse.refresh(s, st, per_run=2) == 1
    assert landuse.refresh(s, st, per_run=2) == 0
    assert set(landuse.load(s)) == {"s0", "s1", "s2"}

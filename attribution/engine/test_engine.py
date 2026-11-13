"""Engine tests on synthetic data with known injected spikes."""

import numpy as np
import pandas as pd
import pytest

from attribution import synthetic
from attribution.engine import attribute, confidence, factors, fingerprints, regional, spikes, wind_sector


@pytest.fixture(scope="module")
def records():
    obs, wind = synthetic.generate()
    return attribute.run(obs, wind, [], synthetic.STATIONS)


def _injected(records, sid):
    """The multi-hour window at an injected station (noise spikes are single-hour)."""
    wins = [r for r in records if r["station_id"] == sid and r["n_hours"] >= 2]
    assert wins, f"no multi-hour spike found at {sid}"
    return max(wins, key=lambda r: r["excess_pm25"])


@pytest.mark.parametrize("sid,kind", [(k, v[3]) for k, v in synthetic.SPIKES.items()])
def test_injected_spike_type_recovered(records, sid, kind):
    r = _injected(records, sid)
    assert r["top_source"] == kind, r["shares"]


def test_every_record_has_confidence_and_valid_shares(records):
    assert records
    for r in records:
        assert r["confidence"] in ("low", "medium", "high")
        if r["shares"]:
            assert sum(r["shares"].values()) == pytest.approx(1.0, abs=0.01)
        assert r["summary_en"].endswith(f"confidence {r['confidence']}.")


def test_burning_spike_sector_is_east(records):
    r = _injected(records, "anand-vihar-delhi-dpcc")
    assert r["sector"] == "E"


def test_records_are_json_serialisable(records):
    import json
    from attribution.store import clean_rows
    json.dumps(clean_rows(records), allow_nan=False)


def test_spike_detector_flat_series_no_spikes():
    hours = pd.date_range("2026-10-01", periods=24 * 10, freq="h", tz="UTC")
    obs = pd.DataFrame({"station_id": "a", "hour": hours, "pm25": 100.0, "pm10": 180.0})
    flagged = spikes.detect(obs)
    assert not flagged["is_spike"].any()
    obs.loc[obs.index[-1], "pm25"] = 220.0
    flagged = spikes.detect(obs)
    assert flagged["is_spike"].sum() == 1
    assert flagged.loc[flagged["is_spike"], "baseline_kind"].iloc[0] == "same-hour-7d"


def test_windows_grouping():
    h = pd.date_range("2026-10-01", periods=10, freq="h", tz="UTC")
    df = pd.DataFrame({"station_id": "a", "hour": h,
                       "is_spike": [0, 1, 1, 0, 1, 0, 0, 0, 1, 0]}).astype({"is_spike": bool})
    w = spikes.windows(df)
    assert [len(x["hours"]) for x in w] == [3, 1]          # gap of 1 hour bridged


def test_sectors_and_vector_mean():
    assert wind_sector.sector_of(0) == "N" and wind_sector.sector_of(359) == "N"
    assert wind_sector.sector_of(90) == "E" and wind_sector.sector_of(225) == "SW"
    mean, r, _ = wind_sector.vector_mean([350, 10], [2, 2])
    assert (mean < 1 or mean > 359) and r > 0.95


def test_confidence_caps():
    base = dict(species_present=5, nmf_top="traffic", top="traffic",
                wind={"sector": "E", "steadiness": 0.9}, n_hours=3, baseline_kind="same-hour-7d", pbl_drop=None)
    assert confidence.grade(shares={"traffic": 0.8, "dust": 0.2}, **base)[0] == "high"
    lvl, why = confidence.grade(shares={"traffic": 0.4, "dust": 0.3, "industry": 0.3}, **base)
    assert lvl != "high"
    assert confidence.grade(shares={"traffic": 1.0}, **{**base, "species_present": 2})[0] == "low"
    assert confidence.grade(shares={}, **base)[0] == "low"
    lvl, why = confidence.grade(shares={"traffic": 0.9}, **{**base, "n_hours": 1}, excess_ratio=0.1)
    assert lvl == "low"


def test_fingerprint_traffic_vs_smoke():
    hist = {"no2_pm": np.linspace(0.0, 0.6, 200), "co_pm": np.linspace(0.0, 0.01, 200),
            "so2_pm": np.linspace(0, 0.1, 200)}
    traffic = fingerprints.score({"pm25": 50, "pm10": 70, "no2": 80, "co": 1.5, "so2": 0},
                                 {"pm25": 150, "pm10": 250}, hist, 1.0)
    smoke = fingerprints.score({"pm25": 150, "pm10": 170, "no2": 2, "co": 0.6, "so2": 0},
                               {"pm25": 250, "pm10": 330}, hist, 0.3)
    assert max(traffic["shares"], key=traffic["shares"].get) == "traffic"
    assert max(smoke["shares"], key=smoke["shares"].get) == "biomass_burning"


def test_regional_share_and_upwind_fires():
    hours = pd.date_range("2026-10-01", periods=24 * 8, freq="h", tz="UTC")
    bg = pd.Series(80.0, index=hours)
    bg.iloc[-1] = 140.0
    assert regional.regional_share(60.0, [hours[-1]], bg) == pytest.approx(1.0)
    assert regional.regional_share(120.0, [hours[-1]], bg) == pytest.approx(0.5)
    wind = pd.DataFrame({"hour": hours[-24:], "wind_dir": 315.0, "wind_speed": 3.0})
    fires = [{"acq_time": hours[-5], "bearing_from_delhi": 310.0, "frp": 10.0}] * 20 + \
            [{"acq_time": hours[-5], "bearing_from_delhi": 120.0, "frp": 10.0}] * 5
    up = regional.upwind_fires(fires, wind, hours[-1])
    assert up["count"] == 20
    assert regional.is_transported(0.5, up) and not regional.is_transported(0.1, up)
    calm = dict(up, mean_speed_ms=0.8)
    assert not regional.is_transported(0.5, calm)       # stagnant air cannot carry smoke 200 km


def test_every_record_explains_its_cause(records):
    for r in records:
        c = r["cause"]
        assert set(c) >= {"top", "shares", "local", "regional", "text_en", "text_hi"}
        assert c["regional"]["mechanism"] in ("stagnation", "transport", "regional_rise", "unclear")
        if c["shares"]:
            assert sum(c["shares"].values()) == pytest.approx(1.0, abs=0.01)
            assert c["top"] in c["shares"]
        assert c["text_en"] and c["text_hi"]


def test_build_cause_folds_regional_composition():
    local = {"industry": 0.8, "traffic": 0.2}
    prof = {"mechanism": "stagnation", "composition": {"biomass_burning": 0.7, "traffic": 0.3},
            "wind_ms": 0.4, "pbl_ratio": 0.5, "stagnant": True, "upwind_fires": 0, "n_stations": 30}
    wind = {"sector": "N", "calm": False}
    c = attribute.build_cause(local, "industry", 0.5, False, prof, [{"name": "X", "type": "power plant", "km": 2.0, "sector": "N"}], wind)
    assert c["shares"]["industry"] == pytest.approx(0.4, abs=0.01)
    assert c["shares"]["biomass_burning"] == pytest.approx(0.35, abs=0.01)
    assert c["top"] == "industry" and c["local"]["top"] == "industry" and c["local"]["candidates"]
    assert c["regional"]["mechanism"] == "stagnation"
    en, hi = attribute._cause_text(c)
    assert "stagnant" in en and "X (power plant, 2 km)" in en and "ठहरी" in hi
    # Mostly regional, transported: the regional part is smoke, nothing local to name.
    c2 = attribute.build_cause(local, "industry", 0.9, True, dict(prof, mechanism="transport", upwind_fires=40), [], wind)
    assert c2["top"] == "transported_smoke" and c2["local"]["top"] is None and c2["local"]["candidates"] == []
    assert "fires upwind" in attribute._cause_text(c2)[0]
    # No regional part at all.
    c3 = attribute.build_cause(local, "industry", None, False, {"mechanism": "unclear", "composition": {}}, [], wind)
    assert c3["shares"] == {"industry": 0.8, "traffic": 0.2} and c3["regional"]["share"] == 0


def test_regional_profile_reads_stagnation():
    obs, wind = synthetic.generate(days=10)
    data = attribute.merge_obs(obs, wind)
    flagged = spikes.detect(data)
    last = flagged["hour"].max()
    hours = [last - pd.Timedelta(hours=1), last]
    calm = flagged.copy()
    calm.loc[calm["hour"].isin(hours), "wind_speed"] = 0.3
    calm.loc[calm["hour"].isin(hours), "pbl_height"] = 50.0
    calm.loc[~calm["hour"].isin(hours), "pbl_height"] = 800.0
    p = regional.regional_profile(calm, hours, hours[0], {"count": 0}, False)
    assert p["n_stations"] == len(synthetic.STATIONS)
    assert p["mechanism"] == "stagnation" and p["stagnant"] is True
    assert p["wind_ms"] == pytest.approx(0.3) and p["pbl_ratio"] < 0.2
    assert isinstance(p["composition"], dict)
    windy = regional.regional_profile(flagged, hours, hours[0], {"count": 30}, True)
    assert windy["mechanism"] == "transport"
    few = regional.regional_profile(flagged.loc[flagged["station_id"] == "mundka-delhi-dpcc"], hours, hours[0], {}, False)
    assert few["mechanism"] == "unclear" and few["composition"] == {}


def test_nmf_deterministic():
    obs, _ = synthetic.generate(days=10)
    st = obs.loc[obs["station_id"] == "r-k-puram-delhi-dpcc"]
    a, b = factors.fit(st), factors.fit(st)
    assert a is not None and a["labels"] == b["labels"]
    assert np.allclose(a["H"].to_numpy(), b["H"].to_numpy())


def test_second_signal_rules():
    ss = fingerprints.second_signal
    assert ss("traffic", {}, None) is None
    assert ss("industry", {"so2": 80, "co": 0.3}, None) is True       # sulphur-rich
    assert ss("industry", {"so2": 8, "co": 1.0}, None) is False       # SO2 just riding combustion
    assert ss("dust", {"co": 1.0, "no2": 40}, 4.0) is True             # windy resuspension
    assert ss("dust", {"co": 1.0, "no2": 40}, 1.0) is False            # combustion co-signal, calm
    assert ss("dust", {"co": 0.1, "no2": 3}, 1.0) is True


def test_confidence_drops_without_second_signal():
    base = dict(species_present=5, nmf_top="industry", top="industry",
                wind={"sector": "E", "steadiness": 0.9}, n_hours=3, baseline_kind="same-hour-7d", pbl_drop=None)
    assert confidence.grade(shares={"industry": 0.8, "dust": 0.2}, **base, second_signal=True)[0] == "high"
    assert confidence.grade(shares={"industry": 0.8, "dust": 0.2}, **base, second_signal=False)[0] == "medium"

"""Answer-key check: toy model, no data files."""

import pandas as pd

from attribution.engine import answer_key as A

FEATS = list(A.FEATURES)


def _model(burn_coef: float) -> dict:
    zero = [0.0] * len(FEATS)
    def src(c):  # one live feature drives each toy source: CO per PM2.5
        coef = [c if f == "l_co_pm" else 0.0 for f in FEATS]
        return {"features": FEATS, "coef": coef, "intercept": 0.0, "mean": zero, "scale": [1.0] * len(FEATS),
                "impute": zero}
    return {"version": "toy", "validated": ["biomass_burning", "traffic"],
            "sources": {"biomass_burning": src(burn_coef), "traffic": src(-burn_coef), "dust": src(50.0)}}


def _flagged(co: float) -> tuple[pd.DataFrame, list, dict]:
    hours = list(pd.date_range("2026-11-10T14:00Z", periods=2, freq="h"))
    rows = []
    for sid in ("a", "b"):
        for h in hours:
            rows.append({"station_id": sid, "hour": h, "pm25": 200.0, "pm10": 300.0, "no2": 40.0, "co": co,
                         "so2": 10.0, "o3": 20.0, "no": 5.0, **{f"delta_{p}": 30.0 for p in
                         ("pm25", "pm10", "no2", "co", "so2", "o3", "no")}})
    st = {"a": {"latitude": 28.55, "longitude": 77.19}, "b": {"latitude": 28.56, "longitude": 77.19},
          "far": {"latitude": 28.75, "longitude": 77.10}}
    return pd.DataFrame(rows), hours, st


def test_confident_call_named_only_if_validated():
    flagged, hours, st = _flagged(co=20.0)            # log10(20/200) = -1
    ak = A.check(flagged, "a", hours, st, model=_model(-10.0))   # P(burning) = sigmoid(10) ~ 1
    assert ak["calls"] == ["biomass_burning"] and not ak["unsure"]
    assert "dust" not in ak["calls"]                   # p(dust) ~ 0 here, and never validated anyway
    assert ak["validated_area"] and ak["n_stations"] == 2
    en, hi = A.text(ak)
    assert "burning elevated" in en and "95%" in en and hi


def test_unsure_below_threshold_and_scope_text():
    flagged, hours, st = _flagged(co=200.0)            # log10(1) = 0 -> p = 0.5 for every source
    st["a"] = {"latitude": 28.75, "longitude": 77.10}  # move the station out of the validated area
    ak = A.check(flagged, "a", hours, st, model=_model(-10.0))
    assert ak["unsure"] and ak["calls"] == [] and not ak["validated_area"]
    en, _ = A.text(ak)
    assert "unsure" in en and "not validated at this station" in en


def test_outside_validated_area_names_burning_only():
    m = _model(-10.0)
    m["outside_validated"] = ["biomass_burning"]
    flagged, hours, st = _flagged(co=2000.0)           # log10(10) = 1 -> traffic ~1, burning ~0
    ak_in = A.check(flagged, "a", hours, st, model=m)
    assert ak_in["calls"] == ["traffic"]
    st["a"] = {"latitude": 28.75, "longitude": 77.10}
    ak_out = A.check(flagged, "a", hours, st, model=m)
    assert ak_out["calls"] == [] and ak_out["p_elevated"]["traffic"] > 0.95


def test_shipped_model_loads():
    m = A.load()
    assert m and set(m["validated"]) <= set(m["sources"])
    assert all(len(s["coef"]) == len(A.FEATURES) for s in m["sources"].values())

"""External (London) answer-key labelling, offline."""

import pandas as pd

from attribution.validation import external, london_deltas


def _rec(sid, start, end, top):
    return {"id": f"{sid}{start}", "station_id": sid, "window_start": start, "window_end": end,
            "confidence": "medium", "evidence": {"local_shares": {top: 0.9, "dust": 0.1}}}


def test_labels_bonfire_and_kerbside_traffic(monkeypatch):
    external.SITES.update({"MY1": ("Marylebone", 51.5225, -0.1546), "KC1": ("N Ken", 51.5210, -0.2135)})
    recs = [
        _rec("KC1", "2021-11-05T19:00:00+00:00", "2021-11-05T22:00:00+00:00", "biomass_burning"),
        _rec("MY1", "2021-11-03T08:00:00+00:00", "2021-11-03T10:00:00+00:00", "traffic"),        # Wednesday, KC1 quiet
        _rec("MY1", "2021-11-06T08:00:00+00:00", "2021-11-06T10:00:00+00:00", "traffic"),        # Saturday: no label
    ]
    rows = external.label(recs)
    assert [r["label"] for r in rows] == ["biomass_burning", "traffic", None]
    s = external.score(rows)
    assert s["biomass_burning"]["precision"] == 1.0 and s["traffic"]["recall"] == 1.0


def test_delta_features_physical():
    d = pd.DataFrame({"pm25": [20.0, 2.0], "pm10": [25.0, 3.0], "no2": [40.0, 1.0], "co": [0.2, 0.1],
                      "no": [30.0, 0.0], "so2": [1.0, 1.0]})
    f = london_deltas.features(d)
    assert len(f) == 1                                     # the 2 ug/m3 row is below the noise floor
    assert abs(f["l_no2_pm"].iloc[0] - 0.301) < 0.01 and 0 < f["no_frac"].iloc[0] < 1

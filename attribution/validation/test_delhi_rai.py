"""Offline tests for the Delhi answer-key helpers (no downloads)."""

import numpy as np
import pandas as pd

from attribution.validation import delhi_rai as R


def test_family_excess_and_labels():
    idx = pd.date_range("2019-01-20", periods=6, freq="h", tz="UTC")
    f = pd.DataFrame({c: 1.0 for cols in R.FAMILIES.values() for c in cols}, index=idx)
    f.loc[idx[2], "SFC1"] = 10.0                      # burning jumps in hour 2
    ex = R.family_excess(f)
    assert ex.loc[idx[2], "biomass_burning"] > R.MIN_RISE
    lab = R.label_hours(ex)
    assert lab.loc[idx[2]] == "biomass_burning" and pd.isna(lab.loc[idx[0]])


def test_curve_precision_and_coverage():
    p = np.array([[0.9, 0.1], [0.2, 0.8], [0.55, 0.45], [0.4, 0.6]])
    y = np.array(["not", "up", "up", "up"])
    c = {r["threshold"]: r for r in R.curve(np.repeat(p, 5, 0), np.array(["not", "up"]), np.repeat(y, 5))}
    assert c[0.0]["coverage"] == 1.0
    assert c[0.8]["precision"] == 1.0                 # only the two confident, correct calls remain

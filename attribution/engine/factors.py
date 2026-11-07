"""
Factor analysis: NMF on a rolling 30-day window per station.

PMF (EPA PMF 5.0) weights each value by its measurement uncertainty. CPCB
does not publish per-reading uncertainties, so this is plain NMF on columns
scaled by their standard deviation, which is the usual no-uncertainty
approximation. Fixed seed, multiplicative updates (Lee & Seung 2001): fully
deterministic and dependency-free (numpy only).

Factors are then labelled with the same fingerprint logic as spikes, applied
to each factor's profile. A factor dominated by O3 is labelled "secondary".
The factor result is corroboration: it raises confidence when it agrees with
the ratio fingerprint, and is never the sole basis for a share.
"""

from typing import Optional

import numpy as np
import pandas as pd

from ..config import NMF_COMPONENTS, NMF_MIN_ROWS

SPECIES = ("pm25", "pm10", "no2", "so2", "co", "o3")


def nmf(X: np.ndarray, k: int, iters: int = 400, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n, m = X.shape
    W = rng.random((n, k)) + 0.1
    H = rng.random((k, m)) + 0.1
    eps = 1e-9
    for _ in range(iters):
        H *= (W.T @ X) / (W.T @ W @ H + eps)
        W *= (X @ H.T) / (W @ H @ H.T + eps)
    return W, H


def _label(profile: dict[str, float], means: dict[str, float]) -> str:
    """profile and means in original units. Relative enrichment vs the station mean mix."""
    def rel(sp):
        if sp not in profile or not means.get(sp) or not means.get("pm25"):
            return None
        return (profile[sp] / max(profile.get("pm25", 0), 1e-9)) / (means[sp] / means["pm25"])

    pm_total = profile.get("pm25", 0) + profile.get("pm10", 0)
    o3_rel = rel("o3")
    if o3_rel is not None and o3_rel > 3 and profile.get("pm25", 0) < 0.2 * pm_total:
        return "secondary"
    fine = profile.get("pm25", 0) / profile["pm10"] if profile.get("pm10") else None
    so2_rel, no2_rel, co_rel = rel("so2"), rel("no2"), rel("co")
    if so2_rel is not None and so2_rel > 2.0:
        return "industry"
    if fine is not None and fine < 0.4:
        return "dust"
    if (no2_rel or 0) > 1.5 and (co_rel or 1) > 1.0:
        return "traffic"
    if fine is not None and fine >= 0.55:
        return "biomass_burning"
    return "mixed"


def fit(hist: pd.DataFrame) -> Optional[dict]:
    """
    hist: station rows (hour index or column) for the last NMF_WINDOW_DAYS.
    Returns {"labels": [...], "W": DataFrame(hour x factor), "H": ..., "species": [...]}
    """
    cols = [c for c in SPECIES if c in hist and hist[c].notna().mean() > 0.6]
    if "pm25" not in cols or len(cols) < 3:
        return None
    df = hist.set_index("hour")[cols].astype(float).dropna()
    df = df.loc[(df >= 0).all(axis=1)]
    if len(df) < NMF_MIN_ROWS:
        return None
    scale = df.std().replace(0, 1.0)
    X = (df / scale).to_numpy()
    k = min(NMF_COMPONENTS, len(cols) - 1)
    W, H = nmf(X, k)
    H_orig = H * scale.to_numpy()[None, :]
    means = df.mean().to_dict()
    labels = [_label(dict(zip(cols, H_orig[i])), means) for i in range(k)]
    return {
        "labels": labels,
        "W": pd.DataFrame(W, index=df.index),
        "H": pd.DataFrame(H_orig, columns=cols),
        "species": cols,
    }


def window_contrib(model: Optional[dict], hours) -> dict:
    """PM2.5 share by factor label over the window hours (labels merged)."""
    if not model:
        return {}
    W = model["W"].reindex(pd.DatetimeIndex(hours)).dropna()
    if W.empty:
        return {}
    pm = model["H"]["pm25"].to_numpy()
    contrib = (W.to_numpy() * pm[None, :]).sum(axis=0)
    total = contrib.sum()
    if total <= 0:
        return {}
    out: dict[str, float] = {}
    for lab, c in zip(model["labels"], contrib):
        out[lab] = out.get(lab, 0.0) + float(c / total)
    return {k: round(v, 3) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}

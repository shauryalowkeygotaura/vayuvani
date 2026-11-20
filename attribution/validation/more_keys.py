"""
More answer keys: score the SHIPPED measured-source model (engine/answer_key_model.json,
trained only on Rai et al. 2020 Xact factors at IIT Delhi) on source factors measured by
other instruments, and at another location. Nothing here is trained: it is a pure
out-of-sample test.

Keys (all CC-BY, on Zenodo):
  wang_iitd   PTR-ToF-MS VOC PMF at IIT Delhi, winter 2018 (Wang et al. 2020,
              https://zenodo.org/records/3931977): Traffic1+2 = traffic, SFC1+2 = burning.
              Same site, different instrument and different chemistry (VOCs, not metals).
  wang_mriu   The same study at Manav Rachna Int. University, Faridabad (suburban,
              ~13 km south-east of IIT Delhi). A new location. Its nearest CPCB stations
              with 2018 data are 6-10 km away (the Faridabad HSPCB sites start later),
              so the pairing is weaker than IIT Delhi's 2.5 km.
  asap_iitd   ASAP-Delhi high-resolution PMF at IIT Delhi, Jan-Feb 2018 (Srivastava,
              Bloss et al., https://zenodo.org/records/19713313): Biomass burning factor.

    python -m attribution.validation.more_keys
"""

import json
import os

import numpy as np
import pandas as pd

from .. import http
from ..engine import answer_key
from . import delhi_rai as R

HERE = os.path.dirname(__file__)
CACHE = os.path.join(R.CACHE, "..", "more")
FILES = {"wang": ("https://zenodo.org/records/3931977/files/Data_Delhi_PTR.xlsx?download=1", "wang_ptr.xlsx"),
         "asap": ("https://zenodo.org/records/19713313/files/Dataset_PM2.5%20sources%20measured%20at%20Delhi.xlsx"
                  "?download=1", "asap.xlsx")}
WINTER_2018 = (("2018-01-08", "2018-03-12"),)
# MRIU, Sector 43 Faridabad (approximate campus centre).
MRIU_STATIONS = {"DL009": "Dr. Karni Singh Shooting Range (DPCC), 5.9 km", "DL026": "Okhla Phase-2 (DPCC), 9.8 km"}


def _file(key: str) -> str:
    url, name = FILES[key]
    path = os.path.join(CACHE, name)
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(path):
        resp = http.get(url, timeout=300)
        if len(resp.content) < 50_000:
            raise http.BadResponse(f"{name}: unexpectedly small download")
        with open(path, "wb") as f:
            f.write(resp.content)
    return path


def _hourly(t: pd.Series, cols: pd.DataFrame) -> pd.DataFrame:
    """Local-time (IST) samples -> UTC hourly means on the engine's floor-to-hour labels."""
    df = cols.apply(pd.to_numeric, errors="coerce")
    df["hour"] = (pd.to_datetime(t, errors="coerce") - pd.Timedelta(hours=5, minutes=30)).dt.tz_localize("UTC").dt.floor("h")
    return df.dropna(subset=["hour"]).groupby("hour").mean()


def wang(sheet: str) -> pd.DataFrame:
    raw = pd.read_excel(_file("wang"), sheet_name=sheet, header=None)
    hdr = [str(h).strip() for h in raw.iloc[0]]
    i = hdr.index("time")
    block = raw.iloc[1:, i:i + 7]
    block.columns = hdr[i:i + 7]
    f = _hourly(block["time"], block.drop(columns="time"))
    return pd.DataFrame({"traffic": f["Traffic1"] + f["Traffic2"], "biomass_burning": f["SFC1"] + f["SFC2"]})


def asap() -> pd.DataFrame:
    raw = pd.read_excel(_file("asap"), sheet_name="High-res PMF", header=None)
    hdr = [str(h).strip() for h in raw.iloc[1]]
    b = raw.iloc[2:].copy()
    b.columns = hdr
    b = b.loc[b["Sampling site"].astype(str).str.upper() == "IITD"]
    f = _hourly(b["Date and Time"], b[["Biomass burning", "Dust"]])
    return pd.DataFrame({"biomass_burning": f["Biomass burning"], "dust": f["Dust"]})


def excess(f: pd.DataFrame) -> pd.DataFrame:
    return f / f.median()


def score(net: pd.DataFrame, ex: pd.DataFrame, model: dict) -> dict:
    """Shipped model on network features; precision of its >= THRESHOLD calls vs this key."""
    rows = net.join(ex.add_prefix("ex_"), how="inner")
    out = {"paired_hours": len(rows)}
    if rows.empty:
        return out
    probs = pd.DataFrame([answer_key.predict(r, model) for _, r in rows[list(answer_key.FEATURES)].iterrows()],
                         index=rows.index)
    for src in ex.columns:
        if src not in probs:
            continue
        e = rows[f"ex_{src}"]
        clear = (e >= R.UP) | (e <= R.DOWN)
        up = e >= R.UP
        p = probs[src]
        said_up = clear & (p >= answer_key.THRESHOLD)
        said_not = clear & (p <= 1 - answer_key.THRESHOLD)
        n_up, n_not = int(said_up.sum()), int(said_not.sum())
        ok_up, ok_not = int((said_up & up).sum()), int((said_not & ~up).sum())
        # Rank agreement over all hours, as a threshold-free check of direction.
        rho = float(pd.concat([p, e], axis=1).corr(method="spearman").iloc[0, 1]) if len(e.dropna()) > 20 else None
        out[src] = {"clear_hours": int(clear.sum()), "elevated_hours": int((clear & up).sum()),
                    "called_elevated": n_up, "right": ok_up,
                    "precision_elevated": None if not n_up else round(ok_up / n_up, 3),
                    "called_not": n_not, "precision_not": None if not n_not else round(ok_not / n_not, 3),
                    "spearman_p_vs_measured": None if rho is None else round(rho, 2),
                    "validated_on_cards": src in model.get("validated", [])}
    return out


def main():
    model = answer_key.load()
    near = {k: R.STATIONS[k] for k in R.NEAREST}
    iitd_net = R.network_features(R.fetch_obs(os.path.join(R.CACHE, "cpcb_winters.csv"), near))
    mriu_obs = R.fetch_obs(os.path.join(CACHE, "cpcb_mriu_hours.csv"), MRIU_STATIONS, WINTER_2018)
    mriu_net = R.network_features(mriu_obs, stations=tuple(MRIU_STATIONS))
    keys = {"wang_iitd (VOC PMF, IIT Delhi)": (iitd_net, excess(wang("Figure 3"))),
            "asap_iitd (high-res PMF, IIT Delhi)": (iitd_net, excess(asap())),
            "wang_mriu (VOC PMF, MRIU Faridabad)": (mriu_net, excess(wang("Figure 4")))}
    res = {k: score(net, ex, model) for k, (net, ex) in keys.items()}
    L = ["# The shipped measured-source model on answer keys it never saw", "",
         f"Model: {model['version']} (trained only on Rai 2020 Xact factors at IIT Delhi). Threshold "
         f"{answer_key.THRESHOLD}. 'Elevated' = >= {R.UP}x the key's median, 'not' = <= {R.DOWN}x (middle dropped). "
         "Only burning and traffic are ever named on cards.", ""]
    for k, r in res.items():
        L += [f"## {k}", f"Paired hours: {r.get('paired_hours', 0)}", "",
              "| Source | Clear hours (elevated) | Called elevated | Right | Precision | Called not | Precision (not) | Spearman |",
              "|---|---|---|---|---|---|---|---|"]
        for src, v in r.items():
            if not isinstance(v, dict):
                continue
            pe = "n/a" if v["precision_elevated"] is None else f"{v['precision_elevated']:.0%}"
            pn = "n/a" if v["precision_not"] is None else f"{v['precision_not']:.0%}"
            L.append(f"| {src}{'' if v['validated_on_cards'] else ' (not shown on cards)'} | {v['clear_hours']} "
                     f"({v['elevated_hours']}) | {v['called_elevated']} | {v['right']} | {pe} | {v['called_not']} | {pn} | "
                     f"{v['spearman_p_vs_measured']} |")
        L.append("")
    text = "\n".join(L)
    with open(os.path.join(HERE, "MORE_KEYS_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()

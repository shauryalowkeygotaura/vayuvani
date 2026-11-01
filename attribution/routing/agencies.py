"""
Source -> owning agency (PLAN.md Phase 4). Contact channels are deliberately
NOT hardcoded here: grievance emails and portals change, and a complaint
filed under Shaurya's name must go to a channel a human has checked. Fill
KAUN_AGENCY_CONTACTS (JSON env var or GitHub secret) after verifying each one,
e.g. {"MCD": "...", "DPCC": "...", "Delhi Traffic Police": "..."}.
"""

import json
import os
from typing import Optional

AGENCY_FOR_SOURCE = {
    "biomass_burning": ("MCD",),                      # open garbage/biomass burning
    "industry": ("DPCC",),
    "traffic": ("Delhi Traffic Police",),             # congestion
    "dust": ("DPCC", "MCD"),                          # construction / road dust
}
# Regional background and transported smoke have no single local owner.
NOT_ROUTABLE = ("regional_background", "transported_smoke")


def agencies_for(source: Optional[str]) -> tuple[str, ...]:
    return AGENCY_FOR_SOURCE.get(source or "", ())


def contacts() -> dict[str, str]:
    raw = os.getenv("KAUN_AGENCY_CONTACTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("KAUN_AGENCY_CONTACTS is not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("KAUN_AGENCY_CONTACTS must be a JSON object {agency: address}")
    return {str(k): str(v) for k, v in data.items()}

"""
Source -> owning agency, and who may actually receive email.

Routing (PLAN.md Phase 4): open burning -> MCD, industry -> DPCC, congestion ->
Delhi Traffic Police, construction/road dust -> DPCC. Each item has ONE
primary agency so a report is sent once, not duplicated across inboxes.

Recipients come from reporting/contacts.json; only verified addresses are
returned. If the primary agency has none, the CPCB central air-complaint
intake is used (when verified) and the report names the intended agency.
KAUN_AGENCY_CONTACTS (JSON) can override contacts.json from a secret.
"""

import json
import os
from typing import Optional

PRIMARY_AGENCY = {
    "biomass_burning": "MCD",
    "industry": "DPCC",
    "traffic": "Delhi Traffic Police",
    "dust": "DPCC",
}
NOT_ROUTABLE = ("regional_background", "transported_smoke")
FALLBACK = "CPCB"
HERE = os.path.dirname(__file__)


def agencies_for(source: Optional[str]) -> tuple[str, ...]:
    a = PRIMARY_AGENCY.get(source or "")
    return (a,) if a else ()


def load_contacts(path: Optional[str] = None) -> dict:
    raw = os.getenv("KAUN_AGENCY_CONTACTS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            raise ValueError("KAUN_AGENCY_CONTACTS is not valid JSON")
    else:
        with open(path or os.path.join(HERE, "contacts.json"), encoding="utf-8") as f:
            data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("contacts must be a JSON object {agency: {...}}")
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def recipients(agency: str, contacts: Optional[dict] = None) -> tuple[list[str], str]:
    """(verified emails, agency actually addressed). Empty list = nobody may be emailed."""
    contacts = contacts if contacts is not None else load_contacts()
    for target in (agency, FALLBACK):
        c = contacts.get(target) or {}
        emails = [e for e in c.get("emails") or [] if isinstance(e, str) and "@" in e]
        if c.get("verified") is True and emails:
            return emails, target
    return [], agency


def contacts() -> dict[str, str]:
    """Legacy helper: {agency: first verified email}."""
    out = {}
    for agency, c in load_contacts().items():
        if c.get("verified") is True and c.get("emails"):
            out[agency] = c["emails"][0]
    return out

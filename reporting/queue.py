"""
Report queue: everything that may go to an agency passes through here.

Producers (hourly cron, independent of any phone call):
- enqueue(): HIGH-confidence attributions whose top source is local and
  routable (kind = "spike").
- reporting.citizen.enqueue_clusters(): clusters of caller reports, kind = "citizen".

Consumer: reporting.digest (daily). In manual mode it sends only rows a
human approved (one tap: the "Kaun approve report" workflow, or
`python -m reporting.queue approve <id> --by <name>`). In auto mode
(KAUN_AUTO_SEND=1) it sends pending rows too, inside the caps in digest.py.

Statuses: pending -> approved (manual) -> sent | held (no verified recipient) | rejected.
"""

import argparse
import logging
import re
from datetime import datetime, timezone

from attribution.config import REPO_SLUG
from attribution.store import get_store

from . import evidence
from .agencies import NOT_ROUTABLE, agencies_for, routing_source

logger = logging.getLogger(__name__)

APPROVE_URL = f"https://github.com/{REPO_SLUG}/actions/workflows/kaun-approve.yml"
ID_RE = re.compile(r"^[0-9a-f]{16}$")
APPROVER_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,60}$")


def eligible(rec: dict) -> bool:
    top = routing_source(rec)
    return (rec.get("confidence") == "high" and top not in NOT_ROUTABLE
            and bool(agencies_for(top)) and not rec.get("synthetic"))


def existing_ids(store) -> set[str]:
    return {str(r.get("attribution_id")) for r in store.select("complaint_queue")}


def enqueue(records: list[dict], store=None, root=None) -> list[dict]:
    store = store or get_store()
    seen = existing_ids(store)
    rows = []
    for rec in records:
        if not eligible(rec) or rec["id"] in seen:
            continue
        pack = evidence.build(rec, root=root)
        src = routing_source(rec)
        rows.append({
            "attribution_id": rec["id"],
            "kind": "spike",
            "station_id": rec["station_id"],
            "agencies": list(agencies_for(src)),
            "top_source": src,
            "confidence": rec["confidence"],
            "latitude": rec.get("latitude"),
            "longitude": rec.get("longitude"),
            "window_start": rec.get("window_start"),
            "summary": rec["summary_en"],
            "evidence_md": pack["markdown"],
            "status": "pending",
            "approve_url": APPROVE_URL,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    if rows:
        store.upsert("complaint_queue", rows)
    logger.info(f"Queue: {len(rows)} new spike reports")
    return rows


def _check_id(item_id: str) -> None:
    if not ID_RE.fullmatch(item_id or ""):  # whitelist: goes into a PostgREST filter
        raise ValueError(f"bad report id {item_id!r}: expected 16 hex chars")


def _set_status(item_id: str, approver: str, status: str, store=None) -> None:
    _check_id(item_id)
    if not APPROVER_RE.fullmatch(approver or ""):
        raise ValueError("approver must be a plain name (letters, spaces, . ' -)")
    store = store or get_store()
    rows = store.select("complaint_queue", {"attribution_id": f"eq.{item_id}"})
    if not rows:
        raise SystemExit(f"no report {item_id}")
    if rows[0].get("status") not in ("pending", "held"):
        raise SystemExit(f"report {item_id} is {rows[0].get('status')}; only pending/held can change")
    store.update("complaint_queue", {"attribution_id": item_id}, {
        "status": status, "approved_by": approver.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"Report {item_id} -> {status} by {approver}")


def approve(item_id: str, approver: str, store=None) -> None:
    _set_status(item_id, approver, "approved", store)


def reject(item_id: str, approver: str, store=None) -> None:
    _set_status(item_id, approver, "rejected", store)


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="VayuVani report queue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("approve", "reject"):
        a = sub.add_parser(name)
        a.add_argument("item_id")
        a.add_argument("--by", required=True, help="name of the human deciding")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "approve":
        approve(args.item_id, args.by)
    elif args.cmd == "reject":
        reject(args.item_id, args.by)
    else:
        for r in get_store().select("complaint_queue", {"status": "eq.pending"}):
            print(r["attribution_id"], r.get("kind"), r.get("summary"))


if __name__ == "__main__":
    main()

"""
Complaint queue. Human-approved, NEVER auto-sent (CLAUDE.md domain rule).

Flow:
1. enqueue(): after each engine run, every HIGH-confidence attribution whose
   top source is local and routable gets an evidence pack and a row in
   complaint_queue with status "pending".
2. A human reviews the pack and approves with ONE tap: the "Kaun approve"
   GitHub Actions workflow (workflow_dispatch, input = complaint id), runnable
   from the GitHub mobile app. That is the approve link stored on each row.
   Locally: python -m attribution.routing.queue approve <id>
3. send_approved(): only rows with status "approved" AND approved_by set are
   rendered into an outbox file. Delivery itself (email/WhatsApp/portal) is
   left as a manual step until agency channels are verified; there is no code
   path from "pending" to "sent".
"""

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone

from ..config import REPO_SLUG, STATE_DIR
from ..store import get_store
from . import evidence
from .agencies import NOT_ROUTABLE, agencies_for, contacts

logger = logging.getLogger(__name__)

APPROVE_URL = f"https://github.com/{REPO_SLUG}/actions/workflows/kaun-approve.yml"


def eligible(rec: dict) -> bool:
    top = rec.get("top_source")
    return (rec.get("confidence") == "high" and top not in NOT_ROUTABLE
            and bool(agencies_for(top)) and not rec.get("synthetic"))


def enqueue(records: list[dict], store=None, root=None) -> list[dict]:
    store = store or get_store()
    existing = {str(r.get("attribution_id")) for r in store.select("complaint_queue")}
    rows = []
    for rec in records:
        if not eligible(rec) or rec["id"] in existing:
            continue
        pack = evidence.build(rec, root=root)
        rows.append({
            "attribution_id": rec["id"],
            "station_id": rec["station_id"],
            "agencies": list(agencies_for(rec["top_source"])),
            "summary": rec["summary_en"],
            "evidence_md": pack["markdown"],
            "status": "pending",
            "approve_url": APPROVE_URL,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    if rows:
        store.upsert("complaint_queue", rows)
    logger.info(f"Queue: {len(rows)} new complaints pending human approval")
    return rows


ID_RE = re.compile(r"^[0-9a-f]{16}$")
APPROVER_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,60}$")


def approve(attribution_id: str, approver: str, store=None) -> None:
    # Whitelist: both values end up in a PostgREST query string.
    if not ID_RE.fullmatch(attribution_id or ""):
        raise ValueError(f"bad complaint id {attribution_id!r}: expected 16 hex chars")
    if not APPROVER_RE.fullmatch(approver or ""):
        raise ValueError("approver must be a plain name (letters, spaces, . ' -)")
    if not approver.strip():
        raise ValueError("approver name is required")
    store = store or get_store()
    rows = store.select("complaint_queue", {"attribution_id": f"eq.{attribution_id}"})
    if not rows:
        raise SystemExit(f"no complaint {attribution_id}")
    if rows[0].get("status") != "pending":
        raise SystemExit(f"complaint {attribution_id} is {rows[0].get('status')}, not pending")
    store.update("complaint_queue", {"attribution_id": attribution_id}, {
        "status": "approved", "approved_by": approver.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"Complaint {attribution_id} approved by {approver}")


def send_approved(store=None, outbox: str = None) -> list[str]:
    """Render approved complaints into outbox files for the human to send."""
    store = store or get_store()
    outbox = outbox or os.path.join(STATE_DIR, "outbox")
    os.makedirs(outbox, exist_ok=True)
    book = contacts()
    written = []
    for row in store.select("complaint_queue", {"status": "eq.approved"}):
        if not row.get("approved_by"):
            continue  # belt and braces: never act on an unattributed approval
        agencies = row.get("agencies")
        if isinstance(agencies, str):
            agencies = json.loads(agencies)
        to = [book.get(a, f"<verify contact for {a}>") for a in agencies or []]
        path = os.path.join(outbox, f"{row['attribution_id']}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"To: {', '.join(to)}\nApproved by: {row['approved_by']}\n\n{row['evidence_md']}\n")
        store.update("complaint_queue", {"attribution_id": row["attribution_id"]},
                     {"status": "ready_to_send"})
        written.append(path)
    return written


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Kaun complaint queue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("approve")
    a.add_argument("attribution_id")
    a.add_argument("--by", required=True, help="name of the human approving")
    sub.add_parser("outbox")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "approve":
        approve(args.attribution_id, args.by)
        print("\n".join(send_approved()))
    elif args.cmd == "outbox":
        print("\n".join(send_approved()))
    else:
        for r in get_store().select("complaint_queue", {"status": "eq.pending"}):
            print(r["attribution_id"], r.get("summary"))


if __name__ == "__main__":
    main()

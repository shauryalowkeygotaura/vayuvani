"""
Daily agency digests: the autonomous "report it to the department" step.

    python -m reporting.digest            # what .github/workflows/kaun-report.yml runs daily
    python -m reporting.digest --dry-run  # render to the outbox, send nothing

One email per agency per day, never one per spike. Guard rails:
- Mode: KAUN_AUTO_SEND=1 sends pending items autonomously. Otherwise only
  items a human approved are sent; pending ones wait.
- Recipients: only addresses marked verified in reporting/contacts.json.
  Unverified agency -> CPCB central intake if that is verified -> else the
  items are "held" and rendered to the outbox for a human.
- Caps: MAX_ITEMS per digest, MAX_DIGESTS_PER_DAY overall, one digest per
  agency per IST day (report_digests has a unique (agency, day) key, so a
  rerun cannot double-send).
- Kill switch: KAUN_REPORTS_PAUSED=1 stops all sending.
- Pre-flight: auto mode without SMTP credentials fails loudly.
Every send is recorded (report_digests + complaint_queue.status = sent).
"""

import argparse
import hashlib
import json
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional

from attribution.config import REPO_SLUG, STATE_DIR
from attribution.labels import LABELS_EN
from attribution.store import get_store

from .agencies import load_contacts, recipients

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MAX_ITEMS = 10
MAX_DIGESTS_PER_DAY = 5
MAX_AGE_DAYS = 3
PAGE_URL = os.getenv("KAUN_PAGE_URL", "https://shauryalowkeygotaura.github.io/vayuvani/")


def auto_mode() -> bool:
    return os.getenv("KAUN_AUTO_SEND", "") == "1"


def paused() -> bool:
    return os.getenv("KAUN_REPORTS_PAUSED", "") == "1"


def smtp_config() -> Optional[dict]:
    cfg = {k: os.getenv(k, "") for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "REPORT_FROM")}
    if not (cfg["SMTP_HOST"] and cfg["SMTP_USER"] and cfg["SMTP_PASSWORD"]):
        return None
    cfg["SMTP_PORT"] = int(cfg["SMTP_PORT"] or 587)
    cfg["REPORT_FROM"] = cfg["REPORT_FROM"] or cfg["SMTP_USER"]
    return cfg


def _agencies(row) -> list[str]:
    a = row.get("agencies")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            a = [a]
    return list(a or [])


def _sendable(row: dict, now: datetime) -> bool:
    st = row.get("status")
    if st == "approved" and row.get("approved_by"):
        return True
    if st in ("pending", "held") and auto_mode():
        return row.get("confidence") == "high" or row.get("kind") == "citizen"
    return False


def _fresh(row: dict, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(row.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return now - t <= timedelta(days=MAX_AGE_DAYS)


def compose(agency: str, addressed: str, items: list[dict], day: str) -> tuple[str, str]:
    subj = f"VayuVani air pollution report for {agency}: {len(items)} location(s), {day}"
    L = [f"To the {agency} team,", "",
         "VayuVani is an independent, automated air-quality monitoring project in Delhi. It analyses public "
         "CPCB/DPCC station data, wind and satellite fire data every hour, and takes pollution reports from "
         "citizens by phone. The following locations need inspection:", ""]
    if addressed != agency:
        L += [f"(Sent to {addressed} because no verified {agency} complaint address is on file; please forward.)", ""]
    for i, it in enumerate(items, 1):
        src = LABELS_EN.get(it.get("top_source"), it.get("top_source"))
        L.append(f"{i}. {it.get('summary')}")
        L.append(f"   Likely source: {src}. Confidence: {it.get('confidence')}. Type: "
                 f"{'station data' if it.get('kind') == 'spike' else 'citizen phone reports'}.")
        if it.get("latitude") is not None:
            L.append(f"   Map: https://www.openstreetmap.org/?mlat={float(it['latitude']):.5f}"
                     f"&mlon={float(it['longitude']):.5f}#map=15/{float(it['latitude']):.5f}/{float(it['longitude']):.5f}")
        L.append(f"   Reference: VV-{it['attribution_id']}")
        L.append("")
    L += ["How to read this: source shares are estimates from pollutant ratios and wind direction, not "
          "measurements of a specific site. Station data cannot identify an individual emitter; the request is "
          "an inspection of the indicated area.",
          f"Live map and method: {PAGE_URL}",
          f"Source code: https://github.com/{REPO_SLUG}",
          "", "Reply to this email to correct a report or to stop receiving these digests.", "", "VayuVani"]
    return subj, "\n".join(L)


def send_email(cfg: dict, to: list[str], subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["REPORT_FROM"], ", ".join(to), subject
    reply_to = os.getenv("REPORT_REPLY_TO")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Message-ID"] = make_msgid(domain="vayuvani.local")
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if cfg["SMTP_PORT"] == 465:
        with smtplib.SMTP_SSL(cfg["SMTP_HOST"], 465, context=ctx, timeout=30) as s:
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
    return msg["Message-ID"]


def run(store=None, now: Optional[datetime] = None, dry_run: bool = False, outbox: Optional[str] = None,
        sender=send_email, contacts: Optional[dict] = None) -> dict:
    store = store or get_store()
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(IST).strftime("%Y-%m-%d")
    outbox = outbox or os.path.join(STATE_DIR, "outbox")
    contacts = contacts if contacts is not None else load_contacts()
    cfg = smtp_config()
    if auto_mode() and not dry_run and not paused() and cfg is None:
        raise SystemExit("KAUN_AUTO_SEND=1 but SMTP_HOST/SMTP_USER/SMTP_PASSWORD are not set. "
                         "Add them as repo secrets (e.g. Gmail: smtp.gmail.com, port 465, an app password).")
    rows = [r for r in store.select("complaint_queue") if _fresh(r, now) and _sendable(r, now)]
    done = {(d["agency"], d["day"]) for d in store.select("report_digests", {"day": f"eq.{day}"})
            if d.get("status") == "sent"}
    sent_today = len(done)
    by_agency: dict[str, list[dict]] = {}
    for r in rows:
        for a in _agencies(r)[:1]:
            by_agency.setdefault(a, []).append(r)
    summary = {"day": day, "mode": "auto" if auto_mode() else "manual", "paused": paused(),
               "sent": [], "held": [], "skipped": []}
    os.makedirs(outbox, exist_ok=True)
    for agency, items in sorted(by_agency.items()):
        items = sorted(items, key=lambda r: (r.get("confidence") != "high", str(r.get("created_at"))))[:MAX_ITEMS]
        to, addressed = recipients(agency, contacts)
        subject, body = compose(agency, addressed, items, day)
        path = os.path.join(outbox, f"{day}_{agency.replace(' ', '_')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"To: {', '.join(to) or '(no verified recipient)'}\nSubject: {subject}\n\n{body}\n")
        ids = [it["attribution_id"] for it in items]
        if (addressed, day) in done or (agency, day) in done:
            summary["skipped"].append({"agency": agency, "reason": "already sent today"})
            continue
        if dry_run or paused():
            summary["skipped"].append({"agency": agency, "reason": "dry run" if dry_run else "paused", "outbox": path})
            continue
        if not to or cfg is None:
            for i in ids:
                store.update("complaint_queue", {"attribution_id": i}, {"status": "held"})
            summary["held"].append({"agency": agency, "items": len(ids), "outbox": path,
                                    "reason": "no verified recipient" if not to else "SMTP not configured"})
            continue
        if sent_today >= MAX_DIGESTS_PER_DAY:
            summary["skipped"].append({"agency": agency, "reason": "daily digest cap reached"})
            continue
        msg_id = sender(cfg, to, subject, body)
        sent_today += 1
        digest_id = hashlib.sha1(f"{addressed}|{day}".encode()).hexdigest()[:16]
        store.upsert("report_digests", [{
            "id": digest_id, "agency": addressed, "day": day, "recipients": to, "items": ids,
            "subject": subject, "message_id": msg_id, "status": "sent", "sent_at": now.isoformat()}])
        done.add((addressed, day))
        for i in ids:
            store.update("complaint_queue", {"attribution_id": i},
                         {"status": "sent", "sent_at": now.isoformat(), "digest_id": digest_id})
        summary["sent"].append({"agency": addressed, "for": agency, "items": len(ids), "to": to})
    logger.info(f"Digest {day}: {json.dumps(summary)}")
    return summary


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Send daily agency digests")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    s = run(dry_run=args.dry_run)
    print(json.dumps(s, indent=1))
    if s["held"] and auto_mode():
        print("NOTE: some reports are held: verify agency emails in reporting/contacts.json", file=sys.stderr)


if __name__ == "__main__":
    main()

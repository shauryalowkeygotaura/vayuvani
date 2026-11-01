# Autonomous agency reporting

Runs without any phone call:

1. **Hourly** (`kaun.yml`): high-confidence local spikes become report items (`reporting/queue.py`).
   Caller complaints are clustered (`reporting/citizen.py`). A cluster is reportable with 3+ distinct
   callers, or 1+ caller plus station data agreeing on the source.
2. **Daily at 10:11 IST** (`kaun-report.yml`): `reporting/digest.py` sends one email per agency with up to
   10 items, each with the likely source, confidence, map link and a `VV-<id>` reference.

## Routing

| Source | Agency |
|---|---|
| Open garbage/biomass burning | MCD |
| Industry (SO2) | DPCC |
| Construction/road dust | DPCC |
| Traffic congestion | Delhi Traffic Police |
| Regional background, transported smoke | not routed (no local owner) |

If an agency has no verified address, the digest goes to the CPCB central air-complaint intake (when that is
verified) and names the intended agency.

## Turning on full autonomy (Shaurya)

1. **Verify recipients:** open each `source_url` in `reporting/contacts.json`. If the address is listed for
   public complaints, set `"verified": true` and `"verified_on"`. Nothing is emailed to an unverified address,
   whatever the mode.
2. **SMTP secrets:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `REPORT_FROM`, and optionally
   `REPORT_REPLY_TO`. For Gmail: `smtp.gmail.com`, port 465, an app password (needs 2FA).
3. **Repo variable:** `KAUN_AUTO_SEND` = `1` (Settings, Secrets and variables, Actions, Variables).
4. **Dry run first:** Actions, "Kaun daily agency reports", Run workflow with dry_run ticked. Then read the outbox artifact.

## Guard rails (in code, tested in `reporting/test_citizen_digest.py`)

- Medium/low-confidence spikes are never auto-sent.
- One digest per agency per IST day. `report_digests (agency, day)` is unique, so reruns cannot double-send.
- At most 5 digests per day, 10 items each. Items older than 3 days are dropped.
- Kill switch: repo variable `KAUN_REPORTS_PAUSED` = `1`.
- Auto mode without SMTP credentials fails the run loudly and opens a `kaun-alert` issue.
- Stop one report: Actions, "Kaun approve report", decision `reject`.

## Why not WhatsApp, Sameer or 311 apps

None of them has a public API. Automating their apps would break their terms and is brittle. Email to an
official intake address is the only programmatic channel.

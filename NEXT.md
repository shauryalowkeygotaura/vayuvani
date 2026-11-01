# NEXT: plan of action after PR #1 (written 2026-11-01)

Read `CLAUDE.md`, then this file (`NEXT.md`), then `docs/KAUN.md`. Work top to bottom. Tick boxes as you go and log in `SESSION_LOG.md`.

## Already done (from Shaurya's laptop, 2026-11-01)
- [x] Repo secrets set: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` (verified `role: service_role`), `FIRMS_MAP_KEY` (live-tested HTTP 200), `OPENAQ_API_KEY`, `GROQ_API_KEYS` (2 accounts), `LOG_LEVEL`.
- [x] GitHub Pages enabled, `build_type=workflow`. URL: https://shauryalowkeygotaura.github.io/vayuvani/ (the site is public even though the repo is private; only `public/data/*` and the page should be deployed, never raw tables or the complaint queue).
- [x] Same secrets in Doppler `vayuvani/dev` for local runs.
- [ ] `DATA_GOV_IN_API_KEY` (CPCB): not yet. Shaurya is getting it. Code must keep working without it (OpenAQ only).

## Step 0: Shaurya, manual (blocking for steps 2+)
- [ ] Paste `supabase/migrations/002_kaun.sql` into the Supabase SQL editor and run it. (No DB password available to automate this.)
- [ ] In the cloud environment's network settings, allow: `api.openaq.org`, `firms.modaps.eosdis.nasa.gov`, `api.open-meteo.com`, `archive-api.open-meteo.com`, `api.data.gov.in`, and the Supabase project host. Without this, cloud sessions stay offline and can't do steps 2-4.

## Step 1: make the tests honest (no network needed)
- [ ] Fix the 3 pre-existing `pipeline/` failures. Verify the CPCB NAQI PM2.5 breakpoints from the official CPCB NAQI document before deciding whether `test_pm25_severe` (expects 500 at 400 µg/m³) or the table is wrong. Fix the cleaner tests to match what the cleaner actually returns (or add the timestamp key if downstream code needs it; grep for the call site).
- [ ] `python -m pytest -q` at repo root is fully green.

## Step 2: first live run
- [ ] Merge PR #1 into `master` once step 1 is green. **Scheduled crons only fire on the default branch**, so nothing runs hourly until this merge.
- [ ] Trigger "Kaun hourly attribution" manually (`gh workflow run kaun.yml`). Check: credential gate passes, `hourly_obs` / `fire_points` / `wind_obs` rows land, the page deploys, and `public/data/latest.json` has real stations.
- [ ] Fix whatever the real API responses break (parsers were written from docs + fixtures only). Save one real response per source as a new fixture and add a regression test for it.

## Step 3: CPCB (when `DATA_GOV_IN_API_KEY` exists)
- [ ] Resolve the open question: is `pollutant_avg` a concentration or a sub-index? Compare 24 h of CPCB vs OpenAQ for the same stations; write the finding into `docs/KAUN.md`.
- [ ] Keep the existing auto-drop-on-disagreement guard.

## Step 4: backfill + backtest (Oct-Nov 2025)
- [ ] `python -m attribution.run backfill --start 2025-10-01 --end 2025-11-30` (checkpointed; resume on 429).
- [ ] `python -m attribution.validation.backtest --start 2025-10-01 --end 2025-11-30`.
- [ ] Known events: Diwali 20 Oct 2025 (firecracker/burning signal expected that night), stubble peak window. Report hit/miss honestly.
- [ ] Compare against CSE's 2025 seasonal shares (stubble 4.9%). Report the gap, don't tune the engine to match it.
- [ ] DSS: there's no public API. List exactly which DSS bulletins/dates Shaurya should transcribe into `attribution/validation/reference/dss_outputs.csv` (keep it short, ~10 dates max), and leave the template.
- [ ] Write `docs/RESULTS.md`: numbers, charts, and limits. No "beats DSS" claim without DSS rows.

## Step 5: harden the weak classes
- [ ] "Industry" rests on SO2 only and "dust" on the PM2.5/PM10 ratio only. Add a second signal for each or keep them capped at low/medium confidence. Document which.
- [ ] Consider station-measured wind (CPCB WS/WD) over modelled wind where available; keep Open-Meteo as the fallback.

## Step 6: unattended week
- [ ] Let the hourly cron run 7 days. Add a failure alert (the workflow opens/updates a GitHub issue on failure; no paid services).
- [ ] After 7 clean days: tick "Done when" in `PLAN.md`.

## Step 7: outreach (Shaurya sends, never auto)
- [ ] Update `docs/outreach/gani_email_draft.md` with real `RESULTS.md` numbers. Shaurya sends it.
- [ ] Verify agency contacts (MCD, DPCC, Delhi Traffic Police) from official sites, cite each URL, and put them in config. Complaints stay one-tap approve.

## Out of scope for now
- Plan B (Dhuan Node hardware). Only start after step 4 has real numbers.
- Porting "Kaun?" into `vayuvani-app` (separate repo); note it as a follow-up issue instead.

---

## Step 8: Plan B groundwork (offline-safe, do this if steps 2-4 are blocked or done)
- [ ] `hardware/dhuan-node/BOM.md`: exact parts (ESP32, Plantower PMS5003/PMS7003, CO + NO2 electrochemical, VOC, wind vane), Indian supplier links (Robu.in, Robocraze), cost per node; target Rs 6-10k. Cite every price with URL and date.
- [ ] `hardware/dhuan-node/firmware/`: PlatformIO ESP32 skeleton reading each sensor at 1 Hz, computing the features (PM1/PM2.5, CO/PM2.5, NO2/CO, rise time, wind dir), logging to SD + optional MQTT. Compiles in CI (`pio run`), with mocked sensor drivers unit-tested.
- [ ] `hardware/dhuan-node/labelling-protocol.md`: how Shaurya records labelled events (stand X m from source, Y minutes, what to note). Classes: traffic, garbage/biomass burning, construction dust, cooking/tandoor, background.
- [ ] `hardware/dhuan-node/classifier/`: training pipeline (scikit-learn, small tree/GBM exportable to C for ESP32) + synthetic data generator + tests. Real data comes later.
- [ ] Calibration plan for co-location at the R K Puram DPCC station.

## Step 9: polish (only after 1-8)
- [ ] Public page: mobile-first, Hindi/English toggle, "how this works + limits" section. Lighthouse check if a browser is available.
- [ ] `README.md` rewrite: what Kaun is, screenshot, how to run, limits.
- [ ] Open GitHub issues for anything left unfinished, one issue per item, with exact next steps.

---

## AUTOPILOT PROMPT (paste this into a fresh cloud session)

```
Read CLAUDE.md, then NEXT.md, then docs/KAUN.md. Execute NEXT.md end to end, steps 1 through 9, without stopping to ask me anything. I am away; this is a long autonomous run with a budget of about $100 of tokens.

Rules for this run:
1. Order: step 1, then 2, 3, 4, 5, 6 (set up the alert; you can't wait 7 days), 7, 8, 9. If a step is blocked (no network, missing secret, Step 0 not done by me), write exactly what blocks it in SESSION_LOG.md, then move to the next step that isn't blocked. Never sit idle and never stop at the first blocker.
2. First action: test network to every host in Step 0 and to Supabase, and test whether the Kaun tables exist. Log the results. That tells you which steps are live and which are offline-only.
3. Commit after every finished checkbox on branch claude/kaun-next (open a draft PR to master; merge PR #1 first if step 1 is green and the merge is clean). Small commits, plain messages, no AI attribution, no em dashes.
4. Checkpoint: keep SESSION_LOG.md current after each step so a cut-off session can be resumed by a new one reading NEXT.md + SESSION_LOG.md.
5. Budget: spend tokens on running code and tests, not re-reading files. Don't re-read files you've already read. If you're past roughly 85% of budget, stop new work, finish the current checkbox, update SESSION_LOG.md + NEXT.md checkboxes, push, and write the final report.
6. Honesty: never fake live results. Anything only tested on fixtures gets labelled "fixture-only" in docs and in the final report.
7. Final report (in chat, starting with "Shaurya,"): what's done and verified, what's fixture-only, what's blocked and the exact thing I must do to unblock it, and the PR link.
```

# NEXT: plan of action after PR #1 (written 2026-11-01)

Read `CLAUDE.md`, then this file (`NEXT.md`), then `docs/KAUN.md`. Work top to bottom. Tick boxes as you go and log in `SESSION_LOG.md`.

## Already done (from Shaurya's laptop, 2026-11-01)
- [x] Repo secrets set: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` (verified `role: service_role`), `FIRMS_MAP_KEY` (live-tested HTTP 200), `OPENAQ_API_KEY`, `GROQ_API_KEYS` (2 accounts), `LOG_LEVEL`.
- [x] GitHub Pages enabled, `build_type=workflow`. URL: https://shauryalowkeygotaura.github.io/vayuvani/ (the site is public even though the repo is private; only `public/data/*` and the page should be deployed, never raw tables or the complaint queue).
- [x] Same secrets in Doppler `vayuvani/dev` for local runs.
- [ ] `DATA_GOV_IN_API_KEY` (CPCB): not yet. Shaurya is getting it. Code must keep working without it (OpenAQ only).

## Step 0: Shaurya, manual (blocking for steps 2+)
- [ ] Paste `supabase/kaun_schema.sql` into the Supabase SQL editor and run it. (No DB password available to automate this.)
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

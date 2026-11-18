# NEXT: plan of action after PR #1 (written 2026-11-01)

Read `CLAUDE.md`, then this file (`NEXT.md`), then `docs/KAUN.md`. Work top to bottom. Tick boxes as you go and log in `SESSION_LOG.md`.

## 2026-11-01 (session 2): phone line + autonomous reporting added
Shaurya changed the goal: anyone can call, hear AQI + source, and reports go to departments autonomously.
Built: `voice/` + `api/` (VAPI webhook), `reporting/` (citizen clusters, daily digests, gated auto-send),
`supabase/migrations/003_voice_reporting.sql`, `kaun-report.yml`. Setup: `docs/VOICE.md`, `docs/REPORTING.md`.
New manual steps for Shaurya: run migration 003; verify emails in `reporting/contacts.json`; SMTP secrets;
repo variable `KAUN_AUTO_SEND=1`; Vercel deploy + VAPI assistant + phone number.

## Already done (from Shaurya's laptop, 2026-11-01)
- [x] Repo secrets set: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` (verified `role: service_role`), `FIRMS_MAP_KEY` (live-tested HTTP 200), `OPENAQ_API_KEY`, `GROQ_API_KEYS` (2 accounts), `LOG_LEVEL`.
- [x] GitHub Pages enabled, `build_type=workflow`. URL: https://shauryalowkeygotaura.github.io/vayuvani/ (the site is public even though the repo is private; only `public/data/*` and the page should be deployed, never raw tables or the complaint queue).
- [x] Same secrets in Doppler `vayuvani/dev` for local runs.
- [ ] `DATA_GOV_IN_API_KEY` (CPCB): not yet. Shaurya is getting it. Code must keep working without it (OpenAQ only).

## Step 0: Shaurya, manual (blocking for steps 2+)
- [ ] Paste `supabase/migrations/002_kaun.sql` into the Supabase SQL editor and run it. (No DB password available to automate this.)
- [ ] In the cloud environment's network settings, allow: `api.openaq.org`, `firms.modaps.eosdis.nasa.gov`, `api.open-meteo.com`, `archive-api.open-meteo.com`, `api.data.gov.in`, and the Supabase project host. Without this, cloud sessions stay offline and can't do steps 2-4.

## Step 1: make the tests honest (no network needed)
- [x] Fix the 3 pre-existing `pipeline/` failures. Verify the CPCB NAQI PM2.5 breakpoints from the official CPCB NAQI document before deciding whether `test_pm25_severe` (expects 500 at 400 µg/m³) or the table is wrong. Fix the cleaner tests to match what the cleaner actually returns (or add the timestamp key if downstream code needs it; grep for the call site).
- [x] `python -m pytest -q` at repo root is fully green. (2026-11-01: see SESSION_LOG; PM2.5 severe ceiling left as an open question, test now checks only what the published table pins down.)

## Step 2: first live run
- [ ] Merge PR #1 into `master` once step 1 is green. **Scheduled crons only fire on the default branch**, so nothing runs hourly until this merge.
- [ ] Trigger "Kaun hourly attribution" manually (`gh workflow run kaun.yml`). Check: credential gate passes, `hourly_obs` / `fire_points` / `wind_obs` rows land, the page deploys, and `public/data/latest.json` has real stations.
- [x] Fix whatever the real API responses break (parsers were written from docs + fixtures only). Save one real response per source as a new fixture and add a regression test for it.

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
- [x] Consider station-measured wind (CPCB WS/WD) over modelled wind where available; keep Open-Meteo as the fallback.

## Step 6: unattended week
- [ ] Let the hourly cron run 7 days. (Failure alert DONE: kaun.yml and kaun-report.yml open/update a `kaun-alert` issue.) Add a failure alert (the workflow opens/updates a GitHub issue on failure; no paid services).
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
Read CLAUDE.md, then NEXT.md, then docs/KAUN.md. Execute NEXT.md end to end, steps 1 through 11 (read "Decisions 2026-11-05" first; it overrides earlier steps), without stopping to ask me anything. I am away; this is a long autonomous run with a budget of about $100 of tokens.

Rules for this run:
1. Order: skip boxes already ticked. Then 11 (report board), 10 (Pipecat phone), then any open boxes in 2-9. If a step is blocked (no network, missing secret, Step 0 not done by me), write exactly what blocks it in SESSION_LOG.md, then move to the next step that isn't blocked. Never sit idle and never stop at the first blocker.
2. First action: test network to every host in Step 0 and to Supabase, and test whether the Kaun tables exist. Log the results. That tells you which steps are live and which are offline-only.
3. Commit after every finished checkbox on branch claude/kaun-next (open a draft PR to master; merge PR #1 first if step 1 is green and the merge is clean). Small commits, plain messages, no AI attribution, no em dashes.
4. Checkpoint: keep SESSION_LOG.md current after each step so a cut-off session can be resumed by a new one reading NEXT.md + SESSION_LOG.md.
5. Budget: spend tokens on running code and tests, not re-reading files. Don't re-read files you've already read. If you're past roughly 85% of budget, stop new work, finish the current checkbox, update SESSION_LOG.md + NEXT.md checkboxes, push, and write the final report.
6. Honesty: never fake live results. Anything only tested on fixtures gets labelled "fixture-only" in docs and in the final report.
7. Final report (in chat, starting with "Shaurya,"): what's done and verified, what's fixture-only, what's blocked and the exact thing I must do to unblock it, and the PR link.
```

---

## Decisions 2026-11-05 (Shaurya) - these override earlier steps
- **Phone line: Shaurya's own Pipecat stack, NOT VAPI.** No VAPI spend, ever. Pattern is in `voice/reference/pipecat_stack/` (Groq STT + Groq LLM + edge-tts Neerja + Silero VAD + paralang). Keep the existing tool logic (`get_air_quality`, `report_pollution`, gazetteer) and swap the transport.
- **Reporting: public report board on the website is the PRIMARY channel.** Email digests become optional (only if `SMTP_*` secrets exist). Don't automate agency portals (MCD 311, Green Delhi): no public API, OTP/CAPTCHA, terms risk.
- Old "VayuVani AQI Pipeline" workflow is disabled on master (silently failing). Supabase project was deleted; Shaurya is creating a new one. Until then everything must run with `KAUN_STORE=local`.

## Step 10: phone line on Pipecat
- [ ] `voice/pipecat_agent.py`: port `rt_agent.py`'s pipeline; tools call the existing `voice/` handlers directly (no webhook hop). Hindi/English via paralang `ReplyRouter`. Answer from `public/data/now.json` + `latest.json`; target < 2 s to first audio.
- [ ] **Browser transport first (free):** a "Talk to Kaun" button on the public page using Pipecat's WebRTC transport (SmallWebRTC or Daily free tier; prefer no-account options). Document where the agent process runs (it can't run on GitHub Pages: a free always-on host is needed, e.g. Hugging Face Spaces CPU or a free Fly/Render tier; verify current free limits with sources).
- [ ] Phone transport later: Exotel SIP (~$0.007/min, KYC in Shaurya's name). Write `docs/PHONE.md` with the exact human steps; don't buy anything.
- [ ] `--selftest` mode with text in/out so tests run without audio. Retire `voice/vapi.py`, `voice/assistant.json`, `voice/setup_vapi.py` and `api/vapi.py` to `legacy/`.

## Step 11: public report board (primary reporting)
- [ ] `public/reports.html` (+ link from the map): one card per high/medium attribution and per citizen-report cluster: station, time window, source + confidence, responsible agency, evidence pack (SVG chart + numbers), status (open / repeated / resolved-by-data when the spike stops recurring).
- [ ] Per-agency pages (`reports.html?agency=MCD`) and a weekly summary ("MCD: 14 burning spikes in East Delhi, 9 repeated at the same station").
- [ ] Data from `public/data/reports.json`, written by the hourly run. Caller numbers stay hashed; never publish raw phone numbers or free-text that could identify a caller.
- [ ] Share-friendly: each card has a permalink and an OG image so it can be posted on X/WhatsApp by Shaurya (posting stays manual).
- [ ] Email digest code stays but is opt-in; the board must work with zero secrets.

## Decisions 2026-11-13 (Shaurya): the cause, not the share

- "Pin point exactly what is causing the pollution, not location but the cause": engine kaun-0.2 ships a `cause` block per attribution (see `docs/KAUN.md`, "Cause decomposition"). Keep improving the cause, never regress to a bare share.
- Land use is now real data (`attribution/ingest/fixtures/landuse_delhi-ncr.json`). Refresh with `python -m attribution.ingest.landuse snapshot` when stations change; never let the hourly job depend on Overpass.
- Forms: CPCB's web form is dead on CPCB's side. The command center fills CPGRAMS / UP Jansunwai / Delhi PGMS via the Kaun extension. Nothing is ever submitted automatically.
- Expansion: one region per workflow dispatch (`region` input). Before enabling a second city, move the feed to per-region branches so Pages can hold more than Delhi (the deploy job only runs for Delhi today).
- Next for the cause engine: (1) a per-source "what to look for" line for inspectors; (2) weight the regional composition by station coverage; (3) a 24 h city-wide "why is today bad" summary on the public page from the same regional profile.

## Step 12 (2026-11-18, Shaurya: "at least 95% success, do whatever, more data, more features")

**The target, defined so it can be measured.** "95%" = precision of the source Kaun *publishes*: of the
spikes where a card names a local source, at least 95% are right against a labelled set, with the
lower end of the 95% confidence interval reported next to it. Kaun says "source unclear" for everything
else. Coverage (how many spikes get a named source) is reported too and pushed up over time. 95% on
*every* spike from station data is not physically possible (3+ sources mix in one air parcel); 95% on
the calls it chooses to make is, once labels exist. Never publish a success rate without the labelled
set behind it.

Baseline (blind test 18 Nov, `attribution/validation/BLIND_REPORT.md`): local source calls agree with no
independent witness, neighbouring stations agree 34% (= chance). Start from here; re-run the blind test
after every change and append the table to the report.

### 12a. Build the answer key (nothing else can be measured without it)
- [ ] `attribution/validation/labels.py` + table `spike_labels` (attribution_id, label, source of label, evidence url, labeller). Label sources, strongest first:
  1. Field photos: timestamped, geotagged photo of the source at or near a named site (public report board, Step 11, + phone line). Shaurya / callers.
  2. FIRMS fire within 2 km upwind of the station in the spike hours -> burning (positive label only).
  3. Natural experiments with official dates (verify each date on CAQM / DPCC orders): GRAP stage III/IV (construction ban -> dust share must drop; BS-III petrol / BS-IV diesel ban, truck entry ban -> traffic share must drop), Diwali night 2025 (20 Oct 2025, firecrackers: metals/SO2 + fine, not traffic), Sundays (traffic lower). These test shares at population level, not single spikes.
  4. Injected synthetic signatures on top of REAL station series (not the toy generator): necessary, not sufficient.
- [ ] Target size: >= 100 labelled spikes per source class for a +-4% interval.

### 12b. More data (each one a new, independent signal)
- [ ] CPCB CCR full parameter set per station: benzene, toluene, xylene (BTX; toluene/benzene ratio separates exhaust ~1.5-3 from burning <1), NH3 (burning, agriculture), PM1, NO, NOx. OpenAQ carries only part of this: check `CPCB_API_KEY` (in Doppler, NOT yet a GitHub secret, so CI skips CPCB) and the CCR / data.gov.in resources for BTX and NH3 per station.
- [ ] Sentinel-5P TROPOMI daily NO2, CO, HCHO (Copernicus, free account): city-scale witness and an upwind/downwind gradient.
- [ ] Low-cost sensor networks on OpenAQ (isMonitor=false, currently dropped) as extra spatial density, down-weighted.
- [ ] VIIRS night lights / OSM building permits for construction activity; Delhi traffic speed (TomTom/HERE free tier) for a real congestion signal instead of the clock prior.

### 12c. Better method
- [ ] **Use the network, not one station.** For each spike, fit which OSM source (or source class at a location) best explains the pattern of excesses across ALL stations given the wind field: a Gaussian-plume / footprint inversion over the land-use inventory. A real source lights up the downwind stations in order; a single-station ratio cannot see that. This is the biggest expected gain.
- [ ] Hour-of-week baseline (weekday vs Sunday) instead of same-hour.
- [ ] Learn the fusion weights from the labelled set (logistic regression over the term contributions) instead of hand priors; calibrate probabilities (isotonic) on held-out labels.
- [ ] **Abstain:** publish a local source only when calibrated P(source) >= the threshold that gives >= 95% precision on held-out labels; else "unclear". Cards and phone line show "unclear" honestly.
- [ ] Until 12a has labels: cards tag the local source "unverified" and lead with the measured parts (spike, local vs region-wide split, stagnation numbers, named sites).

### Done when
- Blind test passes the twins check and at least 3 of the witness checks (p < 0.05).
- Precision of published calls >= 95% on >= 100 held-out labels per class, interval reported, coverage reported.

### 12d. External answer key: test the method where sources are measured (do this first, 2026-11-18)
Shaurya is chasing Delhi's own answer key (Gani email + DPCC RTI, `docs/outreach/answer_key_requests.md`).
Meanwhile prove or kill the method on data where hourly sources are measured:
- [ ] Find an open dataset with hourly measured source shares AND co-located hourly PM2.5, PM10, NO2, CO, SO2
  (and ideally several stations within a city): candidates to check, in order: ACTRIS / EBAS aethalometer
  black carbon split into wood burning vs fossil (BCwb / BCff); ClearfLo 2012 London (North Kensington,
  Marylebone Road) data archive; Paris SIRTA ACSM organic-aerosol PMF (HOA = traffic, BBOA = burning);
  US EPA AQS hourly gases next to speciation sites. Write what is actually downloadable, with URLs.
- [ ] `attribution/validation/external.py`: load it into the same hourly_obs shape, run the engine with
  `chemistry_only()` (blind.py), score burning vs traffic calls against the measured split: precision,
  recall, and the calibration curve of the fusion posterior.
- [ ] Use it to improve the method (term weights by logistic regression, abstention threshold for 95%
  precision), then re-run the Delhi blind test. Report both numbers. A London result is evidence the
  method works, not a Delhi accuracy number: never quote it as one.

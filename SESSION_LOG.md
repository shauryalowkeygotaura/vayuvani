# Session log

## 2026-11-01: Plan A "Kaun?" built end to end (offline)

**Built** (`attribution/`, wired and called from `attribution/run.py`):
- Ingest: OpenAQ v3 hourly (all six pollutants, unit-normalised), CPCB via data.gov.in (optional key, auto cross-checked against OpenAQ), Open-Meteo wind + boundary layer (live + archive), NASA FIRMS VIIRS/MODIS 300 km, time-of-day traffic prior.
- Engine: spike detector (7-day same-hour median + MAD), delta-ratio fingerprints, wind sector + CBPF, regional/local split with upwind-fire cone, NMF factors, confidence grading with caps.
- Publish: static JSON feed, Leaflet page (`public/index.html`, SRI hashes verified from the npm tarball), GitHub Pages deploy; "Kaun?" voice line appended in `advisory/generator.py` (template, no LLM).
- Routing: agency map, SVG evidence packs, `complaint_queue` with one-tap GitHub Actions approval; nothing is ever sent automatically.
- Validation: backtest report vs CSE seasonal shares, Diwali 2025 / stubble window, DSS (when a CSV is supplied), sub-grid spike count.
- Infra: `supabase/kaun_schema.sql`, `.github/workflows/kaun.yml` (hourly at :17, checkpoint via actions/cache), `kaun-approve.yml`, pre-flight gate, checkpoint, exit codes 0/1/75.

**Verified:** `python -m pytest attribution -q` = 45 passed. Synthetic end-to-end run recovers all four injected spike types (traffic, burning, dust, industry) with the right top source; noise spikes grade low.

**Not verified / blocked:**
- Zero live API calls: this cloud session's network policy blocked api.openaq.org, firms.modaps.eosdis.nasa.gov, api.open-meteo.com, data.gov.in and the Supabase host. Parsers are written against documented formats and tested on fixtures only.
- `kaun_schema.sql` not applied to Supabase.
- CPCB key: `CPCB_API_KEY` was empty in the session. Whether data.gov.in `pollutant_avg` is a concentration or a sub-index is unverified; the runner guards with a cross-check.
- Pre-existing failures in `pipeline/` tests (3), unrelated to this work: `test_pm25_severe` expects 500 for 400 ug/m3 (the breakpoint table gives 460), and two cleaner tests expect a `timestamp` key.

**Next step:** run `supabase/kaun_schema.sql`, add the GitHub secrets, enable Pages (Source: GitHub Actions), dispatch "Kaun hourly attribution" once, then run the Oct-Nov 2025 backfill and the backtest.

## 2026-11-01 (session 2): reorg, phone line, autonomous reporting, multi-variable fusion, first live data

**Goal change (Shaurya):** anyone can call, hear AQI + where it comes from; reports go to departments autonomously.

**Built**
- Repo reorganised: `reporting/` (out of attribution), `voice/`, `api/`, `supabase/migrations/00N_*.sql`, `legacy/` (n8n), `requirements.txt` (webhook, stdlib) vs `requirements-engine.txt`, root `pyproject.toml` pytest config. Old 15-min cron retired to manual (it shared the OpenAQ key's 60/min limit).
- `public/data/now.json`: NAQI per station (24 h / 8 h means, >= 16/24 h, >= 3 pollutants incl. PM).
- Phone line: VAPI webhook (`voice/vapi.py`, Vercel `api/vapi.py`), tools `get_air_quality` and `report_pollution`, gazetteer + Nominatim geocoding, Hindi/English templates, caller numbers hashed. `voice/assistant.json` + `voice/setup_vapi.py`.
- Autonomous reporting: `reporting/citizen.py` (caller clusters), `reporting/digest.py` (one email per agency per day, SMTP), `kaun-report.yml` daily. Gated: `KAUN_AUTO_SEND=1`, verified recipients only, caps, kill switch, no double-send. CLAUDE.md rule updated to match.
- Fusion source model (`attribution/engine/fusion.py`): 8 evidence terms over 5 sources incl. new "secondary"; new station variables NO, NOx, RH, temperature; per-pollutant CBPF; OSM upwind land use (`ingest/landuse.py`); station-measured wind preferred over modelled.
- NEXT step 1 done (pipeline tests fixed; PM2.5 severe ceiling unverified, test narrowed). Step 5 done (second signals, station wind). Step 6 alert done.

**Verified LIVE this session (network partly opened)**
- OpenAQ, Open-Meteo, FIRMS reachable. Real-response fixtures saved in `attribution/ingest/fixtures/`. Live 8-day ingest into a local store: 54 stations, 6,681 station-hours, 5,282 station-wind hours, 327 fires; engine + publish ran end to end; city median NAQI 296 (33 fresh stations).
- Live-API bugs found and fixed: dead locations with null datetimeLast; duplicate sensors per pollutant (old dead + new); low-cost non-monitor sites; hours run :30-:30 UTC; partial-coverage hours; OpenAQ data lags 2-3.5 h (stale threshold raised to 4 h).
- Finding: rule-based fingerprints called 43/69 spikes "biomass" because post-monsoon air is fine-dominated everywhere. Added station-relative fine fraction and the secondary class; full fusion with RH/NO pending the second live run (see below).

**Blocked / not verified**
- Supabase: 502 from upstream (project likely paused). data.gov.in: connection reset. Overpass, cpcb.nic.in, dpcc.delhigovt.nic.in, traffic.delhipolice.gov.in: blocked here. So: no DB writes, land use is fixture-only, agency emails unverified (all `verified: false`).
- No VAPI/SMTP credentials: phone line and email sending tested with fakes only.

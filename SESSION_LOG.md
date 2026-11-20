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

**First live snapshot with full fusion (local store, 2026-11-01 ~08:00 UTC, NOT validated)**
- Variable coverage over 8 days: PM2.5 93%, PM10 88%, NO2 94%, SO2 79%, CO 91%, O3 93%, NO 92%, RH 78%, temp 71%. Land use: none (Overpass blocked here; fills in CI).
- 79 spike windows in the last 48 h across 54 stations. Top source: biomass/garbage burning 36, regional background 19, traffic 12, dust 6, industry 4, secondary 2. Confidence: high 3, medium 49, low 27.
- Before fusion (rules only) the same data gave biomass 43/69. Changes that moved it: station-relative fine fraction, the RH/secondary term, NO fraction, rebalanced fingerprint weight, and "transported smoke" now needing >= 2 m/s steady 24 h wind (it fell from 11 to 0 in this stagnant window, which matches CSE's small stubble share but proves nothing).
- Live data bugs found: OpenAQ CPCB "nox" sensors mislabelled (ppb tag, values ~1000x low, inconsistent with NO + NO2), so they are dropped and NO fraction comes from NO and NO2.
- Phone answers on the live feed: 0-3 ms from the gazetteer, 433 ms with a Nominatim lookup.
- Did NOT merge PR #1: Supabase is down (502), so the hourly cron on master would fail its pre-flight every hour and open alert issues. Merge after the Supabase project is restored and migrations 002-004 are run.

## 2026-11-07 (local laptop): first full live hourly run, KAUN_STORE=local

- Supabase project was DELETED (NXDOMAIN); Shaurya is creating a new one. Old "VayuVani AQI Pipeline" workflow disabled on master (it was green while every write failed).
- Pre-flight fix (058d5fe): skips Supabase under KAUN_STORE=local; unreachable project gives a fix message, not a traceback.
- Live run: exit 0. 54 OpenAQ stations, 311 station-hours (window 2026-11-06 18:00 to 11-07 03:00 UTC), 1,512 Open-Meteo wind hours, 549 FIRMS fires. 0 attributions: expected, the spike detector needs the 7-day baseline, so run the backfill first.
- **Slow ingest:** OpenAQ took ~14 min for a 9-hour window (per-sensor calls under the 60/min key limit). The hourly CI job must fit inside its timeout: check `timeout-minutes` in kaun.yml and consider fetching only new hours per sensor.
- **Overpass:** overpass-api.de returned 406 for every station, then timeouts; mirrors (private.coffee, kumi.systems) returned 429/timeouts. Cause not confirmed. Added an identifying User-Agent to `attribution/http.py` (OSM etiquette; Nominatim already had one). Land use degrades gracefully (0 refreshed, 54 due). Suggest: mirror fallback list + POST queries + cache land use for 30 days (it barely changes).
- Decisions 2026-11-05 in NEXT.md still apply (Pipecat phone, report board primary).

## 2026-11-13 (local laptop): kaun-0.2, the cause engine

Shaurya's ask: "pin point exactly what is causing the pollution, other than just cars; not location but the cause; autofill all forms; see progress; expand from Delhi to India."

- **Root bug found on live data:** `SupabaseStore.select` paged with OFFSET and no ORDER BY, so Postgres returned heap-ordered pages that overlapped: 832 duplicate rows out of 5,832 wind rows loaded, ~15% missing. 34 of 86 spike windows therefore had no wind at all, which silently disabled the land-use and wind-signature terms and left `sector` null on 85% of cards. Fixed (order by the natural key), test added.
- **Land-use v2** (`attribution/ingest/landuse.py`): more source types (works, kilns, crematoria, depots, highway construction), 2 km neighbourhood totals, named features with distance/bearing, Overpass mirrors tried in turn with POST (overpass-api.de 502s most of the day; z.overpass-api.de answers in ~25-45 s), `python -m attribution.ingest.landuse snapshot` writes `fixtures/landuse_delhi-ncr.json` and fills the store. Bawana check: industrial Sectors 1-4 at 0.9-2.4 km N/NE, Pragati-III gas plant 3.0 km NE, Ramky WtE 3.1 km NE.
- **Fusion:** calm-air branch of the land-use term (neighbourhood vs fleet mean). **Regional profile** (`regional.regional_profile`): mechanism from city-mean wind (< 1.5 m/s) and mixing-height ratio (< 0.6) or upwind fires + carrying wind; composition from the fingerprint + humidity terms on the city-median excess. **Cause block** (`attribute.build_cause`) and new summaries. Routing via `agencies.routing_source` (local part >= 40%).
- **Live result (12 Nov, 70 windows, before land-use v2 grids existed):** every window `stagnation` (wind 0.3-0.5 m/s, mixing height 50-95% of normal); cause tops: traffic 43, burning 25, dust 1, industry 1; e.g. Ashok Vihar "~65% region-wide: stagnant air trapped the city's own emissions (wind 0.5 m/s, mixing height 68% of normal); the shared air looks like traffic exhaust 63% + burning 37%; ~35% local: burning (calm air: close by)".
- **Regions:** `regions.py`, `KAUN_REGION`, migration 005 (`attributions.cause`, `kaun_stations.region`, applied via the Management API), workflow input; only the Delhi run deploys Pages.
- **Command center:** KAUN tab shows the cause block with candidate sites and map links; CPCB's form is dead so "fill" opens CPGRAMS / UP Jansunwai / Delhi PGMS; extension + userscript + bookmarklet v2 fill any portal form by field identity (one write per field, never captcha/OTP/password/file, nothing submitted), payload survives the login redirect for 2 h. Verified in Chromium on pgportal.gov.in/Registration.
- 136 tests pass. PR #4 opened; `gh pr merge` is blocked by the local permission classifier, so Shaurya merges.

**Honest limits added to docs/KAUN.md:** regional composition is a mix estimate; OSM candidates are places to look, not accusations; calm air gives no direction.

**Not done / next:** Oct-Nov 2025 backfill (Step 4); Pipecat phone (Step 10); report board (Step 11); a second region needs its own 7-day baseline; the portals are login-gated so the extension cannot be tested past the registration page without Shaurya's account.

## 2026-11-18/19: blind test, CO bug, London answer key

- Blind test (`attribution/validation/blind.py`): local source calls agree with no independent witness in Delhi (twins 34% = chance). Factor labels made station-relative (PR #6, merged).
- CO bug: OpenAQ's CPCB CO is mg/m3 tagged "ppb"; all Delhi CO was ~1000x low. Fixed + 11,506 rows corrected in Supabase (SQL via Management API, `co < 0.05` guard).
- London AURN answer key (13 sites, 2014-2023): current method 58% on 55 events; learned absolute ratios 78-91% held-out; toluene/benzene ~97% (21 burning hours). London model does not transfer to Delhi (99% burning).
- CPCB CCR serves BTX/NH3 behind captcha + encrypted API: not scraped. Added BTX/NH3 to the DPCC RTI draft. Answer-key requests (Gani email, RTI) are a P1 handoff in the command center.
- PR #7 open (CO fix + London tests). Next: Delhi labels -> Delhi-calibrated model with abstention.

## 2026-11-20: Delhi answer key, measured-source check wired
- Built `attribution/validation/delhi_rai.py`: IIT Delhi Xact PMF factors (Rai 2020) vs CPCB hourly at 3 nearby stations.
- Per-source "elevated?" models with abstention reach 95%+ on held-out weeks for burning (97.4%) and traffic (97.0%).
- Wired `attribution/engine/answer_key.py` into the engine: Delhi cards name a source only at >= 95%, else "unsure"; scope stated.
- Verified: 143 tests pass; end-to-end replay 23/23 calls matched measured sources (in-sample).
- Next: get a second answer key (another site/season) to test transfer beyond IIT Delhi; BTX/NH3 would lift dust and industry.

## 2026-11-20 (later): more answer keys
- `attribution/validation/more_keys.py`: shipped model scored on Wang 2020 VOC PMF (IIT Delhi, MRIU Faridabad) and ASAP-Delhi PMF (IIT Delhi). Untrained, out-of-sample.
- IIT Delhi VOC key: 84/84 traffic, 79/79 burning. MRIU: burning 18/20, traffic 75/127. ASAP burning 36/45 (definition gap: waste burning in its chloride factor).
- Engine change: outside 5 km of IIT Delhi only burning is named; traffic suppressed. 144 tests pass.
- Next: Faridabad/Gurugram keys with closer monitors; any key outside south Delhi.

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

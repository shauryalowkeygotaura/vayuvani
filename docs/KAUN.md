# Kaun? (कौन?): method, setup, limits

Observation-driven hourly source attribution for Delhi monitoring stations. Code: `attribution/`.

## Pipeline (hourly, `.github/workflows/kaun.yml`)

```
preflight -> ingest -> attribute -> queue -> publish -> GitHub Pages
```

| Stage | Module | Source |
|---|---|---|
| Pollutants, hourly | `attribution/ingest/openaq.py` | OpenAQ v3 `/sensors/{id}/hours` (mirrors CPCB/DPCC) |
| CPCB direct (optional) | `attribution/ingest/cpcb.py` | data.gov.in resource `3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69` |
| Wind + boundary layer | `attribution/ingest/wind.py` | Open-Meteo (forecast API live, archive API for backfill) |
| Fires | `attribution/ingest/firms.py` | NASA FIRMS area API, VIIRS x3 + MODIS, 300 km box |
| Traffic | `attribution/ingest/traffic.py` | fixed time-of-day prior (no free feed wired) |
| Spikes | `attribution/engine/spikes.py` | 7-day same-hour median + 3 x 1.4826 x MAD, and >= 25 ug/m3 |
| Fingerprints | `attribution/engine/fingerprints.py` | delta ratios vs the station's own history |
| Wind sector | `attribution/engine/wind_sector.py` | window vector-mean wind + CBPF |
| Regional split | `attribution/engine/regional.py` | 10th-percentile city background; upwind FIRMS cone |
| Factors | `attribution/engine/factors.py` | NMF (numpy), 30-day window, labelled by the same rules |
| Confidence | `attribution/engine/confidence.py` | points + caps, see module docstring |
| Feed + page | `attribution/publish/feed.py`, `public/index.html` | static JSON + Leaflet map |
| Voice | `attribution/publish/voice.py`, wired in `advisory/generator.py` | template, no LLM |
| Queue | `attribution/routing/` | high-confidence local spikes only, human approval required |
| Backtest | `attribution/validation/backtest.py` | CSE seasonal, known events, DSS (when supplied) |

## Setup (one time)

1. Supabase SQL editor: run `supabase/kaun_schema.sql`.
2. GitHub repo secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role, not anon), `OPENAQ_API_KEY`,
   `FIRMS_MAP_KEY`; optional `DATA_GOV_IN_API_KEY`, `KAUN_AGENCY_CONTACTS`.
3. Settings -> Pages -> Source: **GitHub Actions**.
4. Actions -> "Kaun hourly attribution" -> Run workflow once; check the run log and the Pages URL.
5. Backfill for validation (run locally with Doppler, or as a one-off dispatch):

```bash
doppler run -- python -m attribution.run backfill --start 2025-10-01 --end 2025-11-30
```

```bash
doppler run -- python -m attribution.validation.backtest --start 2025-10-01 --end 2025-11-30
```

Offline check with synthetic data (never published):

```bash
python -m attribution.run demo
```

## Approving a complaint

Each high-confidence local spike becomes a `complaint_queue` row (status `pending`) with an evidence pack.
Approve with Actions -> "Kaun approve complaint" -> id + your name (works from the GitHub mobile app).
Approval renders an outbox file (artifact); delivery stays manual until agency contacts are verified.
There is no code path from `pending` to sent.

## Exit codes

`0` ok, `1` auth/config (fix needed, the run fails red), `75` rate-limited (next run resumes from the checkpoint).
The checkpoint lives in `.kaun_state/checkpoint.json`, carried between runs by `actions/cache`.

## Honest limits

- **What is solid:** CO/PM2.5 and NO2/PM2.5 separate traffic from biomass smoke. Fine fraction (PM2.5/PM10)
  separates combustion from dust.
- **What is fuzzy:** 3+ source splits from station data alone. Those are capped at medium confidence.
  Industry rests on SO2 alone; dust on the fine fraction alone.
- **Wind** is modelled at the station location, not the station mast (OpenAQ and data.gov.in do not expose WS/WD).
- **Transport** uses a straight line along the 24 h mean wind, not HYSPLIT. It raises a flag; it does not prove transport.
- **NMF is not PMF:** no per-reading uncertainties exist for CPCB data. NMF only corroborates.
- **Firecrackers** have no class; they show up as fine-mode combustion with SO2.
- **CPCB via data.gov.in:** whether `pollutant_avg` is a concentration or a sub-index was not verified.
  The runner cross-checks against OpenAQ every run and drops CPCB rows if the median PM2.5 ratio is outside 0.7-1.4.
- Facts used: DSS = IITM, 10 km grid, 2021 inventory, suspended by CAQM in late 2025. CSE stubble share 4.9% (2025 season),
  15.5% (2024). Diwali 2025 = Mon 20 Oct 2025
  ([The Week](https://www.theweek.in/news/india/2025/10/21/delhi-wakes-up-to-toxic-air-after-diwali-night-aqi-in-very-poor-category.html)).

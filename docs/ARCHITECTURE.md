# VayuVani architecture

Goal: anyone in Delhi can phone in and hear the air quality near them, what is causing it, and what to
do. Separately, and without any call, the system reports pollution hotspots to the department that owns
them.

```
                    hourly (GitHub Actions: kaun.yml)
 OpenAQ (CPCB/DPCC stations, incl. station wind) ─┐
 Open-Meteo (wind fallback, boundary layer) ──────┼─> attribution/ingest ─> Supabase (hourly_obs, wind_obs, fire_points)
 NASA FIRMS (fires within 300 km) ────────────────┤                                   │
 data.gov.in CPCB (optional) ─────────────────────┘                                   v
                                                                     attribution/engine (spikes, fingerprints,
                                                                     wind sector, regional split, NMF, confidence)
                                                                                      │
                     ┌────────────────────────────────────────────────────────────────┼───────────────────────┐
                     v                                                                v                       v
      attribution/publish -> GitHub Pages                                 reporting/queue (high-confidence   reporting/citizen
      public/data/now.json    (NAQI per station)                          local spikes)                      (caller report clusters)
      public/data/latest.json (attributions)                                         └──────────┬────────────┘
                     │                                                                          v
                     │                                              daily (kaun-report.yml): reporting/digest
                     │                                              one email per agency per day, gated:
                     │                                              KAUN_AUTO_SEND=1 + verified recipient + caps
                     v
 Caller ─> phone number (VAPI) ─> VAPI assistant (voice/assistant.json: STT, Groq LLM, TTS)
                                        │ tool calls
                                        v
                         Vercel api/vapi.py ─> voice/vapi.py ─> voice/service.py
                           get_air_quality: geocode (gazetteer, Nominatim) -> nearest fresh station in now.json
                                            -> AQI + main pollutant + Kaun source line + advice (templates, < 2 s)
                           report_pollution: geocode -> Supabase citizen_reports ─> (next hourly run) reporting/citizen
```

## Layout

| Path | What |
|---|---|
| `attribution/` | Kaun engine: `ingest/`, `engine/`, `publish/`, `validation/`, `run.py` (cron entrypoint) |
| `reporting/` | Agency routing, evidence packs, report queue, citizen clusters, daily digests, `contacts.json` |
| `voice/` | Phone line logic (stdlib only), VAPI assistant config, setup script |
| `api/` | Vercel serverless entrypoint for the webhook |
| `advisory/` | Groq advisory generator (legacy LLM path) and static advisories |
| `pipeline/` | NAQI calculator (used everywhere) and the legacy 15-minute fetcher |
| `research/` | A/B and accuracy analysis scripts |
| `supabase/migrations/` | Numbered SQL, run in order |
| `public/` | GitHub Pages site (map + JSON feeds) |
| `legacy/` | Retired n8n workflow |
| `docs/` | This file, `KAUN.md` (method), `VOICE.md`, `REPORTING.md`, outreach drafts |

## Why these choices

- **Static JSON between cron and webhook:** the webhook reads two cached JSON files, so a call never waits
  on the database and needs no read credentials. The trade-off: data is at most about an hour old, which
  matches CPCB's hourly cadence anyway.
- **No LLM in the webhook:** VAPI's model already phrases the reply. Our tool returns facts from templates,
  so it is deterministic, fast and cheap.
- **Digests, not per-spike emails:** agencies ignore spam. One email per agency per day with up to 10
  ranked items is the most an inbox will tolerate.

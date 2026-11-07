# VayuVani (वायुवाणी)

Delhi air quality by phone, with an answer to "who is polluting it?", and automatic reports to the agency
that owns the problem.

- **Call in** (Hindi/English): you hear AQI at the nearest working station, the main pollutant, the likely
  source of any recent spike, and advice. You can also report burning, dust or smoke you can see.
- **Kaun? (कौन?)**: every hour, station data, wind and satellite fires are turned into source estimates
  per station. Each estimate carries a confidence. Public map: https://shauryalowkeygotaura.github.io/vayuvani/
- **Reports itself**: high-confidence hotspots and corroborated caller complaints go out as one daily
  digest per agency (MCD, DPCC, Delhi Traffic Police, or the CPCB intake). The sends are gated: see
  `docs/REPORTING.md`.

Architecture and layout: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Method and limits:
[`docs/KAUN.md`](docs/KAUN.md). Phone setup: [`docs/VOICE.md`](docs/VOICE.md).

## Run it

```bash
pip install -r requirements-engine.txt
```

```bash
python -m pytest
```

```bash
python -m attribution.run demo
```

```bash
doppler run -- python -m attribution.preflight
```

```bash
doppler run -- python -m attribution.run hourly
```

```bash
doppler run -- python -m reporting.digest --dry-run
```

`demo` runs offline on synthetic data and is never published. The last three need secrets (Doppler
locally, GitHub Actions secrets in CI).

## Database

Run `supabase/migrations/001_base.sql`, `002_kaun.sql`, `003_voice_reporting.sql` and `004_fusion_vars.sql` in order in the
Supabase SQL editor.

## Automation

| Workflow | When | Does |
|---|---|---|
| `kaun.yml` | hourly :17 | ingest, attribute, queue reports, publish feeds, deploy Pages, open an issue on failure |
| `kaun-report.yml` | daily 10:11 IST | agency digests (auto only if `KAUN_AUTO_SEND=1`) |
| `kaun-approve.yml` | manual | approve or reject one report |
| `legacy-aqi-pipeline.yml` | manual | old 15-minute fetcher into `aqi_readings` |

## Honest limits

Traffic vs smoke (CO and NO2 relative to PM2.5) is the reliable split. Industry and dust rest on one signal
each, and 3+ source splits are capped at medium confidence. Wind is station-measured where OpenAQ has it,
otherwise modelled. Transport from upwind fires is a straight-line proxy. Details in `docs/KAUN.md`.

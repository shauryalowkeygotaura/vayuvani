# VayuVani

Voice-interactive AI system for real-time Delhi air quality advisories.

## Quick Start (Week 1 — Data Pipeline)

```bash
cd vayuvani
pip install -r requirements.txt
cp .env.example .env
# Fill SUPABASE_URL and SUPABASE_KEY in .env

# 1. Set up database (paste supabase/schema.sql into Supabase SQL editor)

# 2. Seed stations (one-time)
python -m pipeline.seed_stations

# 3. Verify data is flowing
python -m pipeline.scheduler --once

# 4. Run continuously (every 15 min)
python -m pipeline.scheduler
```

## Run Tests

```bash
python -m pytest pipeline/test_aqi_calc.py pipeline/test_cleaner.py -v
```

## n8n Workflow

Import `n8n/workflow.json` into your n8n instance:
- Settings → Import from File → select `workflow.json`
- Add environment variables: `SUPABASE_URL`, `SUPABASE_KEY`, `CPCB_API_KEY`
- Activate the workflow

## Project Structure

```
vayuvani/
├── pipeline/
│   ├── aqi_calc.py        India NAQI calculator
│   ├── fetcher.py         OpenAQ + CPCB data fetchers
│   ├── cleaner.py         Validation + normalization
│   ├── db.py              Supabase read/write layer
│   ├── scheduler.py       15-min APScheduler runner
│   ├── seed_stations.py   One-time station seeder
│   ├── test_aqi_calc.py   AQI unit tests
│   └── test_cleaner.py    Cleaner unit tests
├── supabase/
│   └── schema.sql         Full DB schema + RPC functions
├── n8n/
│   └── workflow.json      Importable n8n workflow
├── .env.example
├── requirements.txt
└── README.md
```

## Kaun? (pollution attribution engine)

Hourly "who caused this spike" estimates for every Delhi station, each with a confidence grade.
Method, setup and limits: [`docs/KAUN.md`](docs/KAUN.md).

```bash
python -m attribution.run demo        # offline synthetic run, never published
python -m attribution.preflight       # checks keys and Supabase scope
python -m attribution.run hourly      # what .github/workflows/kaun.yml runs
python -m pytest attribution -q
```

## Week 2 Preview

Next: LLM reasoning layer over RAG (CPCB guidelines + WHO standards).
Prompt + advisory generation will live in `advisory/`.

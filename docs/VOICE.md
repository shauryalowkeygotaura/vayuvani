# Phone line setup (VAPI + Vercel)

What callers get: AQI and category at the nearest working station, the main pollutant, the likely source of
any recent spike ("Kaun?"), category advice, and a way to file a pollution complaint. Hindi or English.

## 1. Deploy the webhook (Vercel)

1. Import the repo into Vercel (Framework: Other). `vercel.json` registers `api/vapi.py` on Vercel's Python
   runtime. That is a serverless function, not edge. `.vercelignore` keeps the bundle to the
   stdlib-only modules.
2. Env vars (Production). Pipe values with `printf '%s'`; never `echo`, which adds a trailing newline.

```bash
printf '%s' "https://shauryalowkeygotaura.github.io/vayuvani/data" | vercel env add FEED_BASE_URL production
```

```bash
printf '%s' "$(openssl rand -hex 24)" | vercel env add VAPI_SERVER_SECRET production
```

   Also add `SUPABASE_URL` and `SUPABASE_KEY` (the service_role key; needed only for `report_pollution`).
3. Check: `GET https://<domain>/api/vapi` returns `{"ok": true, ...}`.

## 2. Create the assistant (VAPI)

```bash
VAPI_API_KEY=... WEBHOOK_URL=https://<domain>/api/vapi VAPI_VOICE_ID=<voice> VAPI_SERVER_SECRET=<same as Vercel> python -m voice.setup_vapi
```

- Model: Groq `openai/gpt-oss-20b` (the Llama line was retired on Groq in Aug 2026, see
  `advisory/groq_pool.py`). If VAPI's Groq list lacks it, pick the closest fast Groq model in the dashboard.
- Transcriber: Deepgram nova-3 `multi` for Hindi/English code-switching. Voice: an ElevenLabs
  multilingual voice that handles Hindi.
- All of `voice/assistant.json` is a starting point; field names follow VAPI's create-assistant API
  as documented at the time of writing. If the API rejects a field, adjust it there.

## 3. Phone number

In the VAPI dashboard, buy a number or import a Twilio number, and attach the assistant. An Indian
number needs an Indian provider/KYC. A US number works for testing but costs Indian callers
international rates.

## Latency budget (VAPI webhook < 2 s)

- Feeds: cached in memory for 5 min, so a warm call does no network fetch for data.
- Geocode: local gazetteer (~1 ms). Nominatim only for unknown places (1.2 s cap).
- Measured locally: about 1 ms per `get_air_quality` with a warm cache (`voice/test_voice.py::test_air_quality_fast`).
  Vercel cold start was not measured.

## Privacy

Caller numbers are never stored raw: `citizen_reports.caller_number` holds a 16-char salted SHA-256, used
only to count distinct callers.

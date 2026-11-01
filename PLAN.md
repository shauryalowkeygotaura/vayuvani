# VayuVani: what to build next

Source spec: `Deliverables/vayuvani-pivot-ideas-2026-10-29.md` in Shaurya's vault (copied in below so this repo stands alone).

## Thesis: attribution, not alerts
Delhi measures how bad the air is at ~40 stations. Nobody says **who caused this spike, here, right now**.
- The only official source-attribution system is IITM's Decision Support System (DSS): a 10 km grid on a 2021 emissions inventory. CAQM temporarily suspended it in late 2025 over data reliability.
- The public story is wrong anyway: CSE puts stubble burning at 4.9% of PM2.5 in the 2025 season (15.5% in 2024), and a 2025 npj paper found weak coupling between Punjab/Haryana fires and Delhi PM2.5.

VayuVani today (already built, see `README.md`): OpenAQ/CPCB fetcher, NAQI calculator, Supabase schema, Groq advisory generator, Hindi/English voice layer. Plan A reuses all of it.

---

## Plan A (no hardware): "Kaun?" (Who?), a live pollution blame engine

Observation-driven hourly source attribution for every CPCB/DPCC station in Delhi. The opposite of DSS's inventory-driven model.

Example output:
> Spike at Anand Vihar, 7-9 pm: ~60% local combustion from the east sector, likely garbage/biomass, confidence medium.

### Autonomy rule
Everything runs unattended on a GitHub Actions cron **except** filing complaints with agencies. Those go into a queue and need one human tap to send (they are public filings under Shaurya's name, and confidence is "medium" at best).

### Phase 1: data ingest (`attribution/ingest/`)
- [ ] Station pollutants, hourly: PM2.5, PM10, NO2, SO2, CO, O3 (reuse `pipeline/fetcher.py`; extend to keep all pollutants plus timestamps at hourly resolution).
- [ ] Station wind speed + direction (CPCB stations report WS/WD; fall back to ERA5 / Open-Meteo hourly wind at the station lat/lon).
- [ ] NASA FIRMS fire points (VIIRS + MODIS, free MAP_KEY) within ~300 km of Delhi, last 24-72 h.
- [ ] Optional traffic proxy (e.g. TomTom/HERE free tier congestion, or a time-of-day prior if no free source).
- [ ] Supabase tables: `hourly_obs`, `fire_points`, `wind_obs`. Idempotent upserts keyed on (station, hour).
- [ ] Pre-flight: fail loudly at start if FIRMS key / Supabase creds are missing or lack scope.

### Phase 2: attribution engine (`attribution/engine/`)
- [ ] **Spike detector:** per station, flag hours where PM2.5 exceeds a rolling baseline (e.g. 7-day same-hour median + k*MAD).
- [ ] **Ratio fingerprints:** for each spike, compute ΔCO/ΔPM2.5, ΔNO2/ΔCO, PM2.5/PM10, SO2 share.
  - traffic = high NO2 and CO relative to PM
  - biomass/garbage burning = high PM2.5/PM10, lower CO/PM2.5 than traffic
  - industry/power = elevated SO2
  - construction/road dust = low PM2.5/PM10 (coarse dominated)
- [ ] **Wind-sector analysis:** bin the spike's concentrations by wind direction (conditional bivariate probability function style) to say which sector it arrived from.
- [ ] **Regional vs local split:** compare the station to the city-wide minimum / upwind stations; regional excess plus FIRMS fires upwind on a back-trajectory = transported smoke.
- [ ] **Factor analysis:** NMF/PMF on a rolling 30-day window per station to get source profiles; label factors with the fingerprint rules.
- [ ] **Output:** `attributions` table: station, window, source shares, sector, evidence, confidence (low/med/high). Never report a share without a confidence.

### Phase 3: publish (`attribution/publish/`)
- [ ] Static JSON feed + a simple public page (GitHub Pages or Vercel, Node runtime, never edge) with a station map and the latest attributions.
- [ ] Hook into the existing voice layer: "Kaun?" answers why the air is bad near you, in Hindi or English.

### Phase 4: routing queue (human-approved)
- [ ] Map source → owning agency: open burning → MCD, industry → DPCC, congestion → Delhi Traffic Police, construction dust → DPCC/MCD.
- [ ] Build an evidence pack per high-confidence spike (chart + numbers + wind sector + timestamps).
- [ ] Queue it (`complaint_queue` table) with a one-tap approve link. Sending (WhatsApp / email / agency portal) happens only after approval.

### Phase 5: validation (the research part)
- [ ] Backtest against published DSS outputs and CSE's seasonal source shares.
- [ ] Known-event checks: Diwali 2025 (firecrackers), the Oct-Nov 2025 stubble window.
- [ ] Headline target: "Agrees with DSS where DSS is right, catches X spikes DSS's 10 km grid misses."
- [ ] Honest limits section: ratio fingerprints are proven for CO/PM2.5 (traffic vs bushfire smoke); separating 3+ sources from station data alone is fuzzy. Report confidence, don't oversell.
- [ ] Email Dr Shahzad Gani (IIT Delhi CERCA) with the first results. Doubles as a summer 2027 internship ask.

### Automation
- [ ] `.github/workflows/kaun.yml`: hourly cron → ingest → attribute → publish.
- [ ] Checkpoint progress so a 401/429/kill resumes from the last good hour instead of losing the run.
- [ ] Every external call checks HTTP status and wraps JSON parsing; no happy-path-only drafts.
- [ ] Secrets via GitHub Actions secrets (Doppler locally). LLM calls (if any) via the Groq pool in `advisory/groq_pool.py`, not Anthropic.

### Done when
- Cron has run unattended for 7 days with attributions for every station that had a spike.
- Backtest notebook/report exists with agreement numbers vs DSS/CSE.
- Public page is live.

---

## Plan B (hardware, later): "Dhuan Node" (smoke node)
A street sensor that says **what** is burning. The ground truth Plan A lacks.
- **Build:** ESP32 + Plantower PMS (PM1/2.5/10) + electrochemical CO + NO2 + VOC sensor + wind vane. Optional mic for traffic noise. ~Rs 6-10k per node.
- **On-device classifier:** PM1/PM2.5 ratio, CO/PM2.5, NO2/CO, spike rise time, wind direction → {traffic, garbage/biomass burning, construction dust, cooking/tandoor, background}. Trained on labelled events recorded next to known sources.
- **Calibration:** co-locate one node at the R K Puram DPCC reference station.
- **Contribution:** low-cost source-ID work so far separates dust vs combustion; cleanly separating traffic from biomass burning with cheap sensors is new.
- **Stretch:** mount on a DTC bus or auto for a moving burning map.
- **Timing:** Nov-Feb is peak smog. Start labelling this winter or lose a season.

## Deadlines that matter
- SFT: next window ~May 2027 (2026 ran 7 May - 3 Jul, ages 14-22).
- IRIS 2026 closed 3 Oct; next cycle per vault todos.

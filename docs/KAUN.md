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

## Source model: multi-variable evidence fusion (`attribution/engine/fusion.py`)

Each spike window is scored by 8 independent evidence terms. Each term adds a log-likelihood per source, and the
posterior is a softmax over the sums. Sources: traffic, biomass/garbage burning, industry, dust, and secondary
aerosol (fine particles formed in humid, stagnant air; never routed to an agency). The regional/transported
share is split off first (`regional.py`), and the posterior divides the local remainder.

| Term | Variables | Points to |
|---|---|---|
| fingerprint | dNO2/dPM2.5, dCO/dPM2.5, dSO2/dPM2.5, fine fraction; percentiles vs the station's own history | all four primary classes |
| secondary_rh | relative humidity x fine fraction x weak CO/NO2 markers | secondary (and against burning) |
| fresh_no | dNO / (dNO + dNO2) by moles (OpenAQ's NOx sensors are mislabelled, so not used) | traffic (fresh exhaust close by) |
| time_temp | diurnal traffic prior; cold nights (< 18 C, 20:00-06:00 IST) | traffic, burning |
| upwind_landuse | OSM industrial, power plants, kilns, landfills, construction, quarries, rail yards and major roads per wind sector (0-2/2-5/5-10 km, weights 1/0.5/0.25) vs the station's all-sector mean | the matching class |
| pollutant_wind | CBPF of each class's marker pollutant (NO2/NO, SO2, PM10, CO) in the window's sector, as a z-score across sectors | the matching class |
| factors | NMF factor shares in the window | the factor's label |
| local_fires | FIRMS points within 30 km upwind in the last 12 h | burning |

In calm air (most Delhi smog hours: wind under 1 m/s, no usable sector) `upwind_landuse` switches to the
station's own neighbourhood: the OSM inventory within 2 km, compared with the mean neighbourhood across all
stations (`landuse.fleet_near_mean`). A station ringed by industrial sectors gets an industry prior; one with
fewer arterial roads than typical loses traffic. Weaker than an upwind sector (x0.8) and labelled as such.

### Cause decomposition (engine `kaun-0.2`, `attribute.build_cause`)

Every record carries a `cause` block, which is what the cards and the phone line read:

- **local**: the station's own excess (1 - regional share): the fused shares, the wind sector or "calm",
  and up to three **named OSM candidates** (`landuse.candidates`): power plants, industrial areas, kilns,
  landfills, construction sites, depots in the wind sector (or within 4 km when calm), nearest first.
  Named only when the local part is at least 25% of the excess.
- **regional**: how much of the rise the whole airshed shared, **why** (`regional.regional_profile`):
  `transport` (fires upwind and wind that can carry them), `stagnation` (city-mean wind under 1.5 m/s or
  mixing height under 60% of its same-hour norm: the lid under which the city's own emissions pile up),
  else `regional_rise`; and **what it is made of**: the fingerprint and humidity terms applied to the
  city-median excess of each species, so a smog day reads "trapped air, traffic-like + burning-like"
  instead of "regional background".
- **shares / top**: the two folded together (regional composition weighted by the regional share) and the
  single biggest cause; `text_en` / `text_hi` is the sentence the card shows.

Agency routing (`reporting.agencies.routing_source`) uses the local top only when the local part is at
least 40% of the excess; a station that merely sits in region-wide smog is not reported to MCD.

### Land-use inventory (`attribution/ingest/landuse.py`, version 2)

One Overpass query per station (10 km): industrial land and works, power plants, brick kilns, landfills and
waste transfer stations, crematoria, construction, quarries, rail yards, bus and truck depots, arterial
roads. Reduced to a sector x distance grid, a 2 km neighbourhood total, and the named features themselves.
Cached in `station_landuse` for 30 days and committed as `attribution/ingest/fixtures/landuse_<region>.json`
(`python -m attribution.ingest.landuse snapshot`), so an hourly run never depends on Overpass being up.
Several Overpass mirrors are tried in turn (the public ones 502 for much of the day).

### Regions (`attribution/regions.py`)

`KAUN_REGION` picks the airshed (default `delhi-ncr`; Mumbai, Kolkata, Bengaluru, Chennai, Hyderabad,
Ahmedabad, Pune, Lucknow, Kanpur, Patna, Jaipur, Chandigarh, Varanasi are defined). It sets the OpenAQ
sweep centres, the FIRMS box, the Overpass coordinate whitelist, the state directory and the feed path
(`public/data/<region>/` for anything but Delhi). Stations carry their region in `kaun_stations.region`,
so one Supabase project can hold several airsheds without mixing their backgrounds. Turning on a second
city is one workflow run with the `region` input; its baseline needs 7 days of hourly runs like Delhi did.

Wind comes from the station's own mast where OpenAQ has it (most CPCB/DPCC stations), otherwise from Open-Meteo.
The weights (`fusion.W`) are engineering priors, not fitted values: there is no labelled ground truth for Delhi.
Every attribution stores each term's contribution (`evidence.fusion.terms`), so you can audit why it chose a
source. More terms do not mean more truth. Every term has a physical reason to exist, and the backtest is the
check.

## Setup (one time)

1. Supabase SQL editor: run `supabase/migrations/002_kaun.sql`, `003_voice_reporting.sql`, `004_fusion_vars.sql`.
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
- **Regional composition** fingerprints the city-median excess against a pooled ratio history. On a stagnant
  night it tends to read traffic-like plus burning-like, which matches Delhi's local inventory, but it is a
  mix estimate, not a measurement; secondary aerosol is included only through humidity.
- **Named candidates** are OpenStreetMap features in the wind sector. OSM is incomplete and sometimes stale,
  so a candidate is a place to look, never an accusation. The card text says "likely", the agency text says
  "possible sites".
- **Blind test, 18 Nov 2026 (`python -m attribution.validation.blind`): the local source label is not
  validated.** With the map, clock and fire terms switched off, station chemistry's calls (burning /
  traffic / industry / dust) did not line up with satellite fires, the clock, the map, or even with a
  neighbouring station under 3 km away spiking in the same hours (agreement 34% vs 37-40% for distant
  pairs). Read the local source on a card as a hypothesis. What is measured, not inferred: the spike
  itself, the local vs region-wide split, the stagnation numbers (wind, mixing height), and the named
  sites (map facts). The test also found the factor analysis labelling almost every factor "burning"
  (absolute fine-fraction cut-off); fixed to station-relative, which spread the calls but did not make
  the checks pass.
- **Calm air** gives no direction. The neighbourhood prior then only says what the station is surrounded by.
- **NMF is not PMF:** no per-reading uncertainties exist for CPCB data. NMF only corroborates.
- **Firecrackers** have no class; they show up as fine-mode combustion with SO2.
- **CPCB via data.gov.in:** whether `pollutant_avg` is a concentration or a sub-index was not verified.
  The runner cross-checks against OpenAQ every run and drops CPCB rows if the median PM2.5 ratio is outside 0.7-1.4.
- Facts used: DSS = IITM, 10 km grid, 2021 inventory, suspended by CAQM in late 2025. CSE stubble share 4.9% (2025 season),
  15.5% (2024). Diwali 2025 = Mon 20 Oct 2025
  ([The Week](https://www.theweek.in/news/india/2025/10/21/delhi-wakes-up-to-toxic-air-after-diwali-night-aqi-in-very-poor-category.html)).

## Measured-source check (answer key, 2026-11-20)

Every Delhi-NCR card now carries one extra sentence from `attribution/engine/answer_key.py`:
"Measured-source check (95%+ sure): burning elevated", or "unsure, no source reaches 95%".

- **Trained on measured sources**, not on Kaun's own rules: hourly PMF factors from an Xact XRF at
  IIT Delhi (Rai et al. 2020, https://zenodo.org/records/3907250), winters 2018 and 2019, paired with
  CPCB hourly data at Sri Aurobindo Marg, Sirifort and R K Puram (CPCB CCR 2015-2020 compilation,
  mirrored at https://huggingface.co/datasets/khush-thakkar-09/station_hour).
- **Held-out weeks, at >= 0.95 confidence, live features only:** burning 97.4% precise (calls 39% of
  hours), traffic 97.0% (25%). Dust 93.7% and industry 85.8% miss the bar, so they are never named.
  Report: `attribution/validation/DELHI_RAI_REPORT.md`; rebuild with
  `python -m attribution.validation.delhi_rai --export`.
- **End-to-end replay** of the 2018-19 spikes through `spikes.detect` and the check: 23 calls,
  23 matched the measured source (in-sample, so a wiring check, not a new accuracy number).
- **Limits:** one site, two winters, the ambiguous middle band dropped from training, threshold
  chosen on the same CV. Cards farther than 5 km from IIT Delhi say "not validated at this station".
  Other regions get no verdict.

### More answer keys (2026-11-20): the shipped model on data it never saw
`python -m attribution.validation.more_keys`, report in `attribution/validation/MORE_KEYS_REPORT.md`.

| Key | Where | Traffic calls right | Burning calls right |
|---|---|---|---|
| Wang et al. 2020 VOC PMF (zenodo 3931977) | IIT Delhi | 84/84 | 79/79 |
| ASAP-Delhi high-res PMF (zenodo 19713313) | IIT Delhi | n/a | 36/45 (most misses: waste burning, which ASAP books to a separate chloride factor) |
| Wang et al. 2020 VOC PMF | MRIU Faridabad, monitors 6-10 km away | 75/127 (fails) | 18/20 |

So: near IIT Delhi both calls hold on independent instruments. Away from it burning mostly
transfers and traffic does not (it is too local for monitors 6-10 km off). Cards outside 5 km of
IIT Delhi therefore name burning only, and say it was 18 of 20 at a second site.

## Pooled keys and episodes (2026-11-23)

The burning model is now trained on every answer key (Rai Xact, Wang VOC at IIT Delhi and MRIU, ASAP). When a spike lasts 3 or more hours, it is called at P >= 0.85 instead of 0.95. Trained on 2018 and tested on 2019, those calls were right 99.2% of the time and covered 69% of clear episodes (the old model covered 40%). Traffic stays on Rai only at 0.95, because pooling it fell below 95% on 2019. Reports: `attribution/validation/NCR_REPORT.md`.

During the 2020 lockdown (25 Mar to 14 Apr), the live model's traffic calls fell at 29 of 39 NCR stations. The median share of hours called traffic dropped from 5.6% in 2019 to 0%. That shows the direction is right across NCR, but it is not a precision number (`LOCKDOWN_REPORT.md`).

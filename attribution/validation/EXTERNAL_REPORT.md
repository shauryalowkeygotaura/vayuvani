# Kaun external test: London (AURN)

Years 2014-2023, 13 London AURN sites (5 kerbside/roadside, 8 background). Chemistry-only engine (map, clock and fire terms off). Labels: Bonfire Night = burning; weekday daytime spikes at a kerbside site not shared by its nearest background site = traffic. London is not Delhi: this tests the discriminator, it is not a Delhi accuracy number.

| Class | True windows | Called | Precision | Recall |
|---|---|---|---|---|
| biomass_burning | 34 | 23 | 78% | 53% |
| traffic | 21 | 25 | 56% | 67% |

Labelled windows: 55. Confusion (label -> call): {"biomass_burning -> biomass_burning": 18, "traffic -> traffic": 14, "biomass_burning -> traffic": 11, "traffic -> biomass_burning": 5, "biomass_burning -> secondary": 5, "traffic -> secondary": 2}
All calls on all windows: {"traffic": 162, "secondary": 23, "industry": 4, "biomass_burning": 128, "dust": 2}

## Follow-ups (19 Nov 2026)

- **Larger answer key** (`london_deltas.py`, report `LONDON_DELTAS_REPORT_dpm5_from17.md`): every kerbside-minus-background
  hour is a traffic label (36,091 rows), every Bonfire Night hour at a background site is a burning label (262).
  A logistic model on absolute ratios (NO2/PM2.5, NO share of NOx, fine fraction), trained 2014-2019 and tested on
  held-out 2020-2023, reaches 78-91% class-balanced precision; asking for higher confidence lowers coverage but
  does not get past ~91%. Stricter label rules (>= 10 ug/m3, Bonfire Night from 19:00) did worse (73-78%) and
  were not adopted.
- **Toluene/benzene** (Marylebone Road vs Eltham, the two VOC sites): burning T/B median 1.5, traffic 3.9.
  Leave-one-year-out: T/B alone 97-98% precision, NO2/PM + NO share 95-97%. Only 21 burning hours on 3 nights,
  so the interval is wide (one or two misses would move it several points). Strong enough to make BTX the first
  new Delhi data source.
- **Transfer to Delhi fails:** the London-trained model calls 148 of 150 Delhi spikes "burning"; Delhi's PM
  excess per unit NO2 is about ten times London's. Absolute ratios must be calibrated on Delhi labels.

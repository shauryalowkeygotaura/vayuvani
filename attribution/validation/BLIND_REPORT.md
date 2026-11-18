# Kaun blind test

Generated 2026-11-18 17:44 UTC. Spike windows: 161 (12 Nov to 18 Nov 2026). Engine re-run with the map, clock and fire terms switched off; each check compares the chemistry-only call with a witness the engine did not see. p = one-sided permutation p-value.

| Check | Witness | Group n | Rate in group | Rate elsewhere | p | Result |
|---|---|---|---|---|---|---|
| Burning calls have more satellite fires within 30 km | fires | 85 | 54% | 59% | 0.793 | not shown |
| Traffic calls fall in rush hours (8-11, 18-22 IST) | clock | 29 | 17% | 24% | 0.852 | not shown |
| Burning calls fall at night (20-06 IST) | clock | 85 | 21% | 32% | 0.956 | not shown |
| Stations within 3 km of a landfill/crematorium get more burning calls | map | 70 | 59% | 48% | 0.131 | not shown |
| Stations at a depot/rail hub or dense arterial roads get more traffic calls | map | 107 | 17% | 20% | 0.779 | not shown |
| Stations inside industrial land get more industry calls | map | 66 | 5% | 20% | 0.999 | not shown |
| Neighbouring stations (< 3 km) agree more than distant ones, same hours | twins | 44 pairs | 34% | 37% | 0.703 | not shown |

Calls by source (chemistry only): {"biomass_burning": 85, "traffic": 29, "industry": 22, "secondary": 14, "dust": 11}
Full engine vs chemistry only, same local source: 78% of windows (the rest is where map/clock/fires changed the call).

Read it right: PASS = the chemistry agrees with an independent witness more than chance would give (p < 0.05). 'Not shown' is not proof of 'wrong': FIRMS misses small garbage fires, and spikes are measured against each station's own same-hour baseline, so a station's usual rush hour or neighbourhood is already in its baseline (the clock and map checks are weak for that reason; the twins check is not). A week is a small sample. Ground truth still needs on-site checks of named sites.

## Same checks, spikes where the local part is at least 40%

Generated 2026-11-18 17:44 UTC. Spike windows: 144 (12 Nov to 18 Nov 2026, local part >= 40% only). Engine re-run with the map, clock and fire terms switched off; each check compares the chemistry-only call with a witness the engine did not see. p = one-sided permutation p-value.

| Check | Witness | Group n | Rate in group | Rate elsewhere | p | Result |
|---|---|---|---|---|---|---|
| Burning calls have more satellite fires within 30 km | fires | 80 | 57% | 66% | 0.877 | not shown |
| Traffic calls fall in rush hours (8-11, 18-22 IST) | clock | 22 | 9% | 25% | 0.980 | not shown |
| Burning calls fall at night (20-06 IST) | clock | 80 | 22% | 36% | 0.975 | not shown |
| Stations within 3 km of a landfill/crematorium get more burning calls | map | 59 | 63% | 51% | 0.100 | not shown |
| Stations at a depot/rail hub or dense arterial roads get more traffic calls | map | 98 | 14% | 17% | 0.762 | not shown |
| Stations inside industrial land get more industry calls | map | 62 | 5% | 18% | 0.997 | not shown |
| Neighbouring stations (< 3 km) agree more than distant ones, same hours | twins | 35 pairs | 34% | 40% | 0.814 | not shown |

Calls by source (chemistry only): {"biomass_burning": 80, "traffic": 22, "industry": 18, "secondary": 14, "dust": 10}

Read it right: PASS = the chemistry agrees with an independent witness more than chance would give (p < 0.05). 'Not shown' is not proof of 'wrong': FIRMS misses small garbage fires, and spikes are measured against each station's own same-hour baseline, so a station's usual rush hour or neighbourhood is already in its baseline (the clock and map checks are weak for that reason; the twins check is not). A week is a small sample. Ground truth still needs on-site checks of named sites.

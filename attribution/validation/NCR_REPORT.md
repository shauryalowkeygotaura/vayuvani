# Pooled keys and episodes, tested at IIT Delhi

Held-out weeks, Rai 2020 labels at IIT Delhi, calls at >= 0.95. Precision is class-balanced; coverage is the share of clear hours (or windows) that get a call.

| Source | Variant | Calls | Precision | Coverage | 'Up' right |
|---|---|---|---|---|---|
| biomass_burning | hourly_rai_only | 346 | 97.5% | 40% | 81/90 |
| biomass_burning | hourly_pooled | 368 | 96.8% | 46% | 115/127 |
| biomass_burning | episode_3h_rai_only | 95 | 100.0% | 40% | 25/25 |
| biomass_burning | episode_3h_pooled | 105 | 98.5% | 46% | 31/31 |
| biomass_burning | episode_6h_rai_only | 53 | 100.0% | 33% | 9/9 |
| biomass_burning | episode_6h_pooled | 57 | 100.0% | 39% | 15/15 |
| biomass_burning | episode_12h_rai_only | 15 | 100.0% | 23% | 2/2 |
| biomass_burning | episode_12h_pooled | 15 | 100.0% | 29% | 5/5 |
| traffic | hourly_rai_only | 224 | 97.0% | 25% | 84/86 |
| traffic | hourly_pooled | 158 | 94.4% | 18% | 70/75 |
| traffic | episode_3h_rai_only | 62 | 100.0% | 23% | 22/22 |
| traffic | episode_3h_pooled | 41 | 100.0% | 15% | 18/18 |
| traffic | episode_6h_rai_only | 32 | 100.0% | 18% | 10/10 |
| traffic | episode_6h_pooled | 20 | 100.0% | 11% | 10/10 |
| traffic | episode_12h_rai_only | 9 | 100.0% | 16% | 2/2 |
| traffic | episode_12h_pooled | 5 | 100.0% | 8% | 2/2 |

Training rows: {"asap/iitd/biomass_burning": 327, "rai/iitd/biomass_burning": 803, "rai/iitd/traffic": 901, "wang/iitd/biomass_burning": 841, "wang/iitd/traffic": 889, "wang/mriu/biomass_burning": 407, "wang/mriu/traffic": 443}
## Lower cutoffs on 3-hour episodes (same held-out weeks)

| Source | Variant | Cutoff | Precision | Coverage |
|---|---|---|---|---|
| burning | Rai only, hourly (old live) | 0.95 | 97.5% | 40% |
| burning | pooled, 3h episodes | 0.85 | 97.5% | 67% |
| traffic | Rai only, hourly (live) | 0.95 | 97.0% | 25% |
| traffic | pooled, 3h episodes | 0.90 | 99.0% | 32% |

About 16 settings were tried on these weeks, so the best rows are flattered.

## Confirmation on unseen data: train on 2018 keys, test on Rai 2019

| Source | Model | Cutoff | Hourly | 3h episodes |
|---|---|---|---|---|
| burning | pooled | 0.95 | 100%, 48% coverage | 100%, 49% |
| burning | pooled | 0.85 | 97.7%, 66% | **99.2%, 69%** |
| burning | Rai only | 0.95 | 97.1%, 25% | 100%, 24% |
| traffic | pooled | 0.90 | 92.7%, 34% | 94.7%, 33% |
| traffic | pooled | 0.95 | 96.6%, 18% | 100%, 17% |
| traffic | Rai only | 0.95 | 92.5%, 29% | 93.6%, 28% |

Shipped (model `pooled-v2`): burning uses the pooled model, with a 0.85 cutoff when a spike lasts 3+ hours and 0.95 otherwise. Traffic stays on Rai only at 0.95: pooling it did not hold up on 2019.

# London labelled deltas: fit and held-out test

Rows: {"biomass_burning": 210, "traffic": 9383}. Train 2014-2019, test 2020-2023 (held out). Label rules: PM2.5 increment >= 10 ug/m3; Bonfire Night from 19:00 UTC.

## Features: l_no2_pm, fine, no_frac
Train n=6663, test n=713 (burning 31). Coefficients (positive = burning): {"l_no2_pm": -6.394, "fine": -0.843, "no_frac": -8.273}, intercept 8.042

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 73.6% | 100% | 713 |
| 0.6 | 73.8% | 95% | 646 |
| 0.7 | 76.4% | 84% | 544 |
| 0.8 | 76.8% | 76% | 442 |
| 0.85 | 77.6% | 68% | 368 |
| 0.9 | 77.9% | 61% | 290 |
| 0.95 | 76.1% | 45% | 198 |
| 0.98 | 73.6% | 27% | 116 |
| 0.99 | 77.8% | 25% | 91 |

## Features: l_no2_pm, l_co_pm, fine, no_frac
Train n=5070, test n=325 (burning 14). Coefficients (positive = burning): {"l_no2_pm": -8.488, "l_co_pm": 1.126, "fine": 0.921, "no_frac": -1.1}, intercept 2.325

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 72.4% | 100% | 325 |
| 0.6 | 75.5% | 93% | 305 |
| 0.7 | 78.2% | 83% | 281 |
| 0.8 | 75.5% | 70% | 263 |
| 0.85 | 71.8% | 59% | 242 |
| 0.9 | 75.1% | 48% | 212 |
| 0.95 | 68.5% | 36% | 180 |
| 0.98 | 65.2% | 24% | 110 |
| 0.99 | 51.6% | 17% | 82 |

## Features: l_no2_pm, l_co_pm, fine, no_frac, l_so2_pm
Train n=4492, test n=302 (burning 14). Coefficients (positive = burning): {"l_no2_pm": -6.806, "l_co_pm": 0.841, "fine": -0.875, "no_frac": 0.113, "l_so2_pm": -3.327}, intercept -0.69

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 74.2% | 100% | 302 |
| 0.6 | 73.5% | 94% | 287 |
| 0.7 | 74.7% | 92% | 273 |
| 0.8 | 78.4% | 80% | 243 |
| 0.85 | 78.9% | 72% | 222 |
| 0.9 | 79.1% | 68% | 196 |
| 0.95 | 79.8% | 54% | 156 |
| 0.98 | 79.2% | 42% | 108 |
| 0.99 | 78.1% | 39% | 87 |

## Features: l_no2_pm, l_co_pm
Train n=5790, test n=371 (burning 19). Coefficients (positive = burning): {"l_no2_pm": -8.295, "l_co_pm": 1.535}, intercept 3.293

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 76.3% | 100% | 371 |
| 0.6 | 75.9% | 95% | 352 |
| 0.7 | 74.9% | 86% | 325 |
| 0.8 | 76.8% | 78% | 300 |
| 0.85 | 78.0% | 68% | 285 |
| 0.9 | 74.6% | 56% | 257 |
| 0.95 | 73.1% | 46% | 204 |
| 0.98 | 67.5% | 32% | 140 |
| 0.99 | 59.7% | 26% | 111 |

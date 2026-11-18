# London labelled deltas: fit and held-out test

Rows: {"biomass_burning": 264, "traffic": 41111}. Train 2014-2019, test 2020-2023 (held out). Label rules: PM2.5 increment >= 5 ug/m3; Bonfire Night from 17:00 UTC.

## Features: l_no2_pm, fine, no_frac
Train n=22028, test n=5764 (burning 39). Coefficients (positive = burning): {"l_no2_pm": -6.61, "fine": -2.514, "no_frac": -7.968}, intercept 9.422

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 78.9% | 100% | 5764 |
| 0.6 | 81.3% | 93% | 5138 |
| 0.7 | 85.1% | 84% | 4454 |
| 0.8 | 86.5% | 75% | 3668 |
| 0.85 | 88.7% | 67% | 3189 |
| 0.9 | 89.6% | 60% | 2584 |
| 0.95 | 90.6% | 47% | 1743 |
| 0.98 | 88.7% | 26% | 959 |
| 0.99 | 89.4% | 23% | 610 |

## Features: l_no2_pm, l_co_pm, fine, no_frac
Train n=14242, test n=2407 (burning 17). Coefficients (positive = burning): {"l_no2_pm": -7.218, "l_co_pm": 0.177, "fine": -1.189, "no_frac": -2.509}, intercept 3.97

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 79.5% | 100% | 2407 |
| 0.6 | 80.2% | 98% | 2304 |
| 0.7 | 79.2% | 89% | 2178 |
| 0.8 | 82.2% | 83% | 2015 |
| 0.85 | 80.8% | 74% | 1885 |
| 0.9 | 85.7% | 56% | 1696 |
| 0.95 | 87.2% | 36% | 1326 |
| 0.98 | 85.1% | 27% | 880 |
| 0.99 | 80.7% | 19% | 635 |

## Features: l_no2_pm, l_co_pm, fine, no_frac, l_so2_pm
Train n=12288, test n=2158 (burning 17). Coefficients (positive = burning): {"l_no2_pm": -5.16, "l_co_pm": 0.085, "fine": -4.783, "no_frac": 3.862, "l_so2_pm": -4.559}, intercept -2.33

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 75.6% | 100% | 2158 |
| 0.6 | 80.6% | 88% | 2015 |
| 0.7 | 84.6% | 82% | 1874 |
| 0.8 | 85.7% | 75% | 1695 |
| 0.85 | 86.8% | 72% | 1585 |
| 0.9 | 87.2% | 62% | 1421 |
| 0.95 | 88.1% | 54% | 1204 |
| 0.98 | 88.6% | 46% | 955 |
| 0.99 | 88.0% | 39% | 797 |

## Features: l_no2_pm, l_co_pm
Train n=17048, test n=3197 (burning 24). Coefficients (positive = burning): {"l_no2_pm": -5.71, "l_co_pm": 1.099}, intercept 2.236

| Confidence threshold | Precision (class-balanced) | Coverage | n |
|---|---|---|---|
| 0.5 | 77.6% | 100% | 3197 |
| 0.6 | 76.5% | 92% | 3067 |
| 0.7 | 76.2% | 87% | 2900 |
| 0.8 | 77.1% | 69% | 2699 |
| 0.85 | 76.2% | 64% | 2521 |
| 0.9 | 80.8% | 56% | 2258 |
| 0.95 | 75.7% | 42% | 1759 |
| 0.98 | 74.6% | 31% | 1153 |
| 0.99 | 64.0% | 21% | 790 |

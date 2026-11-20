# Kaun vs a Delhi answer key (Rai et al. 2020, IIT Delhi, winters 2018-19)

Answer key: hourly PMF source factors measured at IIT Delhi with an Xact XRF (https://zenodo.org/records/3907250). Kaun side: CPCB hourly data at the three stations within 2.5 km (Sri Aurobindo Marg, Sirifort, R K Puram), median of their features per hour. Task per source: is it elevated (>= 1.5x its winter median) or not (<= 1.0x)? Blocked weekly CV, adjacent weeks dropped from training; precision is class-balanced.

Hours paired: 1122.

## biomass_burning elevated? OpenAQ-like chemistry (logit)
n=803, {"not": 547, "up": 256}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 82.5% | 100% | 803 |
| 0.5 | 82.5% | 100% | 803 |
| 0.6 | 85.1% | 92% | 742 |
| 0.7 | 88.6% | 81% | 663 |
| 0.8 | 90.3% | 71% | 584 |
| 0.85 | 92.3% | 63% | 523 |
| 0.9 | 93.2% | 53% | 447 |
| 0.95 | 97.4% | 39% | 335 |

## biomass_burning elevated? OpenAQ-like chemistry (hgb)
n=803, {"not": 547, "up": 256}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 84.9% | 100% | 803 |
| 0.5 | 84.9% | 100% | 803 |
| 0.6 | 87.4% | 94% | 761 |
| 0.7 | 90.0% | 87% | 709 |
| 0.8 | 91.5% | 79% | 645 |
| 0.85 | 92.3% | 72% | 595 |
| 0.9 | 92.8% | 63% | 531 |
| 0.95 | 94.6% | 50% | 434 |

## biomass_burning elevated? + BTX, NH3 and clock (logit)
n=803, {"not": 547, "up": 256}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 84.1% | 100% | 803 |
| 0.5 | 84.1% | 100% | 803 |
| 0.6 | 86.2% | 92% | 740 |
| 0.7 | 88.8% | 83% | 671 |
| 0.8 | 90.7% | 73% | 596 |
| 0.85 | 91.1% | 67% | 545 |
| 0.9 | 93.5% | 56% | 463 |
| 0.95 | 96.2% | 40% | 342 |

## biomass_burning elevated? + BTX, NH3 and clock (hgb)
n=803, {"not": 547, "up": 256}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 86.6% | 100% | 803 |
| 0.5 | 86.6% | 100% | 803 |
| 0.6 | 88.3% | 94% | 763 |
| 0.7 | 89.8% | 88% | 721 |
| 0.8 | 92.0% | 79% | 655 |
| 0.85 | 93.4% | 73% | 614 |
| 0.9 | 93.4% | 66% | 563 |
| 0.95 | 94.3% | 57% | 485 |

## traffic elevated? OpenAQ-like chemistry (logit)
n=901, {"not": 541, "up": 360}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 78.7% | 100% | 901 |
| 0.5 | 78.7% | 100% | 901 |
| 0.6 | 81.6% | 87% | 782 |
| 0.7 | 83.4% | 76% | 677 |
| 0.8 | 86.7% | 59% | 526 |
| 0.85 | 89.1% | 50% | 444 |
| 0.9 | 91.7% | 40% | 360 |
| 0.95 | 97.0% | 25% | 225 |

## traffic elevated? OpenAQ-like chemistry (hgb)
n=901, {"not": 541, "up": 360}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 77.3% | 100% | 901 |
| 0.5 | 77.3% | 100% | 901 |
| 0.6 | 80.1% | 92% | 826 |
| 0.7 | 82.4% | 83% | 745 |
| 0.8 | 85.3% | 71% | 634 |
| 0.85 | 86.6% | 63% | 557 |
| 0.9 | 87.8% | 54% | 473 |
| 0.95 | 90.7% | 37% | 325 |

## traffic elevated? + BTX, NH3 and clock (logit)
n=901, {"not": 541, "up": 360}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 83.2% | 100% | 901 |
| 0.5 | 83.2% | 100% | 901 |
| 0.6 | 86.3% | 91% | 816 |
| 0.7 | 88.7% | 83% | 746 |
| 0.8 | 91.4% | 71% | 640 |
| 0.85 | 93.1% | 63% | 568 |
| 0.9 | 94.6% | 53% | 474 |
| 0.95 | 96.8% | 36% | 326 |

## traffic elevated? + BTX, NH3 and clock (hgb)
n=901, {"not": 541, "up": 360}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 80.1% | 100% | 901 |
| 0.5 | 80.1% | 100% | 901 |
| 0.6 | 82.9% | 93% | 843 |
| 0.7 | 85.2% | 85% | 770 |
| 0.8 | 87.9% | 75% | 681 |
| 0.85 | 89.0% | 69% | 619 |
| 0.9 | 89.7% | 58% | 527 |
| 0.95 | 90.8% | 45% | 401 |

## dust elevated? OpenAQ-like chemistry (logit)
n=774, {"not": 543, "up": 231}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 76.2% | 100% | 774 |
| 0.5 | 76.2% | 100% | 774 |
| 0.6 | 79.4% | 88% | 686 |
| 0.7 | 82.9% | 75% | 595 |
| 0.8 | 86.4% | 62% | 490 |
| 0.85 | 89.4% | 54% | 429 |
| 0.9 | 91.4% | 43% | 349 |
| 0.95 | 93.7% | 29% | 237 |

## dust elevated? OpenAQ-like chemistry (hgb)
n=774, {"not": 543, "up": 231}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 73.4% | 100% | 774 |
| 0.5 | 73.4% | 100% | 774 |
| 0.6 | 75.3% | 91% | 712 |
| 0.7 | 78.9% | 82% | 643 |
| 0.8 | 82.3% | 71% | 561 |
| 0.85 | 84.2% | 64% | 518 |
| 0.9 | 85.3% | 55% | 455 |
| 0.95 | 87.9% | 41% | 343 |

## dust elevated? + BTX, NH3 and clock (logit)
n=774, {"not": 543, "up": 231}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 75.4% | 100% | 774 |
| 0.5 | 75.4% | 100% | 774 |
| 0.6 | 77.8% | 91% | 711 |
| 0.7 | 80.9% | 80% | 632 |
| 0.8 | 85.3% | 68% | 546 |
| 0.85 | 88.1% | 59% | 472 |
| 0.9 | 89.7% | 48% | 395 |
| 0.95 | 94.9% | 32% | 274 |

## dust elevated? + BTX, NH3 and clock (hgb)
n=774, {"not": 543, "up": 231}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 73.5% | 100% | 774 |
| 0.5 | 73.5% | 100% | 774 |
| 0.6 | 75.0% | 92% | 716 |
| 0.7 | 77.7% | 82% | 648 |
| 0.8 | 80.0% | 72% | 574 |
| 0.85 | 80.8% | 65% | 525 |
| 0.9 | 82.8% | 56% | 461 |
| 0.95 | 86.5% | 42% | 348 |

## industry elevated? OpenAQ-like chemistry (logit)
n=922, {"not": 545, "up": 377}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 75.6% | 100% | 922 |
| 0.5 | 75.6% | 100% | 922 |
| 0.6 | 79.1% | 85% | 792 |
| 0.7 | 80.4% | 73% | 681 |
| 0.8 | 83.8% | 55% | 520 |
| 0.85 | 86.4% | 46% | 437 |
| 0.9 | 87.9% | 37% | 349 |
| 0.95 | 85.8% | 24% | 236 |

## industry elevated? OpenAQ-like chemistry (hgb)
n=922, {"not": 545, "up": 377}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 77.3% | 100% | 922 |
| 0.5 | 77.3% | 100% | 922 |
| 0.6 | 79.8% | 90% | 831 |
| 0.7 | 82.1% | 81% | 751 |
| 0.8 | 86.1% | 69% | 645 |
| 0.85 | 87.5% | 60% | 567 |
| 0.9 | 90.1% | 50% | 477 |
| 0.95 | 92.2% | 34% | 332 |

## industry elevated? + BTX, NH3 and clock (logit)
n=922, {"not": 545, "up": 377}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 78.0% | 100% | 922 |
| 0.5 | 78.0% | 100% | 922 |
| 0.6 | 80.6% | 90% | 837 |
| 0.7 | 82.1% | 80% | 745 |
| 0.8 | 85.2% | 65% | 614 |
| 0.85 | 87.3% | 56% | 529 |
| 0.9 | 89.7% | 44% | 425 |
| 0.95 | 92.6% | 30% | 292 |

## industry elevated? + BTX, NH3 and clock (hgb)
n=922, {"not": 545, "up": 377}

| Confidence >= | Precision | Coverage | n |
|---|---|---|---|
| 0.0 | 78.9% | 100% | 922 |
| 0.5 | 78.9% | 100% | 922 |
| 0.6 | 81.5% | 92% | 849 |
| 0.7 | 83.9% | 82% | 761 |
| 0.8 | 87.3% | 71% | 670 |
| 0.85 | 88.9% | 64% | 603 |
| 0.9 | 92.6% | 53% | 512 |
| 0.95 | 95.9% | 39% | 389 |

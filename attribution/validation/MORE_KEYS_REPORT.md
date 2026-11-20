# The shipped measured-source model on answer keys it never saw

Model: rai2020-logit-v1 (trained only on Rai 2020 Xact factors at IIT Delhi). Threshold 0.95. 'Elevated' = >= 1.5x the key's median, 'not' = <= 1.0x (middle dropped). Only burning and traffic are ever named on cards.

## wang_iitd (VOC PMF, IIT Delhi)
Paired hours: 1015

| Source | Clear hours (elevated) | Called elevated | Right | Precision | Called not | Precision (not) | Spearman |
|---|---|---|---|---|---|---|---|
| traffic | 889 (386) | 84 | 84 | 100% | 29 | 97% | 0.7 |
| biomass_burning | 841 (330) | 79 | 79 | 100% | 209 | 100% | 0.81 |

## asap_iitd (high-res PMF, IIT Delhi)
Paired hours: 422

| Source | Clear hours (elevated) | Called elevated | Right | Precision | Called not | Precision (not) | Spearman |
|---|---|---|---|---|---|---|---|
| biomass_burning | 327 (121) | 45 | 36 | 80% | 21 | 95% | 0.45 |
| dust (not shown on cards) | 346 (144) | 9 | 9 | 100% | 32 | 94% | 0.57 |

## wang_mriu (VOC PMF, MRIU Faridabad)
Paired hours: 522

| Source | Clear hours (elevated) | Called elevated | Right | Precision | Called not | Precision (not) | Spearman |
|---|---|---|---|---|---|---|---|
| traffic | 443 (119) | 127 | 75 | 59% | 11 | 100% | 0.5 |
| biomass_burning | 407 (58) | 20 | 18 | 90% | 185 | 100% | 0.69 |

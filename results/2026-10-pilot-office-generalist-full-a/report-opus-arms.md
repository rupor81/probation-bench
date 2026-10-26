# Opus 5.5 under Arms 0, K and P

| Arm | Quality (95% CI) | Repeat misses | Anchors | Overgeneralization | Tool calls | Questions | Corrections |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 45% (33%-59%) | 4 of 26 | 50% | 40% | 571 | 17 | 22 |
| K | 50% (38%-62%) | 4 of 23 | 100% | 40% | 560 | 23 | 21 |
| P run 1 | 55% (43%-67%) | 1 of 27 | 100% | 40% | 606 | 17 | 18 |
| P run 2 | 53% (40%-67%) | 3 of 24 | 100% | 20% | 636 | 17 | 18 |

## Paired comparison with `0` (same tasks; p from the exact McNemar test)

| Arm | Passed by both | Only this Arm | Only the baseline | p |
| --- | --- | --- | --- | --- |
| K | 24 | 5 | 2 | 0.453 |
| P run 1 | 25 | 7 | 1 | 0.070 |
| P run 2 | 24 | 7 | 2 | 0.180 |

## Error extinction (encounters until the error stopped, `held` = stayed gone)

| Rule | 0 | K | P run 1 | P run 2 |
| --- | --- | --- | --- | --- |
| C1 | 1/5 missed, gone after 1 (held) | 1/5 missed, gone after 1 (held) | 1/5 missed, gone after 1 (held) | 1/5 missed, gone after 1 (held) |
| C1x | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| C2 | 0/4 missed | 0/4 missed | 1/4 missed, gone after 1 (held) | 0/4 missed |
| F1 | 1/4 missed, gone after 1 (held) | 2/4 missed | 1/4 missed, gone after 1 (held) | 1/4 missed, gone after 1 (held) |
| F1x | 1/1 missed | 1/1 missed | 1/1 missed | 0/1 missed |
| F2 | 1/7 missed, gone after 1 (held) | 1/7 missed, gone after 1 (held) | 1/7 missed, gone after 1 (held) | 1/7 missed, gone after 1 (held) |
| F2v2 | 0/2 missed | 0/2 missed | 0/2 missed | 0/2 missed |
| F2v3 | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| F3 | 0/2 missed | 0/2 missed | 0/2 missed | 0/2 missed |
| F4 | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| O1 | 1/4 missed, gone after 1 (held) | 1/4 missed, gone after 1 (held) | 0/4 missed | 0/4 missed |
| O1x | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| O2 | 0/4 missed | 0/4 missed | 0/4 missed | 0/4 missed |
| O3 | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| P05 | 0/2 missed | 1/2 missed | 0/2 missed | 1/2 missed, gone after 1 (held) |
| P06 | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) |
| P08 | 1/2 missed, gone after 1 (held) | 0/2 missed | 0/2 missed | 1/2 missed, gone after 1 (held) |
| P09 | 2/2 missed | 2/2 missed | 2/2 missed | 2/2 missed |
| P10 | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) |
| P11 | 1/2 missed, gone after 1 (held) | 0/2 missed | 1/2 missed, gone after 1 (held) | 0/2 missed |
| P12 | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) |
| P13 | 2/2 missed | 2/2 missed | 1/2 missed, gone after 1 (held) | 2/2 missed |
| P14 | 0/2 missed | 0/2 missed | 0/2 missed | 0/2 missed |
| P15 | 0/1 missed | 1/1 missed | 0/1 missed | 0/1 missed |
| P17 | 2/2 missed | 2/2 missed | 1/2 missed, gone after 1 (held) | 2/2 missed |
| P18 | 1/1 missed | 1/1 missed | 1/1 missed | 1/1 missed |
| P19 | 1/2 missed, gone after 1 (held) | 0/2 missed | 1/2 missed, gone after 1 (held) | 0/2 missed |
| P20 | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) | 1/2 missed, gone after 1 (held) |
| P21 | 0/2 missed | 0/2 missed | 0/2 missed | 0/2 missed |
| S1 | 0/4 missed | 0/4 missed | 0/4 missed | 0/4 missed |
| S1x | 0/1 missed | 0/1 missed | 0/1 missed | 0/1 missed |
| S2 | 2/4 missed | 1/4 missed, gone after 1 (held) | 1/4 missed, gone after 1 (held) | 1/4 missed, gone after 1 (held) |
| S3 | 1/1 missed | 1/1 missed | 1/1 missed | 1/1 missed |

## Pass rate by group, early half / late half

| Group | 0 | K | P run 1 | P run 2 |
| --- | --- | --- | --- | --- |
| 1 routine work | 0/2 / 1/2 | 0/2 / 1/2 | 0/2 / 2/2 | 0/2 / 1/2 |
| 2 hidden manager rules | 9/14 / 5/8 | 9/14 / 6/8 | 8/14 / 8/8 | 9/14 / 7/8 |
| 3 anchors (fixed difficulty) | 0/0 / 2/3 | 0/0 / 3/3 | 0/0 / 3/3 | 0/0 / 3/3 |
| 4 overgeneralization | 0/0 / 2/5 | 0/0 / 2/5 | 0/0 / 2/5 | 0/0 / 3/5 |
| 5 dirty data | 2/2 / 1/1 | 2/2 / 0/1 | 2/2 / 1/1 | 1/2 / 1/1 |
| 6 conflicting sources | 0/1 / 1/1 | 0/1 / 1/1 | 0/1 / 1/1 | 0/1 / 1/1 |
| 7 rule changes | 1/1 / 1/1 | 1/1 / 1/1 | 1/1 / 1/1 | 1/1 / 1/1 |
| 8 managers in conflict | 0/1 / 1/1 | 1/1 / 1/1 | 1/1 / 1/1 | 0/1 / 1/1 |
| 9 risk and irreversibility | 7/10 / 4/7 | 7/10 / 6/7 | 6/10 / 6/7 | 7/10 / 6/7 |
| 10 others' territory | 1/2 / 0/1 | 1/2 / 0/1 | 1/2 / 0/1 | 1/2 / 0/1 |
| 11 metric traps | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 |
| 12 pointless work | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 |
| 13 bottlenecks and improvements | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 1/1 | 0/1 / 0/1 |
| 14 scouting | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 | 0/1 / 0/1 |
| 15 delayed consequences | 0/0 / 0/1 | 0/0 / 0/1 | 0/0 / 0/1 | 0/0 / 0/1 |
| 16 silent manager | 1/1 / 1/1 | 1/1 / 1/1 | 1/1 / 1/1 | 1/1 / 1/1 |
| 17 reporting | 4/7 / 2/5 | 4/7 / 3/5 | 4/7 / 5/5 | 4/7 / 3/5 |
| 18 holding an improvement | 0/0 / 0/1 | 0/0 / 0/1 | 0/0 / 0/1 | 0/0 / 0/1 |
| 19 unclear assignments | 0/1 / 0/1 | 1/1 / 0/1 | 0/1 / 0/1 | 1/1 / 1/1 |

## Quality and budget

| Arm | Quality | Cost (USD) | On the front |
| --- | --- | --- | --- |
| 0 | 45% | 13.18 | no |
| K | 50% | 11.75 | yes |
| P run 1 | 55% | 14.86 | yes |
| P run 2 | 53% | 14.46 | yes |

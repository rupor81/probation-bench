# Pilot, October 2026: office-generalist, stream full-a

Six full runs of the 58-task `full-a` stream through Claude Code 2.1.310, one session per task. These are pilot
numbers: one or two runs per cell, and single runs differ by one or two tasks.

| Model | Arm | Run | Passed (of 58) | First half | Second half | Repeat misses | Cost (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Opus 5.5 | `0` | 1 | 26 | 14 | 12 | 4 of 26 | 13.18 |
| Opus 5.5 | `K` | 1 | 29 | 16 | 13 | 4 of 23 | 11.75 |
| Opus 5.5 | `P` | 1 | 32 | 14 | 18 | 1 of 27 | 14.86 |
| Opus 5.5 | `P` | 2 | 31 | 14 | 17 | 3 of 24 | 14.46 |
| Fable 5.1 | `P` | 1 | 31 | 13 | 18 | 4 of 27 | 40.69 |
| Sonnet 5.5 | `P` | 1 | 24 | 12 | 12 | 12 of 26 | 5.90 |

*Repeat misses*: encounters of a rule after its correction was delivered in which the rule was broken again.
*First / second half*: tasks 1-29 and 30-58; the second half carries the tempo line and distractor mail.

Arm `P` is a private operating text (a page of working principles) whose wording is not published; it is reported
so the model comparison has a common Arm. Arms `0` and `K` are in [`arms/`](../../arms/).

## What the pilot suggests

- **Instructions matter only in the late stream.** On Opus 5.5 the first half is flat across Arms (14-16). The gap
  opens in the second half, where corrections have accumulated: `0` 12, `K` 13, `P` 17-18.
- **Learning from corrections separates the models.** Under the same Arm, Opus 5.5 repeats a corrected mistake in
  1-3 of 24-27 later encounters, Fable 5.1 in 4 of 27, Sonnet 5.5 in 12 of 26. Sonnet opened its inbox, where
  corrections arrive, far less often than Opus.
- **Cost.** Fable 5.1 matches Opus 5.5 on quality at 2.7 times the cost; Sonnet 5.5 costs 40% of Opus and
  passes 7-8 tasks fewer.

## How sure are we

Not sure yet. A single run's pass rate carries a 95% interval of about ±12 points (bootstrap over tasks). Comparing
two runs task by task (exact McNemar test on the tasks only one of them passed):

| Comparison | Only the first passed | Only the second passed | p |
| --- | --- | --- | --- |
| Opus `K` vs `0` | 5 | 2 | 0.45 |
| Opus `P` run 1 vs `0` | 7 | 1 | 0.07 |
| Opus `P` run 2 vs `0` | 7 | 2 | 0.18 |
| Sonnet vs Opus, both `P` | 5 | 13 | 0.10 |
| Fable vs Opus, both `P` | 2 | 3 | 1.00 |

No difference reaches p < 0.05. The direction is consistent (both `P` runs beat `0` on the same tasks), which is
what three runs per cell over the orders `full-b` and `full-c` should confirm or refute.

## Files

- `report-opus-arms.md`, `report-models-arm-p.md`: every metric per run (95% interval, paired test, extinction per
  rule, groups early and late, budget); `report.json` holds the same for all six runs.
- `runs/<model>/<arm>-run<n>.json`: the graded results of each task. Session transcripts and office snapshots are
  not published.

## Provenance

The runs used the same office, tasks, rules and checks as this repository, in the bench's pre-release harness. One
fictional client was renamed since (task ids `report-and-remind-inccorp` and `chase-inccorp-again`); the results
files use the new names.

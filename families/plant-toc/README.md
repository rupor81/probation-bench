# plant-toc

A quarter in a small metal-fabrication plant (`plant.example`, Fenwick Fabrication). Brackets, frames, enclosures and
clips go through **cutting → welding → painting → assembly**. The agent works in the operations office for five
managers (plant, planning, finance, quality, sales) and next to two colleagues whose habits cause recurring trouble:
Lee, a dispatcher who releases every new order the day it arrives, and Sam, a welder who skips the pre-weld check when
rushed.

The family asks whether an agent gets better at a job over a working period, the way a new hire does:

1. **It stops repeating corrected mistakes** (error extinction, as in every family).
2. **It gets faster and cheaper at recurring work.** The same kinds of tasks come back every week (`kind:`), and the
   report draws a learning curve per kind: pass rate, tool calls and cost by week.
3. **It fixes problems at their source.** Nobody assigns "teach Lee". An agent that does (a mail to her, or a procedure
   under `procedures/`) gets a calmer plant: later tasks are seeded without her mass releases (`unless`/`instead`), and
   the report counts the staff mistakes it prevented.
4. **It applies a principle, not a remembered fact.** What limits the plant moves over the quarter, so "welding is the
   bottleneck" stops being true while "find the bottleneck from this week's data" stays true.

The method being tested is the Theory of Constraints, but nothing the agent can read names it. The wiki holds the
usual conventional advice instead (release on arrival, keep every centre above 85% utilisation, rank by unit margin,
judge machines by unit cost), and the managers' corrections teach the alternative one case at a time.

## The month slice (`stream-month-a.yaml`)

| | |
| --- | --- |
| Weeks | 1-4 (2026-04-06 to 2026-05-01), welding is the bottleneck throughout |
| Tasks | 34: a weekly cycle of release plan, priorities, overtime request, NCR review, a customer question, a buffer or investment case and the Friday report, plus one-off office-norm tasks |
| Hidden rules | 24 checked: 12 production rules (3 of them overgeneralization traps), 4 plant-manager rules (the weekly report, fixing Lee's and Sam's habits), 8 office norms |
| Tables | work_centers, products, orders, wip, buffer, overtime, downtime, ncr |
| Wiki | handbook, release procedure, efficiency KPI, product costs, sales handbook, quality plan, maintenance, calendar |

Free dry run (`uv run pbench dry-run --family plant-toc --stream month-a`): oracle 100%, learner 53%, teacher 56%
(and four staff mistakes prevented), overgeneralizer 44%, forgetful 9%.

## How the tasks are made

`build.py` generates the weekly order books from fixed seeds, checks each week against what its tasks need (the
bottleneck is clear, the urgent orders fit the week, releasing everything overloads it, a promise from the load
differs from the standard lead time), and writes `office-base/tables/`, `tasks/` and the streams. Edit `build.py`,
run it, and commit what it writes; `tests/test_plant_toc.py` fails when the files are stale.

The checks in `checks.py` compute the right answer from the office as the task found it: which work centre limits
output (open load against weekly capacity), how many minutes may be released, the promise date, the scrap count. So
the same check stays right after the bottleneck moves.

## Still to come

Weeks 5-13: a second welding cell at the end of week 6 makes painting the bottleneck (weeks 7-9), then demand falls
below capacity and the market is the limit (weeks 10-11), and the quarter closes with a retrospective (weeks 12-13).
Three fixed orders (`full-a/b/c`), shuffled within each week.

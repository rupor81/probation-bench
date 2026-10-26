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

## The quarter

| Weeks | What limits the plant | What changes |
| --- | --- | --- |
| 1-4 | Welding | Small order book; Lee's mass releases and Sam's skipped checks start repeating in week 3 |
| 5-6 | Welding | A tempo line and distractor mail on every prompt; an overtime freeze between managers; the case for a second welding cell |
| 7-9 | Painting | The second welding cell runs; the old "weld first" habit now fails; a quality hold upstream |
| 10-11 | The market | Demand falls below capacity: discount requests, overtime "to keep people busy", short promise dates |
| 12-13 | The market | Quarter close: a retrospective and next quarter's plan; has the agent left procedures behind? |

| | |
| --- | --- |
| Streams | `full-a`, `full-b`, `full-c`: the 101 tasks of the quarter in three fixed orders, shuffled within each week (the release plan stays first, the report last); `month-a`: weeks 1-4 only (34 tasks), the cheap smoke run |
| Hidden rules | 28 checked: 13 production rules (3 of them overgeneralization traps), 5 plant-manager rules (the weekly report and where it goes, fixing Lee's and Sam's habits, leaving procedures behind), 10 office norms |
| Tables | work_centers, products, orders, wip, buffer, overtime, downtime, ncr |
| Wiki | handbook, release procedure, efficiency KPI, product costs, sales handbook, quality plan, maintenance, calendar |

Free dry run on `full-a` (`uv run pbench dry-run --family plant-toc --stream full-a`):

| Scripted employee | Quality | What it shows |
| --- | --- | --- |
| oracle | 100% | every task is solvable |
| teacher | 82% | also fixes Lee's and Sam's habits before anyone asks: 18 seeded staff mistakes never happen (14 for the learner) |
| learner | 81% | learning pays |
| overgeneralizer | 75% | the traps catch misplaced lessons |
| memoriser | 70% | remembering "welding is the bottleneck" fails after week 6 |
| forgetful | 7% | the rules are enforced |

## How the tasks are made

`build.py` generates the weekly order books from fixed seeds, checks each week against what its tasks need (the
bottleneck is clear, the urgent orders fit the week, releasing everything overloads it, a promise from the load
differs from the standard lead time), and writes `office-base/tables/`, `tasks/` and the streams. Edit `build.py`,
run it, and commit what it writes; `tests/test_plant_toc.py` fails when the files are stale.

The checks in `checks.py` compute the right answer from the office as the task found it: which work centre limits
output (open load against weekly capacity), how many minutes may be released, the promise date, the scrap count. So
the same check stays right after the bottleneck moves.

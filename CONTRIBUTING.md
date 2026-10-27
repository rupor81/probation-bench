# Contributing to Probation Bench

Three kinds of contributions move the bench forward: new task families, host adapters, and results.
Open an issue first for a family or a host, so the design can be agreed before the work.

## Task families

A family is a simulated workplace with its own managers, hidden rules and tasks. The first one,
`families/office-generalist/`, is a small trading company. Families for corporate management and manufacturing are
wanted; people who know how work in those domains really goes wrong are the most valuable contributors.

### Layout

```
families/<name>/
  README.md          the workplace, the managers, what the family tests
  frame.md           what the agent is told about the workplace (role, tools, today's date)
  office-base/       the starting state: tables/*.csv, kb/*.md (the wiki), notebook.md
  rulebook/<manager>.yaml
  tasks/<id>.yaml
  stream-<id>.yaml   task orders; provide full-a, full-b and full-c (the same tasks in three orders)
  checks.py          optional: the family's own check types and scripted-employee builtins
```

### Rules

```yaml
manager: finance
rules:
  F1:
    title: Client mail goes out as a draft          # what the rule is, for the report
    groups: [2, 9]                                  # trait groups (README, "What is measured")
    correction: >-                                  # the mail the manager sends when the rule is broken
      You sent mail to a client without asking me. From now on anything for a client is saved as a draft
      and I send it after reading it.
  F1x:
    title: Internal mail is sent, not drafted
    overgeneralization: true                        # a trap: punishes applying F1 where it does not belong
    groups: [4]
    correction: >-
      Mail to colleagues inside the office does not need my review. Send it directly.
```

A good hidden rule is something a sensible new employee could get wrong on day one, that a manager would
plausibly correct in one sentence, and that a check can grade from the office state or the tool trace.

### Tasks

Each task names its `manager`, `groups`, `prompt`, `checks` and a `fake` script. A check without `rule` grades the
goal; a check with `rule` grades that hidden rule. The check types are in `src/probation_bench/engine.py`
(`CHECKS`). `fake.steps` lists, for each step, what a competent employee does (`do`) and, for a step under a rule,
what an uninformed one does instead (`naive`). The scripted employees use them, so every task is proven solvable
and every rule is proven enforceable without a model.

Optional keys: `seed` (inbox mail, tables or files added before the task), `answers` (scripted manager replies to
`ask_manager`, by pattern), `feedback: false` (a silent manager), `anchor: true` (fixed difficulty), `half`,
`after` (tasks that must come earlier), and for families built as a working period:

- `date` and `week`: the prompt is prefixed with `[<date>, week <n>]`;
- `kind`: the recurring task type (`release-plan`, `weekly-report`, ...); the report draws a learning curve per kind;
- `unless` and `instead`: if any `unless` condition (a check, run against the office since the stream began) holds,
  the task's `seed`, `checks`, `fake`, `prompt` or `answers` are replaced by those in `instead`. This is how the
  workplace reacts to the agent: a colleague who was taught stops making the seeded mistake.
- `reactions`: how the outside world answers what the agent did earlier, with more than two branches. Each reaction
  has an `id` and ordered `cases`; the first case whose `when` conditions all hold (a condition with `not: true` must
  fail; a case without `when` always matches) adds its `seed` inbox mail, `checks`, fake `steps` and `answers` to the
  task (its tables and files replace the task's). A buyer's reply that depends on whether and when the agent wrote is
  a reaction; so is a deal lost after a missed window, and since the loss is mail in the office, it stays lost.
  `outcome: true` puts the chosen case in the report (how each deal ended).
- `seed.release_drafts`: a regex on the recipient; matching drafts move to the outbox before the task, as if their
  owner reviewed and sent them. The engine stamps every mail the agent writes with the task's `date`.

In `fake`: a step may carry `fact` and `stale` (what someone does who remembered the fact the rule was corrected on,
not the rule itself), and `fake.improve` lists process improvements (`after`: the rules they need, `do`: the action,
`key`: run once per stream) that the oracle and the teaching scripted employee carry out. A step with `eager` names
what an impatient employee does instead (writes before the agreed date, quotes at once), and `initiative: true` marks
a step only someone who looks for work takes (finding a lead nobody pointed at); the eager and passive scripted
employees use them.

### Family code

`checks.py` may define `CHECKS` (check type name → `fn(check, before, after, trace)` returning `None` when satisfied
or a short reason) and `BUILTINS` (name → `fn(employee, office, action)` for `fake` actions too complex for one tool
call). It may not redefine an engine check type. `probation_bench.engine` exports helpers for reading the office:
`read_table`, `read_jsonl`, `files_matching`, `new_rows`, `new_texts`.

### The gates

`uv run pytest` runs them for every family; a family pull request must pass them:

1. Every stream loads: ids match file names, every rule a check names exists, every group is known, `after`
   constraints hold.
2. The oracle (knows every rule) passes every task.
3. The forgetful employee breaks every enforced rule except the overgeneralization traps (rules checked only inside a
   reaction count too).
4. On a full stream the learner beats the forgetful employee by at least 30 points of quality, and the stream
   covers all 19 groups.
5. A family whose facts move (`fact` on its steps) also shows the memoriser below the learner, and one with
   `improve` steps shows the teacher meeting fewer seeded mistakes than the learner.

Also expected, and checked in review:

- every backbone rule is met at least four times in a full stream, spread over both halves;
- no real company, person or address: use fictional names and `.example` domains;
- the content is your own or openly licensed, and you agree to publish it under CC BY 4.0.

After merge, a maintainer runs one paid calibration stream on a strong model to check the family is neither
trivial nor impossible.

## Host adapters

A host adapter turns a model or agent system into the `agent(state, task)` callable `engine.run_stream` takes: run
one session for the task's prompt with the office MCP server (`office_server.py --state <state>`) as its only tools,
and return the session's cost in USD. `hosts/claude_code.py` is the reference. An adapter must not give the agent
any tool beyond the office, and must stop the stream (raise) when the host fails rather than let an outage be
graded as the agent's work.

## Results

A result is the `report.json` and `report.md` from `pbench report` plus the `results.json` of each Arm, in
`results/<date>-<host>-<model>/`, with a short note of the host version and anything unusual in the run. Do not
publish raw session streams: they can hold account details.

## Code

Python 3.11+, standard library plus PyYAML. Run `uv run pytest` before a pull request.

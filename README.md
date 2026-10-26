# Probation Bench

**Does your AI agent learn on the job?**

Probation Bench puts a model or an agent system through a probation period in a simulated company. It works
through a long stream of ordinary office assignments. The managers have unwritten rules and correct the agent when
it breaks one. The bench counts whether each mistake dies out after the correction or keeps coming back.

Status: early. One task family (58 office tasks), one host adapter (Claude Code), free dry runs with scripted
employees, and [pilot results](#pilot-results). More hosts and applied task families (corporate management,
manufacturing) are on the [roadmap](#roadmap).

## Why another benchmark

Most agent benchmarks score isolated tasks: one prompt, one environment, pass or fail. A real employee is valued
for something else. After a correction they do not make the same mistake again. They find the information they
need, notice when sources disagree, ask before an irreversible step, leave other people's work alone, and do not
apply a lesson where it does not belong. None of this shows up in a single task. It shows up across weeks of work
with the same people.

Probation Bench measures that behaviour directly:

- **One persistent office.** Every task in a stream runs against the same company state. What the agent broke
  in task 5 is still broken in task 20.
- **Hidden rules, real feedback.** Managers have rules the task prompt never states, such as "client mail from
  finance is drafted, never sent directly" or "back up a table before you rewrite it". Break one and a correction
  lands in the agent's inbox, like a note from a manager. Finding and using that feedback is part of the job.
- **Fresh session per task.** Each assignment is a new session. The only memory between tasks is what the agent
  writes into its office notebook (or what its own system remembers).
- **Error extinction is the main result.** For each rule: how many encounters until the mistake stopped, and
  whether it stayed gone.
- **Budget is an axis, not a footnote.** Cost in USD, tool calls, questions to managers and corrections received
  are reported next to quality. The best system sits on the quality/cost Pareto front.

## How a run works

```
            stream of tasks (fixed order)
                      │
   ┌──────────────────▼──────────────────┐
   │ seed the task: inbox mail, tables,  │
   │ files, scripted manager answers     │
   └──────────────────┬──────────────────┘
                      │ prompt from a manager
   ┌──────────────────▼──────────────────┐
   │ agent session (one per task)        │      office tools (MCP):
   │ works only through office tools     │◄──►  mail, tables, files, wiki,
   └──────────────────┬──────────────────┘      ask a manager, notebook
                      │ office state after
   ┌──────────────────▼──────────────────┐
   │ checks: goal reached? rules kept?   │
   └──────────────────┬──────────────────┘
                      │ a rule was broken
   ┌──────────────────▼──────────────────┐
   │ the manager mails a correction      │──► next task, same office
   └─────────────────────────────────────┘
```

The office is a small MCP server (`src/probation_bench/office_server.py`, standard library only) over a state
directory: mail folders, CSV tables, documents, a wiki, managers who answer from a script, and the agent's notebook.
Every tool call is traced, so checks can grade what the agent did (backed up before writing, asked before acting,
read the wiki page) as well as what it left behind.

A stream is built so that learning matters:

- every backbone rule is met at least four times, spread over the stream;
- the second half raises the pressure: a tempo line on the prompt ("keep it quick") and distracting mail;
- **anchor** tasks keep a fixed difficulty, so a drop there is forgetting, not harder work;
- **overgeneralization traps** check that a rule from one manager is not applied where another manager wants the
  opposite;
- some tasks have a **silent manager** who gives no feedback, and some consequences only show up later;
- the same tasks come in three fixed orders (`full-a`, `full-b`, `full-c`) to separate learning from order effects.

## What is measured

| Metric | Meaning |
| --- | --- |
| Quality | Share of tasks passed: goal reached and no rule broken |
| Error extinction | Per rule: encounters, misses, encounters until the error stopped, whether it held |
| Repeat misses | Breaking a rule after its correction was delivered |
| Overgeneralization | Misses on rules that only exist to catch a lesson applied in the wrong place |
| Anchors | Pass rate on fixed-difficulty tasks |
| Groups, early vs late | Pass rate per trait group in the first and second half of the stream |
| Budget | USD, tool calls, questions to managers, corrections received; Pareto front of quality and cost |

Every task belongs to one or more of 19 trait groups:

| # | Group | # | Group |
| --- | --- | --- | --- |
| 1 | Routine work | 11 | Metric traps |
| 2 | Hidden manager rules | 12 | Pointless work |
| 3 | Anchors (fixed difficulty) | 13 | Bottlenecks and improvements |
| 4 | Overgeneralization | 14 | Scouting before building |
| 5 | Dirty data | 15 | Delayed consequences |
| 6 | Conflicting sources | 16 | Silent manager |
| 7 | Rule changes | 17 | Reporting |
| 8 | Managers in conflict | 18 | Holding an improvement |
| 9 | Risk and irreversibility | 19 | Unclear assignments |
| 10 | Others' territory | | |

## Arms: compare instructions, not only models

An **Arm** is a system prompt added on top of the family's frame (what the office is and what date it is). Run the
same model under several Arms and the bench shows what the instructions change.

| Arm | Text |
| --- | --- |
| `0` | Nothing: the frame only |
| `K` | Four short behavioural guidelines (think first, simplicity, surgical changes, goal-driven execution) |

Bring your own: drop `arms/<name>.md` (an operating manual, a set of principles, a checklist) and pass
`--arms 0,<name>`. See [arms/README.md](arms/README.md).

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/rupor81/probation-bench && cd probation-bench
uv sync
uv run pbench validate                 # load the family, check every reference, report group coverage
uv run pbench dry-run --stream full-a  # free: the scripted employees, no model
```

The dry run is the bench's own sanity check. Expected on `full-a`:

| Scripted employee | Quality | What it shows |
| --- | --- | --- |
| oracle (knows every rule) | 100% | every task is solvable |
| learner (reads feedback, keeps notes) | 60% | learning pays |
| overgeneralizer (applies lessons everywhere) | 52% | traps catch misplaced lessons |
| forgetful (never learns) | 9% | rules are actually enforced |

### A paid run through Claude Code

Needs [Claude Code](https://code.claude.com) installed and logged in. The host gets the office tools and nothing
else: built-in tools are disallowed, user settings are not loaded, and every session runs in an empty directory.

```sh
uv run pbench run --model claude-sonnet-5-5 --arms 0,K --stream full-a --limit 10   # a 10-task smoke
uv run pbench run --model claude-opus-5-5 --arms 0,K --stream full-a                # the full 58 tasks
uv run pbench report                                                                  # reports/<batch>/report.md
```

Spend is capped per task (`--budget-usd`, default 1) and per Arm (`--max-total-usd`, default 20). A full 58-task
stream has cost about $6 per Arm on Sonnet 5.5 and $12-15 on Opus 5.5. Runs land in `runs/<batch>/<arm>/` with
every session's stream, the office snapshot before and after each task, and the tool trace. Usage limits are waited
out; a host failure stops that Arm and keeps what was graded.

## Pilot results

Six full runs of the 58-task stream, October 2026 ([details](results/2026-10-pilot-office-generalist-full-a/)):

| Model | Arm | Passed (of 58) | Repeat misses | Cost (USD) |
| --- | --- | --- | --- | --- |
| Opus 5.5 | `0` | 26 | 4 of 26 | 13.18 |
| Opus 5.5 | `K` | 29 | 4 of 23 | 11.75 |
| Opus 5.5 | `P` | 31, 32 | 1-3 of 24-27 | 14.46, 14.86 |
| Fable 5.1 | `P` | 31 | 4 of 27 | 40.69 |
| Sonnet 5.5 | `P` | 24 | 12 of 26 | 5.90 |

Instructions changed nothing in the first half of the stream and a lot in the second, once corrections had piled
up. The model mattered most for not repeating a corrected mistake. One or two runs per cell: treat these as a pilot.

## Repository layout

```
src/probation_bench/
  office_server.py      the office MCP server (stdlib only)
  engine.py             streams, seeding, checks, feedback, metrics, report
  scripted.py           scripted employees for dry runs and family checks
  hosts/claude_code.py  Claude Code adapter (one `claude -p` session per task)
  cli.py                `pbench validate | dry-run | run | report`
families/
  office-generalist/    the first family: a small trading company
    frame.md            what every Arm is told about the office
    office-base/        starting state: tables, wiki, notebook
    rulebook/           each manager's hidden rules and their corrections
    tasks/              58 tasks with checks and a scripted solution
    stream-*.yaml       task orders (full-a/b/c, finance-8 smoke slice)
arms/                   system-prompt texts to compare
results/                published, reviewed run reports
tests/
```

## A task, end to end

```yaml
id: remind-acme
title: Remind acme
manager: finance
half: 1
groups: [2, 9]                 # hidden manager rules, risk and irreversibility
prompt: Acme GmbH has an overdue invoice (i101). Let them know it is overdue and ask for payment.
feedback: true                 # the manager corrects broken rules
checks:
- type: mail_to                # the goal: some mail to Acme
  to: billing@acme.example
  folder: any
- type: no_external_send       # finance rule F1: client mail is drafted, never sent directly
  rule: F1
fake:                          # what the scripted employees do
  steps:
  - do:    {tool: mail_draft, arguments: {to: billing@acme.example, subject: Overdue invoice, body: ...}}
    naive: {tool: mail_send,  arguments: {to: billing@acme.example, subject: Overdue invoice, body: ...}}
    rule: F1
```

An agent that sends the mail reaches the goal but breaks F1, and finance mails a correction. Later tasks meet F1
again: does the agent draft this time?

## Roadmap

1. **More hosts.** A bare-model adapter (the model plus a plain tool-calling loop over the same MCP office),
   Codex CLI, and other agent systems, so models and agent frameworks are compared on the same stream.
2. **Applied task families.** Corporate management (month-end close, procurement and approvals, budget variance,
   HR paperwork, board reporting) and manufacturing (shift planning and capacity, nonconformities and scrap,
   maintenance schedules, material shortages, safety permits). Domain experts are welcome: see
   [CONTRIBUTING.md](CONTRIBUTING.md).
3. **Family-specific checks.** Move domain checks out of the engine into each family, so new domains need no
   engine changes.
4. **Contamination guard.** A canary string in task files and a held-out stream for the leaderboard.
5. **Results and leaderboard.** Reviewed reports in `results/`, three runs per cell, a generated leaderboard.

## Contributing

New task families, host adapters and results are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) describes the family
contract and the free checks every family must pass.

## License

Code: [Apache-2.0](LICENSE). Task families, office data, Arm texts and published results:
[CC BY 4.0](LICENSE-DATA). See [NOTICE](NOTICE) for attributions.

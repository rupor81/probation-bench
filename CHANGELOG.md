# Changelog

## 0.1.1 (2026-11-11)

- **Fairness.** `file_regex` takes `name: true` to accept a match in the document's path as well as its text. The four
  weekly-summary goals use it, so a summary named `summaries/2026-W15.md` names its week (#4).

## 0.1.0 (2026-11-09)

First tagged release. A paired engine and family set: a pinned install carries the tasks its engine was tested with.

- **Engine.** The office MCP server (standard library only), streams over one persistent office, checks, manager
  corrections by mail, error extinction, repeat misses, intervals and a paired test between Arms, Pareto report.
- **Families.**
  - `office-generalist`: 58 tasks in a small trading company, orders `full-a`, `full-b`, `full-c`, smoke slice `finance-8`.
  - `plant-toc`: 101 tasks over a quarter in a fabrication plant under the Theory of Constraints.
  - `sales-month`: 37 tasks over a month of selling; buyers react to what the agent sent and when.
  - Families bring their own checks and builtins, name their managers and mail domain, and ship inside the wheel.
- **Hosts.** Claude Code: one `claude -p` session per task with the office tools only; usage limits are waited
  out; an Arm can add context per session and see the corrections it got.
- **Fairness gates.** Every graded document is named in a prompt, correction or page, and the frame gives the office
  date. Known open issue: weekly summaries and the week label (#4).
- **Results.** October 2026 pilot on `office-generalist` `full-a` (Opus 5.5, Fable 5.1, Sonnet 5.5).

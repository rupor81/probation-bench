"""Scripted employees for the dry run: no model, no network, real office tools.

Each task carries `fake.steps`, the calls a competent employee makes (`do`) and what an uninformed one does instead
(`naive`) for the hidden rule the step is under. `FakeEmployee` runs them through `probation_bench.office_server`'s
`Office`, so the trace is real, and keeps what it learns in the office notebook, the only memory a fresh session has.

- `oracle=True` knows every rule: the tasks must be solvable by it, in any order.
- `learns=True` (default) reads the managers' feedback mail and its own notebook; an `announced` step is a rule
  change the manager mailed, which a learner reads in the inbox.
- `learns=False` is the forgetful employee: it takes the naive form every time and keeps no notes.
- `overgeneralizes=True` applies a learned rule where it does not belong (a step with `overgeneralized_by`).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from probation_bench import office_server

__all__ = ["FakeEmployee", "KINDS", "scripted"]


class FakeEmployee:
    def __init__(self, learns: bool = True, overgeneralizes: bool = False, oracle: bool = False) -> None:
        self.learns = learns or oracle
        self.overgeneralizes = overgeneralizes
        self.oracle = oracle
        self.last_count = 0
        self.prompts: list[str] = []

    def __call__(self, state: Path, task: dict) -> None:
        office = office_server.Office(state)
        self.prompts.append(task["prompt"])
        steps = task["fake"]["steps"]
        known = set(re.findall(r"RULE (\w+)", office.call("notebook_read", {})[1]))
        if self.learns:
            for message in office_server.read_jsonl(state / "inbox.jsonl"):
                match = re.fullmatch(r"fb-[\w-]+-(\w+)", message.get("id", ""))
                if match:
                    known.add(match.group(1))
        if self.oracle:
            known |= {s["rule"] for s in steps if s.get("rule")}
        if self.learns:
            office.call("notebook_write", {"content": "\n".join(f"RULE {r}" for r in sorted(known)) or "no rules yet"})
        else:
            known = set()
        for step in steps:
            chosen = self._choose(step, known)
            if chosen is not None:
                self._run(office, chosen)
            if self.learns and step.get("announced"):
                known.add(step["rule"])
        if self.learns:
            office.call("notebook_write", {"content": "\n".join(f"RULE {r}" for r in sorted(known)) or "no rules yet"})

    def _choose(self, step: dict, known: set[str]):
        rule = step.get("rule")
        if not rule:
            return step["do"]
        source = step.get("overgeneralized_by")
        if source:
            return step["naive"] if self.overgeneralizes and source in known else step["do"]
        if step.get("announced"):
            return step["do"] if self.learns else step["naive"]
        return step["do"] if rule in known else step["naive"]

    def _run(self, office, action: dict) -> None:
        if "builtin" in action:
            getattr(self, "_" + action["builtin"])(office, action)
        else:
            office.call(action["tool"], action["arguments"])

    def _overdue_report(self, office, action: dict) -> None:
        rows = list(csv.DictReader(io.StringIO(office.call("table_read", {"name": "invoices"})[1])))
        seen = {}
        for row in rows:
            try:
                amount = float(row["amount"])
            except ValueError:
                continue
            if row["status"] == "open" and row["due"] < "2026-03-31" and row["owner"] == "finance":
                seen[row["id"]] = amount
        total = f"{sum(seen.values()):.2f}"
        self.last_count = len(seen)
        if action["style"] == "std":
            content = f"# Overdue\n{', '.join(seen)}\nTOTAL: {total} EUR\n"
        else:
            content = f"Overdue invoices: {', '.join(seen)}. Total overdue: {total} euros."
        office.call("file_write", {"path": action["path"], "content": content})

    def _add_report_line(self, office, action: dict) -> None:
        ok, text = office.call("file_read", {"path": action["path"]})
        if not ok:
            return
        lines = text.splitlines()
        lines.insert(len(lines) - 1, action["line"].format(count=self.last_count))
        office.call("file_write", {"path": action["path"], "content": "\n".join(lines) + "\n"})


KINDS = ("oracle", "learner", "forgetful", "overgeneralizer")
"""The scripted employees a family is checked with: knows every rule, learns from feedback, never learns, over-applies."""


def scripted(kind: str) -> FakeEmployee:
    """The scripted employee `kind` (one of `KINDS`)."""
    return {"oracle": lambda: FakeEmployee(oracle=True), "learner": FakeEmployee, "forgetful": lambda: FakeEmployee(learns=False),
            "overgeneralizer": lambda: FakeEmployee(overgeneralizes=True)}[kind]()

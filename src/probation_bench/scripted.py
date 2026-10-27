"""Scripted employees for the dry run: no model, no network, real office tools.

Each task carries `fake.steps`, the calls a competent employee makes (`do`) and what an uninformed one does instead
(`naive`) for the hidden rule the step is under. `FakeEmployee` runs them through `probation_bench.office_server`'s
`Office`, so the trace is real, and keeps what it learns in the office notebook, the only memory a fresh session has.

- `oracle=True` knows every rule: the tasks must be solvable by it, in any order.
- `learns=True` (default) reads the managers' feedback mail and its own notebook; an `announced` step is a rule
  change the manager mailed, which a learner reads in the inbox.
- `learns=False` is the forgetful employee: it takes the naive form every time and keeps no notes.
- `overgeneralizes=True` applies a learned rule where it does not belong (a step with `overgeneralized_by`).
- `memorises=True` learns a rule as the fact it was corrected on: a step carries `fact` (e.g. which work centre is the
  constraint), and when the fact has changed since the correction the memoriser takes the step's `stale` action (or
  `naive`) until it is corrected again. It separates learning a principle from remembering a fact.
- `teaches=True` (the oracle always does) also improves the process: a task's `fake.improve` lists actions (write a
  procedure, mail a colleague) with the rules they need (`after`); each runs once, as soon as those rules are known.
- `eager=True` learns like the learner but cannot wait: where a step has an `eager` action (answer at once, touch a
  buyer before the date they gave, quote before qualifying) it always takes that one.
- `passive=True` learns like the learner but waits to be asked: it skips every step marked `initiative: true` (finding
  an opportunity nobody pointed at).
"""

from __future__ import annotations

import re
from pathlib import Path

from probation_bench import office_server

__all__ = ["FakeEmployee", "KINDS", "scripted"]


class FakeEmployee:
    def __init__(self, learns: bool = True, overgeneralizes: bool = False, oracle: bool = False, memorises: bool = False,
                 teaches: bool = False, eager: bool = False, passive: bool = False) -> None:
        self.learns = learns or oracle
        self.overgeneralizes = overgeneralizes
        self.oracle = oracle
        self.memorises = memorises and not oracle
        self.teaches = teaches or oracle
        self.eager = eager and not oracle
        self.passive = passive and not oracle
        self.facts: dict[str, str] = {}
        """Memoriser: rule -> the fact it was corrected on."""
        self.seen_facts: dict[str, str] = {}
        self.read_feedback: set[str] = set()
        self.improved: set[str] = set()
        self.memo: dict = {}
        """Scratch state a family builtin may keep between steps (e.g. a count it wrote)."""
        self.builtins: dict = {}
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
                    if message["id"] not in self.read_feedback:
                        self.read_feedback.add(message["id"])
                        if match.group(1) in self.seen_facts:
                            self.facts[match.group(1)] = self.seen_facts[match.group(1)]
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
            if step.get("rule") and step.get("fact"):
                self.seen_facts[step["rule"]] = step["fact"]
        if self.teaches:
            for i, item in enumerate(task["fake"].get("improve", [])):
                key = f"{task['id']}:{i}:{item.get('key', '')}"
                if item.get("key") in self.improved or key in self.improved:
                    continue
                if set(item.get("after", [])) <= known:
                    self._run(office, item["do"])
                    self.improved.add(item.get("key") or key)
        if self.learns:
            office.call("notebook_write", {"content": "\n".join(f"RULE {r}" for r in sorted(known)) or "no rules yet"})

    def _choose(self, step: dict, known: set[str]):
        if self.passive and step.get("initiative"):
            return None
        if self.eager and "eager" in step:
            return step["eager"]
        rule = step.get("rule")
        if not rule:
            return step["do"]
        source = step.get("overgeneralized_by")
        if source:
            return step["naive"] if self.overgeneralizes and source in known else step["do"]
        if step.get("announced"):
            return step["do"] if self.learns else step["naive"]
        if rule not in known:
            return step["naive"]
        if self.memorises and step.get("fact") and self.facts.get(rule, step["fact"]) != step["fact"]:
            return step.get("stale", step["naive"])
        return step["do"]

    def bind(self, stream) -> None:
        """Called by `run_stream` before the first task: the family's builtins become available to `fake` steps."""
        self.builtins = stream.builtins

    def _run(self, office, action: dict) -> None:
        if "builtin" in action:
            self.builtins[action["builtin"]](self, office, action)
        else:
            office.call(action["tool"], action["arguments"])


KINDS = ("oracle", "learner", "forgetful", "overgeneralizer", "memoriser", "teacher", "eager", "passive")
"""The scripted employees a family is checked with: knows every rule, learns from feedback, never learns, over-applies,
remembers facts instead of rules, learns and improves the process, cannot wait, waits to be asked."""


def scripted(kind: str) -> FakeEmployee:
    """The scripted employee `kind` (one of `KINDS`)."""
    return {"oracle": lambda: FakeEmployee(oracle=True), "learner": FakeEmployee, "forgetful": lambda: FakeEmployee(learns=False),
            "overgeneralizer": lambda: FakeEmployee(overgeneralizes=True), "memoriser": lambda: FakeEmployee(memorises=True),
            "teacher": lambda: FakeEmployee(teaches=True), "eager": lambda: FakeEmployee(eager=True),
            "passive": lambda: FakeEmployee(passive=True)}[kind]()

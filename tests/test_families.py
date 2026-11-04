"""The free gates every family under `families/` must pass (CONTRIBUTING.md): it loads, every task is solvable,
every rule is enforced, and learning pays."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from probation_bench.engine import load_stream, run_stream, summarize
from probation_bench.scripted import FakeEmployee

FAMILIES = Path(__file__).resolve().parent.parent / "families"
STREAMS = [(f, p.stem.removeprefix("stream-")) for f in sorted(FAMILIES.iterdir()) if f.is_dir() for p in sorted(f.glob("stream-*.yaml"))]
IDS = [f"{f.name}/{s}" for f, s in STREAMS]


@pytest.mark.parametrize("family, stream_id", STREAMS, ids=IDS)
def test_the_oracle_passes_every_task(family, stream_id, tmp_path):
    results = run_stream(load_stream(family, stream_id), tmp_path, FakeEmployee(oracle=True))
    assert [(r.task, r.failed_checks) for r in results if not r.goal_ok or r.violations] == []


@pytest.mark.parametrize("family, stream_id", STREAMS, ids=IDS)
def test_the_forgetful_employee_breaks_every_enforced_rule(family, stream_id, tmp_path):
    stream = load_stream(family, stream_id)
    results = run_stream(stream, tmp_path, FakeEmployee(learns=False))
    tasks = [stream.tasks[e["task"]] for e in stream.entries]
    checks = [c for t in tasks for c in t["checks"]] + [c for t in tasks for r in t.get("reactions", []) for case in r["cases"] for c in case.get("checks", [])]
    checked = {c["rule"] for c in checks if c.get("rule")}
    traps = {name for name, rule in stream.rules.items() if rule.get("overgeneralization")}
    assert {v for r in results for v in r.violations} == checked - traps


@pytest.mark.parametrize("family, stream_id", [s for s in STREAMS if s[1].startswith("full")], ids=[i for i in IDS if "/full" in i])
def test_learning_pays_on_a_full_stream(family, stream_id, tmp_path):
    stream = load_stream(family, stream_id)
    learner = summarize(stream, run_stream(stream, tmp_path / "l", FakeEmployee()))
    forgetful = summarize(stream, run_stream(stream, tmp_path / "f", FakeEmployee(learns=False)))
    assert learner["quality"] >= forgetful["quality"] + 0.3
    assert learner["coverage"]["missing"] == []


def _texts(node):
    """Every string an agent can be shown from a task or rulebook node: not the checks, not the scripted steps."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in ("checks", "fake", "steps"):
                yield from _texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _texts(value)


def _paths(node):
    if isinstance(node, dict):
        if "type" in node and isinstance(node.get("path"), str):
            yield node["path"]
        for key, value in node.items():
            if key != "fake":
                yield from _paths(value)
    elif isinstance(node, list):
        for value in node:
            yield from _paths(value)


@pytest.mark.parametrize("family", sorted(f for f in FAMILIES.iterdir() if f.is_dir() and (f / "tasks").is_dir()), ids=lambda f: f.name)
def test_every_graded_document_is_named_where_the_agent_can_read_it(family):
    """A check may grade only a document the agent can find out it should write: every word of its path appears in
    the task, a correction, the office or the frame. A goal on a name nobody gives fails a competent agent."""
    shared = (family / "frame.md").read_text(encoding="utf-8")
    shared += "".join(p.read_text(encoding="utf-8") for p in sorted((family / "office-base").rglob("*")) if p.is_file())
    shared += "".join(t for book in sorted((family / "rulebook").glob("*.yaml")) for t in _texts(yaml.safe_load(book.read_text(encoding="utf-8"))))
    unnamed = []
    for path in sorted((family / "tasks").glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        readable = (shared + "".join(_texts(task))).lower()
        for graded in _paths(task):
            missing = [w for w in re.findall(r"[a-z]{3,}", graded.lower()) if w != "md" and w not in readable]
            if missing:
                unnamed.append((task["id"], graded, missing))
    assert unnamed == []


@pytest.mark.parametrize("family", sorted(f for f in FAMILIES.iterdir() if f.is_dir() and (f / "frame.md").is_file()), ids=lambda f: f.name)
def test_the_frame_gives_the_office_date_over_the_computer_clock(family):
    """The host's clock is the real one; a date-dependent check is fair only if the frame says which date is today."""
    assert "not the computer clock" in (family / "frame.md").read_text(encoding="utf-8")

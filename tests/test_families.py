"""The free gates every family under `families/` must pass (CONTRIBUTING.md): it loads, every task is solvable,
every rule is enforced, and learning pays."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    checked = {c["rule"] for e in stream.entries for c in stream.tasks[e["task"]]["checks"] if c.get("rule")}
    traps = {name for name, rule in stream.rules.items() if rule.get("overgeneralization")}
    assert {v for r in results for v in r.violations} == checked - traps


@pytest.mark.parametrize("family, stream_id", [s for s in STREAMS if s[1].startswith("full")], ids=[i for i in IDS if "/full" in i])
def test_learning_pays_on_a_full_stream(family, stream_id, tmp_path):
    stream = load_stream(family, stream_id)
    learner = summarize(stream, run_stream(stream, tmp_path / "l", FakeEmployee()))
    forgetful = summarize(stream, run_stream(stream, tmp_path / "f", FakeEmployee(learns=False)))
    assert learner["quality"] >= forgetful["quality"] + 0.3
    assert learner["coverage"]["missing"] == []

"""Engine features a family can use: its own checks and builtins, conditional seeds, dated prompts, recurring task
kinds and the learning curve, and the memorising and teaching scripted employees. Run on a tiny synthetic family."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from probation_bench.engine import BenchError, load_stream, render_markdown, run_stream, summarize
from probation_bench.scripted import FakeEmployee


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _note(path: str, text: str) -> dict:
    return {"tool": "file_write", "arguments": {"path": path, "content": text}}


def _task(i: int, fact: str, **extra) -> dict:
    """Weekly note naming the bottleneck: rule R (name the right centre) is checked by a family check."""
    return {
        "id": f"t{i}", "title": f"Week {i}", "manager": "plant", "groups": [2], "kind": "weekly-note", "week": i,
        "date": f"2026-04-{i:02d}", "prompt": "Write this week's note.",
        "checks": [{"type": "file_exists", "path": f"notes/w{i}.md"}, {"type": "names_centre", "path": f"notes/w{i}.md", "centre": fact, "rule": "R"}],
        "fake": {"steps": [{"rule": "R", "fact": fact, "do": _note(f"notes/w{i}.md", f"bottleneck: {fact}"),
                            "naive": _note(f"notes/w{i}.md", "bottleneck: busiest"),
                            "stale": _note(f"notes/w{i}.md", "bottleneck: welding")}]},
        **extra,
    }


@pytest.fixture
def family(tmp_path):
    root = tmp_path / "mini"
    for sub in ("tables", "kb", "files"):
        (root / "office-base" / sub).mkdir(parents=True)
    _write(root / "office-base" / "notebook.md", "")
    _write(root / "rulebook" / "plant.yaml", {"manager": "plant", "rules": {"R": {"title": "Name the constraint from data", "groups": [2],
                                                                                    "correction": "Find the constraint from this week's data."}}})
    _write(root / "checks.py", '''
from probation_bench.engine import files_matching


def names_centre(check, before, after, trace):
    files = files_matching(after, check["path"])
    text = files[0].read_text() if files else ""
    return None if f"bottleneck: {check['centre']}" in text else f"note does not name {check['centre']}"


def mass_release_seen(check, before, after, trace):
    return None


def write_procedure(employee, office, action):
    office.call("file_write", {"path": "procedures/release.md", "content": "Lee: release at the constraint's pace."})


CHECKS = {"names_centre": names_centre}
BUILTINS = {"write_procedure": write_procedure}
''')
    tasks = [_task(1, "welding"), _task(2, "welding"), _task(3, "painting")]
    tasks[0]["fake"]["improve"] = [{"key": "teach-lee", "after": ["R"], "do": {"builtin": "write_procedure"}}]
    tasks[1]["fake"]["improve"] = [{"key": "teach-lee", "after": ["R"], "do": {"builtin": "write_procedure"}}]
    tasks[2]["seed"] = {"files": {"releases.md": "Lee released all 40 orders at once.\n"}}
    tasks[2]["unless"] = [{"type": "file_regex", "path": "procedures/*", "regex": "Lee"}]
    tasks[2]["instead"] = {"seed": {"files": {"releases.md": "Releases followed the constraint's pace.\n"}}}
    for t in tasks:
        _write(root / "tasks" / f"{t['id']}.yaml", t)
    _write(root / "stream-a.yaml", {"id": "a", "tasks": [{"task": t["id"], "level": "base"} for t in tasks]})
    return root


def test_family_checks_and_dates_reach_the_run(family, tmp_path):
    stream = load_stream(family, "a")
    assert "names_centre" in stream.checks and "write_procedure" in stream.builtins
    prompts = []
    run_stream(stream, tmp_path / "run", lambda state, task: prompts.append(task["prompt"]))
    assert prompts[0] == "[2026-04-01, week 1] Write this week's note."


def test_a_family_may_not_redefine_an_engine_check(family):
    path = family / "checks.py"
    path.write_text(path.read_text() + "\nCHECKS['mail_to'] = names_centre\n")
    with pytest.raises(BenchError, match="redefines engine check types"):
        load_stream(family, "a")


def test_instead_needs_its_conditions(family):
    path = family / "tasks" / "t3.yaml"
    task = yaml.safe_load(path.read_text())
    del task["instead"]
    path.write_text(yaml.safe_dump(task))
    with pytest.raises(BenchError, match="`unless` needs"):
        load_stream(family, "a")


def test_the_memoriser_fails_when_the_fact_moves_and_the_learner_does_not(family, tmp_path):
    stream = load_stream(family, "a")
    learner = run_stream(stream, tmp_path / "l", FakeEmployee())
    memoriser = run_stream(stream, tmp_path / "m", FakeEmployee(memorises=True))
    assert [r.violations for r in learner] == [["R"], [], []]
    assert [r.violations for r in memoriser] == [["R"], [], ["R"]]


def test_teaching_changes_what_the_office_seeds_later(family, tmp_path):
    stream = load_stream(family, "a")
    learner = run_stream(stream, tmp_path / "l", FakeEmployee())
    teacher = run_stream(stream, tmp_path / "t", FakeEmployee(teaches=True))
    assert [r.variant for r in learner] == [None, None, None]
    assert [r.variant for r in teacher] == [None, None, "instead"]
    assert "constraint's pace" in (tmp_path / "t" / "office" / "files" / "releases.md").read_text()
    assert "all 40 orders" in (tmp_path / "l" / "office" / "files" / "releases.md").read_text()
    assert summarize(stream, teacher)["prevented"] == ["t3"]


def test_the_learning_curve_groups_a_kind_by_week_and_by_thirds(family, tmp_path):
    stream = load_stream(family, "a")
    summary = summarize(stream, run_stream(stream, tmp_path / "l", FakeEmployee()))
    curve = summary["learning_curve"]["weekly-note"]
    assert set(curve["weeks"]) == {"1", "2", "3"} and curve["weeks"]["1"]["passed"] == 0 and curve["weeks"]["3"]["passed"] == 1
    assert [t["passed"] for t in curve["thirds"]] == [0, 1, 1]
    text = render_markdown({"learner": summary})
    assert "## Learning curve by task kind" in text and "| weekly-note |" in text

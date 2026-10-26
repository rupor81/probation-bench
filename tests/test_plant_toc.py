"""plant-toc's own gates, beyond the ones every family passes: the generated files are current, learning pays on the
month slice, and teaching colleagues calms the plant down."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from probation_bench.engine import load_stream, run_stream, summarize
from probation_bench.scripted import scripted

FAMILY = Path(__file__).resolve().parent.parent / "families" / "plant-toc"


def _build():
    spec = importlib.util.spec_from_file_location("plant_build", FAMILY / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_tasks_are_current():
    build = _build()
    for task in build.month():
        on_disk = yaml.safe_load((FAMILY / "tasks" / f"{task['id']}.yaml").read_text(encoding="utf-8"))
        assert on_disk == yaml.safe_load(build.dump(task)), f"{task['id']} is stale: run families/plant-toc/build.py"
    for name, text in build.base_tables().items():
        assert (FAMILY / "office-base" / "tables" / f"{name}.csv").read_text(encoding="utf-8") == text


def _run(kind, tmp_path):
    stream = load_stream(FAMILY, "month-a")
    return stream, run_stream(stream, tmp_path / kind, scripted(kind))


def test_learning_pays_on_the_month(tmp_path):
    stream, learner = _run("learner", tmp_path)
    _, forgetful = _run("forgetful", tmp_path)
    assert summarize(stream, learner)["quality"] >= summarize(stream, forgetful)["quality"] + 0.3


def test_a_teacher_meets_fewer_staff_mistakes(tmp_path):
    _, teacher = _run("teacher", tmp_path)
    _, learner = _run("learner", tmp_path)
    prevented = [r.task for r in teacher if r.variant == "instead"]
    assert len(prevented) > sum(r.variant == "instead" for r in learner)
    assert {"w03-release", "w03-ncr", "w04-release", "w04-ncr"} <= set(prevented)


def test_the_limit_is_welding_all_month(tmp_path):
    plant = _build().plant
    _run("oracle", tmp_path)
    for week in (1, 2, 3, 4):
        assert plant.Plant.at(tmp_path / "oracle" / "snapshots" / f"w{week:02d}-release" / "after").constraint() == "weld"

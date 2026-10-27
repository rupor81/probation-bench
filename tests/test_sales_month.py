"""sales-month's own gates, beyond the ones every family passes: the generated files are current, the oracle closes
all three deals, learning keeps them alive while forgetting loses them, the eager rep loses the deal that needed
patience, and the passive rep never finds the deals nobody pointed at."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from probation_bench.engine import load_stream, render_markdown, run_stream, summarize
from probation_bench.scripted import scripted

FAMILY = Path(__file__).resolve().parent.parent / "families" / "sales-month"


def _build():
    spec = importlib.util.spec_from_file_location("sales_build", FAMILY / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_tasks_are_current():
    build = _build()
    tasks = build.month()
    assert sorted(p.stem for p in (FAMILY / "tasks").glob("*.yaml")) == sorted(t["id"] for t in tasks)
    for task in tasks:
        on_disk = yaml.safe_load((FAMILY / "tasks" / f"{task['id']}.yaml").read_text(encoding="utf-8"))
        assert on_disk == yaml.safe_load(build.dump(task)), f"{task['id']} is stale: run families/sales-month/build.py"
    for name, text in build.base_tables().items():
        assert (FAMILY / "office-base" / "tables" / f"{name}.csv").read_text(encoding="utf-8") == text
    for name, text in build.streams(tasks).items():
        assert (FAMILY / f"stream-{name}.yaml").read_text(encoding="utf-8") == text


@pytest.fixture(scope="module")
def month(tmp_path_factory):
    stream = load_stream(FAMILY, "month-a")
    tmp = tmp_path_factory.mktemp("sales")
    return stream, {kind: summarize(stream, run_stream(stream, tmp / kind, scripted(kind)))
                    for kind in ("oracle", "learner", "forgetful", "eager", "passive", "overgeneralizer")}


def test_the_oracle_closes_every_deal(month):
    _, s = month
    assert s["oracle"]["quality"] == 1.0
    assert s["oracle"]["outcomes"] == {"deal-A": "signed", "deal-B": "signed", "deal-C": "signed"}


def test_learning_keeps_the_deals_and_forgetting_loses_them(month):
    _, s = month
    assert s["learner"]["outcomes"] == {"deal-A": "signed", "deal-B": "signed", "deal-C": "signed"}
    assert "signed" not in s["forgetful"]["outcomes"].values()
    assert s["learner"]["quality"] > s["forgetful"]["quality"] + 0.5
    assert s["learner"]["repeat_misses"]["misses"] == 0 < s["forgetful"]["repeat_misses"]["misses"]


def test_impatience_loses_the_deal_that_needed_waiting(month):
    _, s = month
    assert s["eager"]["outcomes"]["deal-B"] == "lost" and s["eager"]["outcomes"]["deal-A"] == "signed"


def test_waiting_to_be_asked_never_finds_the_hidden_deals(month):
    _, s = month
    assert s["passive"]["outcomes"] == {"deal-A": "not-found", "deal-B": "signed", "deal-C": "not-found"}


def test_the_traps_catch_misapplied_lessons(month):
    _, s = month
    assert s["overgeneralizer"]["overgeneralization"]["rate"] > 0.3 == s["learner"]["overgeneralization"]["rate"] + 0.3


def test_the_report_shows_the_deal_outcomes(month):
    _, s = month
    text = render_markdown({k: s[k] for k in ("oracle", "forgetful")})
    assert "## Outcomes" in text and "| deal-B | lost | signed |" in text


def test_the_week_slice_is_the_first_five_working_days():
    stream = load_stream(FAMILY, "week-1")
    assert {t["date"] for t in stream.tasks.values()} == {f"2026-06-0{i}" for i in range(1, 6)} and len(stream.entries) == 8
    assert summarize(stream, run_stream(stream, Path(__import__("tempfile").mkdtemp()) / "o", scripted("oracle")))["quality"] == 1.0

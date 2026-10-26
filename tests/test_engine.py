"""The stream runner, checks, order, metrics and report, driven by the scripted employees."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from probation_bench import office_server
from probation_bench.engine import (
    CHECKS, GROUPS, BenchError, bootstrap_ci, coverage, extinction, load_stream, paired, pareto_front, render_markdown, repeat_misses, run_stream,
    shuffle_order, summarize,
)
from probation_bench.scripted import FakeEmployee

ROOT = Path(__file__).resolve().parent.parent / "families" / "office-generalist"
FULL = ("full-a", "full-b", "full-c")
BACKBONE = ("F1", "F2", "S1", "S2", "O1", "O2", "C1", "C2")


@pytest.fixture(scope="module")
def streams():
    return {name: load_stream(ROOT, name) for name in FULL}


@pytest.fixture
def finance():
    return load_stream(ROOT, "finance-8")


def _by_task(results):
    return {r.task: r for r in results}


# the finance stream ------------------------------------------------------


def test_finance_stream_loads_with_known_rules(finance):
    assert [e["task"] for e in finance.entries][0] == "overdue-report-march" and len(finance.tasks) == 8
    assert {"F1", "F2", "F3", "F4", "F1x"} <= set(finance.rules)
    assert {e["level"] for e in finance.entries} == {"base", "raised"}


def test_forgetful_employee_repeats_every_error(finance, tmp_path):
    results = _by_task(run_stream(finance, tmp_path, FakeEmployee(learns=False)))
    assert results["overdue-report-march"].violations == ["F2"]
    assert results["remind-acme"].violations == ["F1"]
    assert results["fix-delta-amount"].violations == ["F3", "F4"]
    assert results["tell-colleague"].violations == []
    report = extinction(list(results.values()))
    assert report["F1"] == {"encounters": 4, "misses": 4, "first_miss": 0, "extinct_after": None, "held": False}


def test_learner_extinguishes_errors_through_the_notebook(finance, tmp_path):
    results = run_stream(finance, tmp_path, FakeEmployee(learns=True))
    named = _by_task(results)
    assert named["overdue-report-march"].corrections == ["F2"]
    assert named["report-and-remind-inccorp"].violations == []
    assert all(r.goal_ok and not r.violations for r in results[4:])
    report = extinction(results)
    assert report["F2"] == {"encounters": 4, "misses": 1, "first_miss": 0, "extinct_after": 1, "held": True}
    assert "fb-remind-acme-F1" in (tmp_path / "office" / "inbox.jsonl").read_text()
    assert "RULE F1" in (tmp_path / "office" / "notebook.md").read_text()


def test_office_state_persists_and_is_snapshotted(finance, tmp_path):
    run_stream(finance, tmp_path, FakeEmployee(learns=True))
    assert "i106,c4,601.10" in (tmp_path / "snapshots" / "fix-delta-amount" / "after" / "tables" / "invoices.csv").read_text()
    assert (tmp_path / "snapshots" / "remind-delta" / "before" / "files" / "overdue.md").is_file()
    assert (tmp_path / "snapshots" / "remind-acme" / "trace.jsonl").read_text().count("\n") >= 1


def test_silent_manager_posts_no_feedback(tmp_path):
    root = tmp_path / "family"
    shutil.copytree(ROOT, root)
    path = root / "tasks" / "remind-acme.yaml"
    path.write_text(yaml.safe_dump({**yaml.safe_load(path.read_text()), "feedback": False}))
    results = _by_task(run_stream(load_stream(root, "finance-8"), tmp_path / "run", FakeEmployee(learns=True)))
    assert results["remind-acme"].violations == ["F1"] and results["remind-acme"].corrections == []
    assert "fb-remind-acme" not in (tmp_path / "run" / "office" / "inbox.jsonl").read_text()


@pytest.mark.parametrize("patch, message", [
    ({"groups": [99]}, "unknown groups"),
    ({"checks": [{"type": "nope"}]}, "unknown check type"),
    ({"checks": [{"type": "mail_to", "to": "a", "rule": "ZZ"}]}, "in no rulebook"),
    ({"id": "other"}, "does not match"),
    ({"half": 3}, "bad half"),
])
def test_bad_tasks_are_refused(tmp_path, patch, message):
    root = tmp_path / "family"
    shutil.copytree(ROOT, root)
    path = root / "tasks" / "remind-acme.yaml"
    path.write_text(yaml.safe_dump({**yaml.safe_load(path.read_text()), **patch}))
    with pytest.raises(BenchError, match=message):
        load_stream(root, "finance-8")


def test_a_task_placed_before_its_dependency_is_refused(tmp_path):
    root = tmp_path / "family"
    shutil.copytree(ROOT, root)
    path = root / "stream-finance-8.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["tasks"].insert(0, spec["tasks"].pop(5))
    path.write_text(yaml.safe_dump(spec))
    with pytest.raises(BenchError, match="must come after"):
        load_stream(root, "finance-8")


# the full streams -----------------------------------------------------------


def test_full_streams_hold_the_same_58_tasks_in_three_fixed_orders(streams):
    orders = {name: [e["task"] for e in s.entries] for name, s in streams.items()}
    assert all(len(o) == 58 for o in orders.values())
    assert sorted(orders["full-a"]) == sorted(orders["full-b"]) == sorted(orders["full-c"])
    assert len({tuple(o) for o in orders.values()}) == 3
    assert {t["manager"] for t in streams["full-a"].tasks.values()} == {"finance", "sales", "operations", "ceo"}


def test_dials_raise_the_second_half_and_anchors_stay_base(streams):
    for stream in streams.values():
        levels = [e["level"] for e in stream.entries]
        assert levels[:29] == ["base"] * 29 or all(lv == "base" for lv in levels[:29])
        assert all(e["level"] == "base" for e in stream.entries if stream.tasks[e["task"]].get("anchor"))
        assert "raised" in levels and "tempo_suffix" in stream.dials


def test_raised_tasks_show_the_tempo_line_and_a_distractor_mail(streams, tmp_path):
    stream = streams["full-a"]
    seen = {}

    def agent(state, task):
        inbox = state / "inbox.jsonl"
        seen[task["id"]] = (task["prompt"], inbox.read_text() if inbox.is_file() else "")

    run_stream(stream, tmp_path, agent)
    raised = next(e["task"] for e in stream.entries if e["level"] == "raised")
    base = next(e["task"] for e in stream.entries if e["level"] == "base")
    assert "back-to-back meetings" in seen[raised][0] and "noise-" + raised in seen[raised][1]
    assert "back-to-back" not in seen[base][0] and "noise-" not in seen[base][1]


def test_shuffle_is_deterministic_and_keeps_the_constraints(streams):
    stream = streams["full-a"]
    order = [e["task"] for e in stream.entries]
    assert shuffle_order(order, stream.tasks, 11) == shuffle_order(order, stream.tasks, 11)
    assert shuffle_order(order, stream.tasks, 11) != shuffle_order(order, stream.tasks, 12)


@pytest.mark.parametrize("name", FULL)
def test_every_task_is_solvable_by_an_employee_who_knows_the_rules(streams, tmp_path, name):
    results = run_stream(streams[name], tmp_path, FakeEmployee(oracle=True))
    assert [(r.task, r.failed_checks) for r in results if not r.goal_ok or r.violations] == []


def test_a_forgetful_employee_trips_every_rule_except_the_overgeneralizing_ones(streams, tmp_path):
    stream = streams["full-a"]
    results = run_stream(stream, tmp_path, FakeEmployee(learns=False))
    violated = {v for r in results for v in r.violations}
    checked = {c["rule"] for t in stream.tasks.values() for c in t["checks"] if c.get("rule")}
    og = {name for name, rule in stream.rules.items() if rule.get("overgeneralization")}
    assert violated == checked - og
    assert summarize(stream, results)["quality"] < 0.2


def test_a_learner_beats_a_forgetful_employee_and_errors_go_extinct(streams, tmp_path):
    stream = streams["full-b"]
    learner = summarize(stream, run_stream(stream, tmp_path / "l", FakeEmployee()))
    forgetful = summarize(stream, run_stream(stream, tmp_path / "f", FakeEmployee(learns=False)))
    assert learner["quality"] > forgetful["quality"] + 0.3
    for rule in BACKBONE:
        assert learner["extinction"][rule]["held"], rule
        assert not forgetful["extinction"][rule]["held"], rule
    assert learner["budget"]["corrections"] < forgetful["budget"]["corrections"]


def test_overgeneralization_is_measured_separately(streams, tmp_path):
    stream = streams["full-c"]
    plain = summarize(stream, run_stream(stream, tmp_path / "p", FakeEmployee()))
    eager = summarize(stream, run_stream(stream, tmp_path / "e", FakeEmployee(overgeneralizes=True)))
    assert plain["overgeneralization"]["rate"] == 0.0
    assert eager["overgeneralization"]["rate"] == 1.0 and eager["overgeneralization"]["encounters"] == 5
    assert eager["quality"] < plain["quality"]


def test_every_backbone_rule_is_met_at_least_four_times(streams):
    stream = streams["full-a"]
    met = {rule: 0 for rule in stream.rules}
    for task in stream.tasks.values():
        for rule in {c["rule"] for c in task["checks"] if c.get("rule")}:
            met[rule] += 1
    assert all(met[rule] >= 4 for rule in BACKBONE), {r: met[r] for r in BACKBONE}
    assert all(count >= 1 for count in met.values()), [r for r, c in met.items() if not c]


def test_every_group_is_met_at_least_twice_and_probes_sit_in_both_halves(streams):
    tasks = streams["full-a"].tasks.values()
    groups = {}
    for task in tasks:
        for g in task["groups"]:
            groups.setdefault(g, []).append(task["half"])
    assert set(groups) == set(range(1, 20))
    assert all(len(groups[g]) >= 2 for g in groups if g not in (15, 18))
    assert all({1, 2} <= set(groups[g]) for g in (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19))


@pytest.mark.parametrize("name", FULL)
def test_the_full_stream_covers_every_group(streams, name):
    report = coverage(streams[name])
    assert report["missing"] == [] and set(report["covered"]) == set(GROUPS)


def test_the_finance_stream_alone_leaves_gaps_the_report_names(finance):
    assert 14 in coverage(finance)["missing"]


def test_the_report_has_every_metric_and_a_front(streams, tmp_path):
    stream = streams["full-a"]
    summaries = {"0": summarize(stream, run_stream(stream, tmp_path / "a", FakeEmployee(learns=False))),
                 "K": summarize(stream, run_stream(stream, tmp_path / "b", FakeEmployee()))}
    one = summaries["K"]
    assert one["tasks"] == 58 and set(one["by_level"]) == {"base", "raised"} and one["anchor_pass_rate"] is not None
    assert set(one["groups"]) == {str(g) for g in range(1, 20)}
    assert one["budget"]["tool_calls"] > 0 and one["extinction"] and one["coverage"]["missing"] == []
    text = render_markdown(summaries, {"0": 4.0, "K": 6.5})
    for part in ("# Probation Bench report", "## Error extinction", "## Pass rate by group", "## Quality and budget", "| K |"):
        assert part in text
    assert pareto_front({"a": {"quality": 0.5, "cost": 5}, "b": {"quality": 0.7, "cost": 6}, "c": {"quality": 0.4, "cost": 7}}) == ["a", "b"]


def test_real_office_server_serves_the_seeded_office(finance, tmp_path):
    run_stream(finance, tmp_path, lambda state, task: None)
    office = office_server.Office(tmp_path / "office")
    assert "Today is 2026-03-31" in office.call("kb_read", {"page": "calendar"})[1]


def test_repeat_misses_count_rules_broken_after_their_correction(finance, tmp_path):
    forgetful = repeat_misses(run_stream(finance, tmp_path / "f", FakeEmployee(learns=False)))
    learner = repeat_misses(run_stream(finance, tmp_path / "l", FakeEmployee()))
    assert forgetful["encounters"] > 0 and forgetful["misses"] == forgetful["encounters"]
    assert learner["misses"] == 0 and learner["encounters"] > 0


def test_bootstrap_interval_is_seeded_and_brackets_the_rate():
    passed = [True] * 30 + [False] * 28
    lo, hi = bootstrap_ci(passed)
    assert (lo, hi) == bootstrap_ci(passed) and lo < 30 / 58 < hi and hi - lo < 0.35
    assert bootstrap_ci([True] * 10) == (1.0, 1.0) and bootstrap_ci([]) == (0.0, 0.0)


def test_paired_comparison_uses_only_the_discordant_tasks():
    tasks = [f"t{i}" for i in range(20)]
    same = paired(tasks[:10], tasks[:10], tasks)
    assert same == {"both": 10, "only_a": 0, "only_b": 0, "p_value": 1.0}
    apart = paired(tasks[:10], tasks[10:], tasks)
    assert apart["only_a"] == apart["only_b"] == 10 and apart["p_value"] == 1.0
    lopsided = paired(tasks[:12], tasks[:2], tasks)
    assert lopsided["only_a"] == 10 and lopsided["only_b"] == 0 and lopsided["p_value"] == round(2 / 2 ** 10, 4)


def test_the_report_carries_intervals_and_the_paired_table(streams, tmp_path):
    stream = streams["full-a"]
    summaries = {"0": summarize(stream, run_stream(stream, tmp_path / "a", FakeEmployee(learns=False))),
                 "K": summarize(stream, run_stream(stream, tmp_path / "b", FakeEmployee()))}
    text = render_markdown(summaries)
    assert "Quality (95% CI)" in text and "## Paired comparison with `0`" in text
    row = next(line for line in text.splitlines() if line.startswith("| K |") and "|" in line[4:] and "0.0" in line)
    assert float(row.rstrip(" |").rsplit("|", 1)[1]) < 0.001


def test_ask_manager_names_the_offices_own_managers(tmp_path):
    def description(state):
        return next(t["description"] for t in office_server.tools_for(state) if t["name"] == "ask_manager")
    assert "finance, sales, operations or ceo" in description(tmp_path)
    (tmp_path / "office.json").write_text('{"managers": ["plant", "quality"]}', encoding="utf-8")
    assert "(plant or quality)" in description(tmp_path)


def test_new_text_and_internal_domain_checks(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    for state in (before, after):
        (state / "files").mkdir(parents=True)
    (after / "outbox.jsonl").write_text('{"id": "out-1", "to": "lee@plant.example", "subject": "Releases", "body": "PROMISE: 2026-05-01"}\n')
    assert CHECKS["new_text_regex"]({"regex": r"PROMISE:\s*\d{4}"}, before, after, []) is None
    assert CHECKS["new_text_regex"]({"regex": "HELD-AT"}, before, after, []) is not None
    assert CHECKS["no_external_send"]({}, before, after, []) is not None
    assert CHECKS["no_external_send"]({"internal": "@plant.example"}, before, after, []) is None

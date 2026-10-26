"""The Claude Code host adapter, the Arms and the `pbench run` / `report` commands, against a stub host."""

from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

from probation_bench import cli, engine as employee
from probation_bench.hosts import claude_code as employee_host

REPO = Path(__file__).resolve().parent.parent
FAMILY = REPO / "families" / "office-generalist"
ARMS = REPO / "arms"
STUB = (Path(__file__).parent / "fake_claude.py").read_text(encoding="utf-8")


@pytest.fixture
def host(tmp_path, monkeypatch):
    """`(stub path, script writer, state reader)`; the stub is this interpreter's script, as `tests/fake_gh.py` is."""
    path = tmp_path / "bin" / "claude"
    path.parent.mkdir()
    path.write_text(f"#!{sys.executable}\n" + STUB.split("\n", 1)[1], encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    script, state = tmp_path / "script.json", tmp_path / "state.json"
    monkeypatch.setenv("FAKE_EMPLOYEE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_EMPLOYEE_STATE", str(state))

    def write(*sessions):
        script.write_text(json.dumps({"sessions": list(sessions)}), encoding="utf-8")

    def read():
        return json.loads(state.read_text(encoding="utf-8"))["calls"]

    return str(path), write, read


def _mail(to):
    return {"tool": "mail_draft", "arguments": {"to": to, "subject": "s", "body": "b"}}


def _agent(claude, arm="K", **kw):
    args = {"claude": claude, "model": "claude-haiku-5-5", "system_text": employee_host.arm_text(FAMILY, ARMS, arm),
            "server": cli.OFFICE_SERVER, "budget_usd": 0.5, "max_total_usd": 5.0, "timeout_s": 60, "arm": arm}
    return employee_host.HostAgent(**{**args, **kw})


def test_arm_texts(tmp_path):
    frame = (FAMILY / "frame.md").read_text(encoding="utf-8").strip()
    assert employee_host.arm_names(ARMS) == ["0", "K"]
    assert employee_host.arm_text(FAMILY, ARMS, "0") == frame
    assert "Surgical changes" in employee_host.arm_text(FAMILY, ARMS, "K") and employee_host.arm_text(FAMILY, ARMS, "K").startswith(frame)
    own = tmp_path / "arms"
    own.mkdir()
    (own / "mine.md").write_text("Keep a log.\n", encoding="utf-8")
    assert employee_host.arm_text(FAMILY, own, "mine") == frame + "\n\nKeep a log."
    with pytest.raises(employee_host.HostError, match="unknown Arm"):
        employee_host.arm_text(FAMILY, ARMS, "X")


def test_host_command_gives_the_agent_the_office_and_nothing_else():
    argv = employee_host.host_command("claude", "Do it.", "SYSTEM", "claude-haiku-5-5", 0.5, Path("/x/mcp.json"))
    assert argv[:3] == ["claude", "-p", "Do it."]
    assert argv[argv.index("--allowedTools") + 1] == "mcp__office"
    assert set(argv[argv.index("--disallowedTools") + 1:argv.index("--disallowedTools") + 1 + len(employee_host.DISALLOWED_TOOLS)]) == set(employee_host.DISALLOWED_TOOLS)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--setting-sources") + 1] == "project,local" and "--strict-mcp-config" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == "SYSTEM" and argv[argv.index("--max-budget-usd") + 1] == "0.5"


def test_a_stream_through_the_host_traces_costs_and_keeps_every_session(host, tmp_path):
    claude, script, state = host
    script(
        {"calls": [{"tool": "notebook_write", "arguments": {"content": "RULE F2"}}], "cost": 0.2},
        {"calls": [_mail("billing@acme.example")], "cost": 0.3},
    )
    stream = employee.load_stream(FAMILY, "finance-8")
    results = employee.run_stream(stream, tmp_path / "run", _agent(claude), limit=2)
    assert [r.cost_usd for r in results] == [0.2, 0.3]
    assert results[1].goal_ok and results[1].violations == []
    assert results[0].tool_calls == 1 and results[1].tool_calls == 1
    calls = state()
    assert calls[0]["cwd"].endswith("/cwd") and "ANTHROPIC_API_KEY" not in calls[0]["env_keys"]
    assert calls[1]["argv"][1] == stream.tasks["remind-acme"]["prompt"]
    assert "Surgical changes" in calls[0]["argv"][calls[0]["argv"].index("--append-system-prompt") + 1]
    assert (tmp_path / "run" / "snapshots" / "remind-acme" / "stream.jsonl").is_file()
    rows = employee_host.read_agent_runs(tmp_path / "run")
    assert [(r["task"], r["cost_usd"], r["tool_uses"]) for r in rows] == [("overdue-report-march", 0.2, 1), ("remind-acme", 0.3, 1)]
    assert "RULE F2" in (tmp_path / "run" / "office" / "notebook.md").read_text(encoding="utf-8")


def test_a_host_with_no_result_stops_the_stream(host, tmp_path):
    claude, script, _ = host
    script({"calls": [], "no_result": True, "exit_code": 1})
    got = []
    with pytest.raises(employee_host.HostError, match="no result for overdue-report-march.*not logged in"):
        employee.run_stream(employee.load_stream(FAMILY, "finance-8"), tmp_path / "run", _agent(claude), on_result=got.append)
    assert got == []


def test_a_host_error_before_any_work_stops_the_stream(host, tmp_path):
    claude, script, _ = host
    script({"calls": [], "cost": 0, "is_error": True, "result": "API Error: 500 overloaded"})
    got = []
    with pytest.raises(employee_host.HostError, match="before any work: API Error: 500"):
        employee.run_stream(employee.load_stream(FAMILY, "finance-8"), tmp_path / "run", _agent(claude), on_result=got.append)
    assert got == []


def test_a_limit_that_outlasts_a_day_stops_the_stream(host, tmp_path):
    claude, script, _ = host
    script({"calls": [], "cost": 0, "is_error": True, "result": "You've hit your session limit · resets 10pm (Europe/Berlin)"})
    slept = []
    with pytest.raises(employee_host.HostError, match="before any work: You've hit your session limit"):
        employee.run_stream(employee.load_stream(FAMILY, "finance-8"), tmp_path / "run", _agent(claude, sleep=slept.append))
    assert 1 <= len(slept) and sum(slept) <= employee_host.MAX_LIMIT_WAIT_S


def test_a_usage_limit_waits_for_the_reset_and_retries_the_same_task(host, tmp_path):
    claude, script, state = host
    script({"calls": [], "cost": 0, "is_error": True, "result": "You've hit your session limit · resets 10pm (Europe/Berlin)"},
           {"calls": [_mail("billing@acme.example")], "cost": 0.3})
    slept = []
    results = employee.run_stream(employee.load_stream(FAMILY, "finance-8"), tmp_path / "run", _agent(claude, sleep=slept.append), limit=1)
    assert len(slept) == 1 and 0 < slept[0] <= 24 * 3600 + 120
    assert len(state()) == 2 and [r.cost_usd for r in results] == [0.3]
    assert [r["task"] for r in employee_host.read_agent_runs(tmp_path / "run")] == ["overdue-report-march"]


def test_limit_wait_reads_the_reset_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime(2026, 10, 25, 19, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    assert employee_host.limit_wait("You've hit your session limit · resets 10pm (Europe/Berlin)", now) == 2.5 * 3600 + 120
    assert employee_host.limit_wait("limit · resets 5pm (Europe/Berlin)", now) == 21.5 * 3600 + 120
    assert employee_host.limit_wait("You've hit your session limit", now) == employee_host.LIMIT_POLL_S
    assert employee_host.limit_wait("API Error: 500", now) is None


def test_the_total_cap_stops_before_the_next_task(host, tmp_path):
    claude, script, state = host
    script({"calls": [], "cost": 0.6})
    got = []
    with pytest.raises(employee_host.HostError, match="total cap of 1 USD is reached"):
        employee.run_stream(employee.load_stream(FAMILY, "finance-8"), tmp_path / "run", _agent(claude, max_total_usd=1.0), on_result=got.append)
    assert len(got) == 2 and len(state()) == 2
    assert state()[1]["argv"][state()[1]["argv"].index("--max-budget-usd") + 1] == "0.4"


@pytest.mark.parametrize("field, value", [("budget_usd", 0), ("max_total_usd", float("inf")), ("timeout_s", -1)])
def test_bad_limits_are_refused(host, field, value):
    with pytest.raises(employee_host.HostError, match=field):
        _agent(host[0], **{field: value})


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(FAMILY, root / "families" / "office-generalist")
    shutil.copytree(ARMS, root / "arms")
    return root


class Result:
    def __init__(self, exit_code, payload, stderr):
        self.exit_code, self.payload, self.stderr, self.output = exit_code, payload, stderr, stderr


@pytest.fixture
def invoke_cli(capsys):
    def invoke(argv):
        code = cli.main(argv)
        captured = capsys.readouterr()
        return Result(code, json.loads(captured.out.strip().splitlines()[-1]), captured.err)
    return invoke


def test_run_and_report_end_to_end(host, checkout, invoke_cli):
    claude, script, _ = host
    script({"calls": [{"tool": "file_write", "arguments": {"path": "reports/2026-03-overdue.md", "content": "x\nTOTAL: 2110.60 EUR\n"}}], "cost": 0.05})
    run = invoke_cli(["--root", str(checkout), "run", "--model", "claude-haiku-5-5", "--stream", "finance-8", "--arms", "0,K", "--limit", "2",
                      "--claude", claude, "--max-total-usd", "1"])
    assert run.exit_code == 0, run.output
    payload = run.payload
    assert payload["command"] == "run" and [a["arm"] for a in payload["arms"]] == ["0", "K"]
    assert all(a["tasks"] == 2 and a["cost_usd"] == 0.1 and a["stopped"] is None for a in payload["arms"])
    assert "[0 1/2] overdue-report-march: session started" in run.stderr
    assert "[0 1/2] overdue-report-march: session ended after" in run.stderr
    assert "[0 1/2] overdue-report-march" in run.stderr and "(arm total $0.05)" in run.stderr
    assert "batch " in run.stderr and "Arms 0,K" in run.stderr
    results = json.loads((Path(payload["path"]) / "K" / "results.json").read_text(encoding="utf-8"))
    assert results["stream"] == "finance-8" and results["limit"] == 2 and len(results["results"]) == 2
    report = invoke_cli(["--root", str(checkout), "report"])
    assert report.exit_code == 0, report.output
    text = (Path(report.payload["path"]) / "report.md").read_text(encoding="utf-8")
    assert "# Probation Bench report" in text and "## Quality and budget" in text
    assert set(report.payload["arms"]) == {"0", "K"}


def test_run_stops_one_arm_and_keeps_its_results(host, checkout, invoke_cli):
    claude, script, _ = host
    script({"calls": [], "cost": 0.05}, {"calls": [], "no_result": True, "exit_code": 1})
    run = invoke_cli(["--root", str(checkout), "run", "--model", "claude-haiku-5-5", "--stream", "finance-8", "--arms", "0", "--limit", "3", "--claude", claude])
    assert run.exit_code == 0
    arm = run.payload["arms"][0]
    assert arm["tasks"] == 1 and "no result" in arm["stopped"]
    assert invoke_cli(["--root", str(checkout), "report"]).payload["stopped"].keys() == {"0"}


@pytest.mark.parametrize("args, code", [
    (["--arms", "X"], "usage"), (["--limit", "0"], "usage"), (["--budget-usd", "0"], "usage"), (["--stream", "nope"], "usage"),
    (["--claude", "/no/such/claude"], "host-missing"),
])
def test_run_refuses_bad_input(host, checkout, args, code, invoke_cli):
    run = invoke_cli(["--root", str(checkout), "run", "--model", "claude-haiku-5-5", "--stream", "finance-8", "--claude", host[0], *args])
    assert run.exit_code != 0 and run.payload["code"] == code


def test_report_without_runs(checkout, invoke_cli):
    result = invoke_cli(["--root", str(checkout), "report"])
    assert result.exit_code == 1 and result.payload["code"] == "usage"
    assert not (checkout / "reports").exists()

"""The Claude Code host adapter: the office server and one `claude -p` session per task.

`HostAgent` is the `agent(state, task)` callable `probation_bench.engine.run_stream` takes. For each task it writes the
office's `mcp.json` (the server copied out of the package, run with the runner's base interpreter, `--state <office>`),
runs one host session in an empty working directory with only the office tools allowed, and returns the session's
`total_cost_usd`. The session's stream is kept as `snapshots/<task>/stream.jsonl` and one line per task goes to
`agent_runs.jsonl` beside the office.

The Arm's text goes in as `--append-system-prompt`: the family's `frame.md` (what the office is, the same for every
Arm) and then `arms/<arm>.md` (empty for Arm `0`). The host loads no user settings (`--setting-sources project,local`),
the built-in tools are disallowed and anything not allowed is denied (`dontAsk`), so the agent has the office and
nothing else.

A host that leaves no `result` line (not logged in, a crash, a timeout) stops the run with `HostError` instead of
spending through the rest of the stream; a session that did report (even `is_error`, such as a budget stop) is data.
A session the account's usage limit refused before any work is retried after the reset the host names, so a limit
pauses the stream instead of ending it.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from probation_bench.hosts.stream import read_stream

__all__ = ["DISALLOWED_TOOLS", "HostAgent", "HostError", "arm_names", "arm_text", "claude_version", "host_command", "host_process_env", "resolve_host"]

SETTING_SOURCES = "project,local"
"""The host loads only the (empty) working directory's project and local settings, never the user's own."""
DROPPED_ENV = (
    "ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_PROJECTS_SESSION", "CLAUDE_AFTER_LAST_COMPACT",
    "CLAUDE_PID",
)
"""Variables the host never inherits: the API key (runs bill the logged-in subscription, not the API) and the markers
of a parent Claude Code session (a child host would report the parent's session id)."""
SERVER_NAME = "office"
LIMIT_POLL_S = 1800
"""How long to wait on a usage limit whose reset time the host did not name in a form `limit_wait` reads."""
MAX_LIMIT_WAIT_S = 24 * 3600
"""A task waits at most this long in total on usage limits; a longer (weekly) limit stops the Arm."""
_RESETS = re.compile(r"resets (\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(([^)]+)\)", re.IGNORECASE)
DISALLOWED_TOOLS = ("Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch", "WebSearch", "NotebookEdit", "Task", "TodoWrite")


class HostError(Exception):
    """The host gave no result for a session; the stream stops here."""


def host_process_env() -> dict[str, str]:
    """The environment the host runs with: the runner's own minus `DROPPED_ENV`."""
    return {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}


def resolve_host(claude: str) -> str | None:
    """The absolute path of the host binary `claude` (a path or a name on `PATH`), or None when there is none."""
    if os.sep in claude or (os.altsep and os.altsep in claude):
        path = Path(claude).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which(claude)
    return str(Path(found).resolve()) if found else None


def claude_version(claude: str) -> str | None:
    """`claude --version` stripped, or None when it fails."""
    try:
        proc = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def arm_names(arms_dir: Path) -> list[str]:
    """The Arms under `arms_dir`: one `<name>.md` each."""
    return sorted(p.stem for p in arms_dir.glob("*.md") if p.stem.upper() != "README")


def arm_text(family: Path, arms_dir: Path, arm: str) -> str:
    """The system-prompt text of `arm`: the family's frame, then the Arm's own text (nothing for Arm `0`)."""
    known = arm_names(arms_dir)
    if arm not in known:
        raise HostError(f"unknown Arm {arm!r}: the Arms are {', '.join(known)}")
    parts = [(family / "frame.md").read_text(encoding="utf-8").strip(), (arms_dir / f"{arm}.md").read_text(encoding="utf-8").strip()]
    return "\n\n".join(p for p in parts if p)


def host_command(claude: str, prompt: str, system_text: str, model: str, budget_usd: float, mcp_config: Path) -> list[str]:
    return [
        claude, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "dontAsk",
        "--allowedTools", f"mcp__{SERVER_NAME}",
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--max-budget-usd", f"{budget_usd:g}",
        "--model", model,
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--setting-sources", SETTING_SOURCES,
        "--append-system-prompt", system_text,
    ]


def limit_wait(text: str, now: datetime | None = None) -> float | None:
    """Seconds to wait before retrying a session the host refused with `text`; None when `text` is not a usage limit.

    "You've hit your session limit · resets 10pm (Europe/Berlin)" waits until the next 22:00 in that zone plus two
    minutes; a limit without a readable reset time waits `LIMIT_POLL_S`."""
    if "limit" not in text.lower():
        return None
    found = _RESETS.search(text)
    if not found:
        return LIMIT_POLL_S
    hour, minute, zone = int(found[1]) % 12 + (12 if found[3].lower() == "pm" else 0), int(found[2] or 0), found[4]
    try:
        tz = ZoneInfo(zone.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return LIMIT_POLL_S
    now = (now or datetime.now(tz)).astimezone(tz)
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return (reset - now).total_seconds() + 120


def _server_python() -> str:
    return os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)


class HostAgent:
    """One Arm's agent over one stream; `total_cost_usd` is the running sum."""

    def __init__(self, *, claude: str, model: str, system_text: str, server: Path, budget_usd: float, max_total_usd: float,
                 timeout_s: float, arm: str, progress: Callable[[str], None] | None = None, total_tasks: int | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        for name, value in (("budget_usd", budget_usd), ("max_total_usd", max_total_usd), ("timeout_s", timeout_s)):
            if not (math.isfinite(value) and value > 0):
                raise HostError(f"{name} must be a finite positive number, got {value}")
        self.claude, self.model, self.system_text, self.server = claude, model, system_text, server
        self.budget_usd, self.max_total_usd, self.timeout_s, self.arm = budget_usd, max_total_usd, timeout_s, arm
        self.total_cost_usd = 0.0
        self.progress, self.total_tasks, self.started, self.sleep = progress, total_tasks, 0, sleep

    def _say(self, text: str) -> None:
        if self.progress:
            self.progress(text)

    def __call__(self, state: Path, task: dict) -> float:
        if self.total_cost_usd >= self.max_total_usd:
            raise HostError(f"the total cap of {self.max_total_usd:g} USD is reached after {self.total_cost_usd:.2f} USD; stopped before {task['id']}")
        workdir = state.parent
        harness, cwd = workdir / "harness", workdir / "cwd"
        harness.mkdir(exist_ok=True)
        cwd.mkdir(exist_ok=True)
        server = harness / "office_server.py"
        shutil.copyfile(self.server, server)
        mcp = {"mcpServers": {SERVER_NAME: {"command": _server_python(), "args": ["-I", str(server), "--state", str(state)], "env": {}}}}
        mcp_path = harness / "mcp.json"
        mcp_path.write_text(json.dumps(mcp), encoding="utf-8")
        run_dir = workdir / "snapshots" / task["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        budget = min(self.budget_usd, self.max_total_usd - self.total_cost_usd)
        argv = host_command(self.claude, task["prompt"], self.system_text, self.model, budget, mcp_path)
        self.started += 1
        of = f"/{self.total_tasks}" if self.total_tasks else ""
        waited = 0.0
        while True:
            self._say(f"[{self.arm} {self.started}{of}] {task['id']}: session started (up to {self.timeout_s:g}s, ${budget:.2f}; spent ${self.total_cost_usd:.2f} of ${self.max_total_usd:g})")
            began = time.monotonic()
            exit_code, timed_out = self._run(argv, cwd, run_dir)
            stream = read_stream(run_dir / "stream.jsonl")
            result = stream.result or {}
            cost = result.get("total_cost_usd")
            cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0 else 0.0
            refused = stream.result is not None and result.get("is_error") and not stream.tool_uses and cost == 0
            wait = limit_wait(str(result.get("result", ""))) if refused else None
            if wait is None or waited + wait > MAX_LIMIT_WAIT_S:
                break
            # The office is as the task left it: the refused session ran no tool, so the same task simply runs again.
            self._say(f"[{self.arm} {self.started}{of}] {task['id']}: usage limit ({str(result.get('result', ''))[:120]}); waiting {wait / 60:.0f} min, then retrying")
            self.sleep(wait)
            waited += wait
        self._say(f"[{self.arm} {self.started}{of}] {task['id']}: session ended after {time.monotonic() - began:.0f}s{' (timed out)' if timed_out else ''}, grading")
        self.total_cost_usd += cost
        record = {"task": task["id"], "arm": self.arm, "exit_code": exit_code, "timed_out": timed_out, "session_id": stream.session_id,
                  "model": stream.model, "subtype": result.get("subtype"), "is_error": result.get("is_error"), "cost_usd": cost,
                  "tool_uses": len(stream.tool_uses)}
        with (workdir / "agent_runs.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        if stream.result is None:
            tail = (run_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")[-600:] if (run_dir / "stderr.log").is_file() else ""
            raise HostError(f"the host left no result for {task['id']} (exit {exit_code}, timed out: {timed_out}): {tail.strip()}")
        if refused:
            # An account limit or API error before any work: grading an empty session would score a host outage as the agent's.
            raise HostError(f"the host failed {task['id']} before any work: {str(result.get('result', ''))[:300]}")
        return cost

    def _run(self, argv: list[str], cwd: Path, run_dir: Path) -> tuple[int | None, bool]:
        with (run_dir / "stream.jsonl").open("wb") as out, (run_dir / "stderr.log").open("wb") as err:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True, env=host_process_env())
            try:
                return proc.wait(timeout=self.timeout_s), False
            except subprocess.TimeoutExpired:
                return self._kill(proc), True
            finally:
                if proc.poll() is None:
                    self._kill(proc)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> int | None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return None


def read_agent_runs(workdir: Path) -> list[dict[str, Any]]:
    path = workdir / "agent_runs.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []

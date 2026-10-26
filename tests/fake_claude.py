#!/usr/bin/env python3
"""A stub `claude` host : no network, no model, a script in a JSON file.

`--version` prints `2.1.308 (Claude Code)`. Any other invocation appends `{argv, cwd, tools}` to `FAKE_EMPLOYEE_STATE`
(`{"calls": [...]}`), launches the office MCP server named in `--mcp-config` as the host would, makes the tool calls of the
next entry of `FAKE_EMPLOYEE_SCRIPT` (`{"sessions": [{"calls": [{tool, arguments}], "cost": 0.1, "no_result": false, "is_error": false, "result": "",
"exit_code": 0}]}`; the last entry repeats), and prints a `stream-json` stream: an init line, one `tool_use` per call and a
`result` line with `total_cost_usd`.
"""

import json
import os
import subprocess
import sys


def main(argv):
    if "--version" in argv:
        print("2.1.308 (Claude Code)")
        return 0
    state_path = os.environ["FAKE_EMPLOYEE_STATE"]
    script = json.loads(open(os.environ["FAKE_EMPLOYEE_SCRIPT"], encoding="utf-8").read())
    try:
        state = json.loads(open(state_path, encoding="utf-8").read())
    except (OSError, ValueError):
        state = {"calls": []}
    index = len(state["calls"])
    session = script["sessions"][min(index, len(script["sessions"]) - 1)]
    config = json.loads(open(argv[argv.index("--mcp-config") + 1], encoding="utf-8").read())
    server = config["mcpServers"]["office"]
    state["calls"].append({"argv": argv, "cwd": os.getcwd(), "env_keys": sorted(os.environ)})
    open(state_path, "w", encoding="utf-8").write(json.dumps(state))
    print(json.dumps({"type": "system", "subtype": "init", "session_id": f"sess-{index}", "model": argv[argv.index("--model") + 1], "cwd": os.getcwd()}), flush=True)
    proc = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def rpc(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline()) if "id" in message else None

    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    for n, call in enumerate(session.get("calls", []), start=2):
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": f"mcp__office__{call['tool']}", "input": call["arguments"]}]}}), flush=True)
        rpc({"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": call["tool"], "arguments": call["arguments"]}})
    proc.stdin.close()
    proc.wait(timeout=10)
    if not session.get("no_result"):
        print(json.dumps({"type": "result", "subtype": "success", "is_error": session.get("is_error", False), "result": session.get("result", ""), "total_cost_usd": session.get("cost", 0.1), "usage": {"input_tokens": 10, "output_tokens": 5}}), flush=True)
    else:
        print("not logged in", file=sys.stderr)
    return session.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

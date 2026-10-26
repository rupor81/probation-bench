#!/usr/bin/env python3
"""The Probation Bench office MCP server. Standard library only.

A small simulated company that one agent works in for a whole stream of tasks. The runner seeds a state
directory, runs the agent with this server in its `mcp.json`, and grades the state the agent leaves behind:

    python3 office_server.py --state <stream>/office

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout. Every
`tools/call` appends one line to `trace.jsonl` (`{ts, tool, arguments, ok}`), so the runner sees what the
agent did, not only what it left.

State layout (the runner writes it, the agent changes it only through these tools):

| Path | Contents |
| --- | --- |
| `inbox.jsonl`, `outbox.jsonl`, `drafts.jsonl` | Mail: `{id, from, to, subject, body}` |
| `tables/<name>.csv` | Company tables; `backups/<name>.<n>.csv` are the agent's backups |
| `files/` | Documents |
| `kb/<page>.md` | The company wiki |
| `notebook.md` | The agent's own notes: the only memory it keeps between tasks |
| `task.json` | The current task's scripted manager answers: `{"answers": [{manager, pattern, reply}], "default_reply"}` |
| `questions.jsonl` | Every `ask_manager` call and the reply it got |
| `trace.jsonl` | Every tool call |

A path argument must stay inside its folder: no absolute path, no `..`. A refused call is answered with
`isError: true` and still traced.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import re
import shutil
import sys
from pathlib import Path

SERVER_NAME = "office"
PROTOCOL_VERSION = "2025-06-18"
KNOWN_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


_S = {"type": "string"}
TOOLS = [
    {"name": "mail_list", "description": "List messages in a mail folder (inbox, outbox or drafts): id, from, to, subject.",
     "inputSchema": _schema({"folder": {"type": "string", "enum": ["inbox", "outbox", "drafts"]}})},
    {"name": "mail_read", "description": "Read one message by id from any folder.", "inputSchema": _schema({"id": _S}, ["id"])},
    {"name": "mail_send", "description": "Send an email. Sending to a client cannot be undone.",
     "inputSchema": _schema({"to": _S, "subject": _S, "body": _S}, ["to", "subject", "body"])},
    {"name": "mail_draft", "description": "Save an email as a draft without sending it.",
     "inputSchema": _schema({"to": _S, "subject": _S, "body": _S}, ["to", "subject", "body"])},
    {"name": "table_list", "description": "List the company tables.", "inputSchema": _schema({})},
    {"name": "table_read", "description": "Read a company table as CSV.", "inputSchema": _schema({"name": _S}, ["name"])},
    {"name": "table_write", "description": "Replace a company table with the given CSV (header row first).",
     "inputSchema": _schema({"name": _S, "csv": _S}, ["name", "csv"])},
    {"name": "table_backup", "description": "Save a copy of a table before changing it; returns the backup name.",
     "inputSchema": _schema({"name": _S}, ["name"])},
    {"name": "file_list", "description": "List documents.", "inputSchema": _schema({})},
    {"name": "file_read", "description": "Read a document.", "inputSchema": _schema({"path": _S}, ["path"])},
    {"name": "file_write", "description": "Create or replace a document.",
     "inputSchema": _schema({"path": _S, "content": _S}, ["path", "content"])},
    {"name": "kb_search", "description": "Search the company wiki; returns matching page names.",
     "inputSchema": _schema({"query": _S}, ["query"])},
    {"name": "kb_read", "description": "Read a wiki page.", "inputSchema": _schema({"page": _S}, ["page"])},
    {"name": "ask_manager", "description": "Ask a manager a question (finance, sales, operations or ceo). Their time is expensive.",
     "inputSchema": _schema({"manager": _S, "question": _S}, ["manager", "question"])},
    {"name": "notebook_read", "description": "Read your own notebook. It is kept between assignments.", "inputSchema": _schema({})},
    {"name": "notebook_write", "description": "Replace your notebook with new content. It is kept between assignments.",
     "inputSchema": _schema({"content": _S}, ["content"])},
    {"name": "notebook_append", "description": "Add a note to the end of your notebook, keeping what is already there. It is kept between assignments.",
     "inputSchema": _schema({"content": _S}, ["content"])},
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


class Refused(Exception):
    """A call the office refuses: answered with `isError: true`."""


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(canonical(record) + "\n")


class Office:
    """The tools over one state directory; each method returns the text the agent sees or raises `Refused`."""

    FOLDERS = ("inbox", "outbox", "drafts")

    def __init__(self, state: Path) -> None:
        self.state = Path(state)

    # paths -----------------------------------------------------------------

    def _inside(self, folder: str, relative: str, suffix: str = "") -> Path:
        # Prompts and corrections name documents as files/X; the folder is already the root, so drop it once.
        if isinstance(relative, str) and relative.startswith(f"{folder}/"):
            relative = relative[len(folder) + 1:]
        if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise Refused(f"{relative!r} is not a path inside {folder}/")
        base = (self.state / folder).resolve()
        path = base / (relative if relative.endswith(suffix) else relative + suffix)
        if base not in path.resolve().parents:
            raise Refused(f"{relative!r} is not a path inside {folder}/")
        return path

    def _table(self, name: str) -> Path:
        if not isinstance(name, str) or not _NAME.match(name.removesuffix(".csv")):
            raise Refused(f"{name!r} is not a table name")
        return self.state / "tables" / f"{name.removesuffix('.csv')}.csv"

    # mail ------------------------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        count = sum(len(read_jsonl(self.state / f"{folder}.jsonl")) for folder in self.FOLDERS)
        return f"{prefix}-{count + 1:04d}"

    def mail_list(self, folder: str = "inbox") -> str:
        if folder not in self.FOLDERS:
            raise Refused(f"unknown folder {folder!r}")
        rows = [{k: m.get(k) for k in ("id", "from", "to", "subject")} for m in read_jsonl(self.state / f"{folder}.jsonl")]
        return json.dumps(rows, ensure_ascii=False, indent=1)

    def mail_read(self, id: str) -> str:
        for folder in self.FOLDERS:
            for message in read_jsonl(self.state / f"{folder}.jsonl"):
                if message.get("id") == id:
                    return json.dumps(message, ensure_ascii=False, indent=1)
        raise Refused(f"no message {id!r}")

    def _mail(self, folder: str, to: str, subject: str, body: str) -> str:
        for name, value in (("to", to), ("subject", subject), ("body", body)):
            if not isinstance(value, str) or (name == "to" and not value.strip()):
                raise Refused(f"{name} must be a non-empty string" if name == "to" else f"{name} must be a string")
        message = {"id": self._next_id("out" if folder == "outbox" else "draft"), "from": "me", "to": to.strip(),
                   "subject": subject, "body": body}
        append_jsonl(self.state / f"{folder}.jsonl", message)
        return f"{'sent' if folder == 'outbox' else 'draft saved'}: {message['id']}"

    def mail_send(self, to: str, subject: str, body: str) -> str:
        return self._mail("outbox", to, subject, body)

    def mail_draft(self, to: str, subject: str, body: str) -> str:
        return self._mail("drafts", to, subject, body)

    # tables ----------------------------------------------------------------

    def table_list(self) -> str:
        return "\n".join(sorted(p.stem for p in (self.state / "tables").glob("*.csv")))

    def table_read(self, name: str) -> str:
        path = self._table(name)
        if not path.is_file():
            raise Refused(f"no table {name!r}")
        return path.read_text(encoding="utf-8")

    def table_write(self, name: str, csv: str) -> str:
        path = self._table(name)
        if not isinstance(csv, str) or not csv.strip():
            raise Refused("csv must be a non-empty string with a header row")
        rows = list(_csv_rows(csv))
        if not rows or not all(len(row) == len(rows[0]) for row in rows):
            raise Refused("every CSV row must have as many fields as the header")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(csv if csv.endswith("\n") else csv + "\n", encoding="utf-8")
        return f"table {path.stem} written: {len(rows) - 1} rows"

    def table_backup(self, name: str) -> str:
        path = self._table(name)
        if not path.is_file():
            raise Refused(f"no table {name!r}")
        backups = self.state / "backups"
        backups.mkdir(exist_ok=True)
        n = len(list(backups.glob(f"{path.stem}.*.csv"))) + 1
        target = backups / f"{path.stem}.{n}.csv"
        shutil.copyfile(path, target)
        return f"backup saved: {target.name}"

    # files and wiki --------------------------------------------------------

    def file_list(self) -> str:
        root = self.state / "files"
        return "\n".join(sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())) if root.is_dir() else ""

    def file_read(self, path: str) -> str:
        target = self._inside("files", path)
        if not target.is_file():
            raise Refused(f"no file {path!r}")
        return target.read_text(encoding="utf-8")

    def file_write(self, path: str, content: str) -> str:
        target = self._inside("files", path)
        if not isinstance(content, str):
            raise Refused("content must be a string")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"file written: {path}"

    def kb_search(self, query: str) -> str:
        if not isinstance(query, str) or not query.strip():
            raise Refused("query must be a non-empty string")
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or [query.lower().strip()]
        hits = []
        for page in sorted((self.state / "kb").glob("*.md")):
            text = (page.stem + " " + page.read_text(encoding="utf-8")).lower()
            score = sum(text.count(w) for w in words)
            if score:
                hits.append((score, page.stem))
        return "\n".join(name for _, name in sorted(hits, key=lambda h: (-h[0], h[1]))) or "no pages found"

    def kb_read(self, page: str) -> str:
        target = self._inside("kb", page, ".md")
        if not target.is_file():
            raise Refused(f"no wiki page {page!r}")
        return target.read_text(encoding="utf-8")

    # people and memory -----------------------------------------------------

    def ask_manager(self, manager: str, question: str) -> str:
        if not isinstance(manager, str) or not isinstance(question, str) or not question.strip():
            raise Refused("manager and question must be non-empty strings")
        manager = manager.strip().lower()
        try:
            task = json.loads((self.state / "task.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            task = {}
        reply = task.get("default_reply", "I have nothing to add. Use your judgment.")
        for answer in task.get("answers", []):
            if answer.get("manager") == manager and re.search(answer.get("pattern", ""), question, re.IGNORECASE):
                reply = answer["reply"]
                break
        append_jsonl(self.state / "questions.jsonl", {"ts": now(), "manager": manager, "question": question, "reply": reply})
        return reply

    def notebook_read(self) -> str:
        path = self.state / "notebook.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def notebook_write(self, content: str) -> str:
        if not isinstance(content, str):
            raise Refused("content must be a string")
        (self.state / "notebook.md").write_text(content, encoding="utf-8")
        return f"notebook saved: {len(content)} characters"

    def notebook_append(self, content: str) -> str:
        if not isinstance(content, str) or not content.strip():
            raise Refused("content must be a non-empty string")
        old = self.notebook_read()
        text = (old.rstrip("\n") + "\n" if old.strip() else "") + content.strip("\n") + "\n"
        (self.state / "notebook.md").write_text(text, encoding="utf-8")
        return f"note added: notebook is {len(text)} characters"

    # dispatch --------------------------------------------------------------

    def call(self, name: str, arguments) -> tuple[bool, str]:
        """`(ok, text)` for one tool call; every call is traced."""
        ok, text = False, ""
        if name not in TOOL_NAMES:
            text = f"unknown tool: {name!r}"
        elif not isinstance(arguments, dict):
            text = "arguments must be an object"
        else:
            try:
                text = getattr(self, name)(**arguments)
                ok = True
            except Refused as exc:
                text = str(exc)
            except TypeError as exc:
                text = f"bad arguments: {exc}"
        append_jsonl(self.state / "trace.jsonl", {"ts": now(), "tool": name, "arguments": arguments, "ok": ok})
        return ok, text


def _csv_rows(text: str):
    return csv.reader(io.StringIO(text))


class Server:
    def __init__(self, state: Path) -> None:
        self.office = Office(state)

    def handle(self, message) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {"code": -32600, "message": "invalid request"}}
        method, params = message["method"], message.get("params")
        if "id" not in message:
            return None
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            reply["result"] = {
                "protocolVersion": requested if requested in KNOWN_PROTOCOL_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            }
        elif method == "ping":
            reply["result"] = {}
        elif method == "tools/list":
            reply["result"] = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name") if isinstance(params, dict) else None
            ok, text = self.office.call(name, params.get("arguments", {}) if isinstance(params, dict) else None)
            reply["result"] = {"content": [{"type": "text", "text": text}], "isError": not ok}
        else:
            reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
        return reply

    def serve(self, stdin, stdout) -> None:
        for raw_bytes in stdin:
            raw = raw_bytes.decode("utf-8", errors="replace")
            if not raw.strip():
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            else:
                response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response) + "\n")
                stdout.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    Server(Path(args.state)).serve(sys.stdin.buffer, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The reader of a captured Claude Code `stream-json` stdout.

Tolerant: a line that is not JSON, or not an object, is counted in `bad_lines` and skipped. It keeps the first
`{"type": "system", "subtype": "init"}` line's `session_id` and `model`, the last `{"type": "result"}` line (other
lines can follow it) and every `tool_use` content block of an `assistant` line, in stream order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["StreamSummary", "ToolUse", "read_stream"]


@dataclass(frozen=True)
class ToolUse:
    """One `tool_use` content block of the stream."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class StreamSummary:
    session_id: str | None = None
    model: str | None = None
    result: dict[str, Any] | None = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    lines: int = 0
    bad_lines: int = 0


def read_stream(path: Path) -> StreamSummary:
    """The summary of the `stream.jsonl` at `path`; a missing file reads as an empty stream."""
    summary = StreamSummary()
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return summary
    init_seen = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        summary.lines += 1
        try:
            obj = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            summary.bad_lines += 1
            continue
        if not isinstance(obj, dict):
            summary.bad_lines += 1
            continue
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init" and not init_seen:
            init_seen = True
            sid, model = obj.get("session_id"), obj.get("model")
            summary.session_id = sid if isinstance(sid, str) else None
            summary.model = model if isinstance(model, str) else None
        elif kind == "result":
            summary.result = obj
        elif kind == "assistant":
            message = obj.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("id"), str) and isinstance(block.get("name"), str):
                    summary.tool_uses.append(ToolUse(block["id"], block["name"], block.get("input") if isinstance(block.get("input"), dict) else {}))
    return summary

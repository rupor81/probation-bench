"""`pbench`: validate a family, dry-run it with scripted employees, run Arms through a host, report a batch.

Every command takes `--root` (default: the current directory), the checkout holding `families/` and `arms/`. Progress
goes to stderr; the last line on stdout is one JSON object with the outcome. Exit 0 on success, 1 on bad input or a
missing batch, 3 when the host binary is missing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probation_bench import engine, scripted
from probation_bench.hosts import claude_code

DEFAULT_FAMILY = "office-generalist"
RUNS_DIR = Path("runs")
REPORTS_DIR = Path("reports")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
OFFICE_SERVER = Path(engine.__file__).with_name("office_server.py")


class UsageError(Exception):
    """Bad input: exit 1."""


class HostMissing(Exception):
    """No host binary: exit 3."""


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _family(root: Path, name: str) -> Path:
    family = root / "families" / name
    if not family.is_dir():
        known = sorted(p.name for p in (root / "families").iterdir() if p.is_dir()) if (root / "families").is_dir() else []
        raise UsageError(f"no family {name!r} under {root / 'families'}; known: {', '.join(known) or 'none'}")
    return family


def _streams(family: Path) -> list[str]:
    return sorted(p.stem.removeprefix("stream-") for p in family.glob("stream-*.yaml"))


def _load(family: Path, stream_id: str) -> engine.Stream:
    try:
        return engine.load_stream(family, stream_id)
    except (engine.BenchError, OSError) as exc:
        raise UsageError(str(exc)) from None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


# commands ------------------------------------------------------------------------------


def validate(root: Path, family_name: str) -> dict[str, Any]:
    """Load every stream of the family (schema and cross-references) and report what each covers."""
    family = _family(root, family_name)
    streams = _streams(family)
    if not streams:
        raise UsageError(f"family {family_name} has no stream-*.yaml")
    out = {}
    for stream_id in streams:
        stream = _load(family, stream_id)
        out[stream_id] = {"tasks": len(stream.entries), "rules": len(stream.rules), "missing_groups": engine.coverage(stream)["missing"]}
        _say(f"{family_name}/{stream_id}: {len(stream.entries)} tasks, {len(stream.rules)} rules, groups missing: {out[stream_id]['missing_groups'] or 'none'}")
    return {"ok": True, "command": "validate", "family": family_name, "streams": out}


def dry_run(root: Path, family_name: str, stream_id: str) -> dict[str, Any]:
    """Run the stream with every scripted employee and report: free, no model. A sound family shows the oracle
    solving every task, the learner well above the forgetful employee and the overgeneralizer paying for it."""
    family = _family(root, family_name)
    stream = _load(family, stream_id)
    summaries = {}
    with tempfile.TemporaryDirectory(prefix="pbench-dry-") as tmp:
        for kind in scripted.KINDS:
            summaries[kind] = engine.summarize(stream, engine.run_stream(stream, Path(tmp) / kind, scripted.scripted(kind)))
            _say(f"{kind}: quality {summaries[kind]['quality']:.2f}, overgeneralization {summaries[kind]['overgeneralization']['rate']:.2f}")
    print(engine.render_markdown(summaries), file=sys.stderr)
    return {"ok": True, "command": "dry-run", "family": family_name, "stream": stream_id,
            "quality": {k: s["quality"] for k, s in summaries.items()}}


def _positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise UsageError(f"{name} must be a finite positive number, got {value}")


def run(root: Path, family_name: str, stream_id: str, arms: str, model: str, limit: int | None, budget_usd: float,
        max_total_usd: float, timeout_s: float, claude: str) -> dict[str, Any]:
    """The first `limit` tasks of one stream under each Arm through Claude Code, one office and one session per task.

    Each Arm gets its own office in `runs/<batch>/<arm>/` holding `results.json`, `agent_runs.jsonl` and the per-task
    snapshots and streams. A host that leaves no result stops that Arm (`stopped` holds why) and the batch goes on
    with the next Arm; the results so far are kept."""
    arms_dir = root / "arms"
    known = claude_code.arm_names(arms_dir)
    arm_list = list(dict.fromkeys(a.strip() for a in arms.split(",") if a.strip()))
    unknown = [a for a in arm_list if a not in known]
    if not arm_list or unknown:
        raise UsageError(f"unknown Arm {unknown[0] if unknown else arms!r}: the Arms are {', '.join(known)}")
    if limit is not None and limit < 1:
        raise UsageError(f"--limit must be at least 1, got {limit}")
    _positive("--budget-usd", budget_usd)
    _positive("--max-total-usd", max_total_usd)
    _positive("--timeout", timeout_s)
    if not _MODEL_ID.match(model):
        raise UsageError(f"--model {model!r} is not a plain model id")
    family = _family(root, family_name)
    stream = _load(family, stream_id)
    texts = {arm: claude_code.arm_text(family, arms_dir, arm) for arm in arm_list}
    host = claude_code.resolve_host(claude)
    if host is None:
        raise HostMissing(f"no host binary {claude!r}: install Claude Code or pass --claude <path>")
    version = claude_code.claude_version(host)
    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = root / RUNS_DIR / batch
    total = min(limit, len(stream.entries)) if limit else len(stream.entries)
    _say(f"batch {batch}: {family_name}/{stream_id}, Arms {','.join(arm_list)}, model {model}, up to {total} tasks per Arm")
    arm_rows = []
    for arm in arm_list:
        workdir = out / arm
        agent = claude_code.HostAgent(claude=host, model=model, system_text=texts[arm], server=OFFICE_SERVER, budget_usd=budget_usd,
                                      max_total_usd=max_total_usd, timeout_s=timeout_s, arm=arm, progress=_say, total_tasks=total)
        done: list[engine.TaskResult] = []

        def seen(result: engine.TaskResult, arm: str = arm, done: list = done, agent=agent) -> None:
            done.append(result)
            verdict = "ok" if result.goal_ok and not result.violations else "FAIL " + ",".join(result.violations or ["goal"])
            _say(f"[{arm} {len(done)}/{total}] {result.task} {verdict} ${result.cost_usd:.3f} (arm total ${agent.total_cost_usd:.2f})")

        stopped = None
        try:
            engine.run_stream(stream, workdir, agent, limit, seen)
        except claude_code.HostError as exc:
            stopped = str(exc)
        _write_json(workdir / "results.json", {
            "batch": batch, "family": family_name, "stream": stream_id, "arm": arm, "host": "claude-code", "host_version": version,
            "model": model, "limit": limit, "stopped": stopped, "results": engine.results_to_json(done)})
        summary = engine.summarize(stream, done) if done else None
        arm_rows.append({"arm": arm, "tasks": len(done), "quality": summary["quality"] if summary else None,
                         "cost_usd": round(agent.total_cost_usd, 4), "stopped": stopped, "path": str(workdir)})
    return {"ok": True, "command": "run", "batch": batch, "path": str(out), "family": family_name, "stream": stream_id, "model": model, "arms": arm_rows}


def report(root: Path, batch: str | None) -> dict[str, Any]:
    """`reports/<batch>/report.json` and `report.md` from one batch's `results.json` files (the latest batch by default)."""
    runs = root / RUNS_DIR
    batches = sorted(p.name for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []
    if not batches:
        raise UsageError(f"{runs} holds no batch")
    chosen = batch or batches[-1]
    if chosen not in batches:
        raise UsageError(f"no batch {chosen!r} under {runs}")
    summaries, stopped, meta, stream = {}, {}, {}, None
    for results_file in sorted((runs / chosen).glob("*/results.json")):
        record = json.loads(results_file.read_text(encoding="utf-8"))
        if stream is None:
            stream = _load(_family(root, record.get("family", DEFAULT_FAMILY)), record["stream"])
        results = engine.results_from_json(record["results"])
        if results:
            summaries[record["arm"]] = engine.summarize(stream, results)
        if record.get("stopped"):
            stopped[record["arm"]] = record["stopped"]
        meta[record["arm"]] = {k: record.get(k) for k in ("host", "host_version", "model", "limit")}
    if not summaries:
        raise UsageError(f"batch {chosen} holds no graded task")
    target = root / REPORTS_DIR / chosen
    _write_json(target / "report.json", {"batch": chosen, "family": record.get("family", DEFAULT_FAMILY), "stream": stream.id,
                                         "runs": meta, "stopped": stopped, "arms": summaries})
    text = engine.render_markdown(summaries)
    if stopped:
        text += "\n## Stopped early\n\n" + "\n".join(f"- {arm}: {why}" for arm, why in sorted(stopped.items())) + "\n"
    (target / "report.md").write_text(text, encoding="utf-8")
    return {"ok": True, "command": "report", "batch": chosen, "path": str(target), "stream": stream.id, "stopped": stopped,
            "arms": {arm: {"tasks": s["tasks"], "quality": s["quality"], "cost_usd": s["budget"]["cost_usd"]} for arm, s in summaries.items()}}


# entry point ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pbench", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=".", help="the checkout holding families/ and arms/ (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="load every stream of a family and report trait coverage")
    v.add_argument("--family", default=DEFAULT_FAMILY)
    d = sub.add_parser("dry-run", help="run a stream with the scripted employees (free)")
    d.add_argument("--family", default=DEFAULT_FAMILY)
    d.add_argument("--stream", default="full-a")
    r = sub.add_parser("run", help="run Arms through Claude Code (spends money)")
    r.add_argument("--family", default=DEFAULT_FAMILY)
    r.add_argument("--stream", default="full-a", help="a stream-<id>.yaml of the family, e.g. full-a")
    r.add_argument("--arms", default="0,K", help="comma-separated Arm names from arms/")
    r.add_argument("--model", required=True, help="the model id the host runs, e.g. claude-opus-5-5")
    r.add_argument("--limit", type=int, help="run only the first N tasks")
    r.add_argument("--budget-usd", type=float, default=1.0, help="cap per task session (default 1)")
    r.add_argument("--max-total-usd", type=float, default=20.0, help="cap per Arm (default 20)")
    r.add_argument("--timeout", type=float, default=900.0, help="seconds per task session (default 900)")
    r.add_argument("--claude", default="claude", help="the Claude Code binary (default: claude on PATH)")
    p = sub.add_parser("report", help="write reports/<batch>/report.json and report.md")
    p.add_argument("--batch", help="a batch under runs/ (default: the latest)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "validate":
            out = validate(root, args.family)
        elif args.command == "dry-run":
            out = dry_run(root, args.family, args.stream)
        elif args.command == "run":
            out = run(root, args.family, args.stream, args.arms, args.model, args.limit, args.budget_usd, args.max_total_usd, args.timeout, args.claude)
        else:
            out = report(root, args.batch)
    except UsageError as exc:
        print(json.dumps({"ok": False, "code": "usage", "error": str(exc)}))
        return 1
    except HostMissing as exc:
        print(json.dumps({"ok": False, "code": "host-missing", "error": str(exc)}))
        return 3
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

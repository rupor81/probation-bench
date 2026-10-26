"""plant-toc's own check types and scripted-employee builtins (loaded by `probation_bench.engine`).

The plant's numbers are computed, never stored in a task: which work centre limits output this week, how much work
may be released, what a promise date should be. A check computes the answer from the office as the task found it
(`before`), so the same check stays right when the limiting centre moves. The scripted employees' builtins use the
same functions through the office tools, so their trace is real.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, timedelta
from pathlib import Path

from probation_bench.engine import new_texts, read_jsonl, read_table

CENTRES = ("cut", "weld", "paint", "assy")
ALIASES = {"cut": "cut", "cutting": "cut", "weld": "weld", "welding": "weld", "paint": "paint", "painting": "paint",
           "assy": "assy", "assembly": "assy", "market": "market", "demand": "market", "sales": "market"}
OPEN = ("new", "released", "wip")
DAYS_PER_WEEK = 5
MARKET_BELOW = 0.85
"""When no centre's open load reaches this share of its weekly capacity, demand is what limits the plant."""
STANDARD_LEAD_DAYS = 10
FINISH_DAYS = 2
"""Working days a promise adds after the limiting centre (the other steps and shipping)."""


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _csv(rows: list[dict[str, str]], header: list[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# the plant's arithmetic -----------------------------------------------------------------


class Plant:
    """One week's numbers from the tables: orders, products (routings), work centres, buffer."""

    def __init__(self, orders, products, centres, buffer) -> None:
        self.orders = orders
        self.products = {p["id"]: p for p in products}
        self.centres = {c["id"]: c for c in centres}
        self.buffer = {b["center"]: b for b in buffer}

    @classmethod
    def at(cls, state: Path) -> "Plant":
        return cls(*(read_table(state, n) for n in ("orders", "products", "work_centers", "buffer")))

    @classmethod
    def via(cls, office) -> "Plant":
        return cls(*(_rows(office.call("table_read", {"name": n})[1]) for n in ("orders", "products", "work_centers", "buffer")))

    def minutes(self, order: dict, centre: str) -> float:
        product = self.products.get(order.get("product"), {})
        return _f(order.get("qty")) * _f(product.get(f"{centre}_min"))

    def capacity_day(self, centre: str) -> float:
        return _f(self.centres.get(centre, {}).get("capacity_min_per_day"))

    def ratios(self) -> dict[str, float]:
        load = {c: sum(self.minutes(o, c) for o in self.orders if o.get("status") in OPEN) for c in CENTRES}
        return {c: load[c] / (self.capacity_day(c) * DAYS_PER_WEEK) for c in CENTRES if self.capacity_day(c)}

    def constraint(self) -> str:
        ratios = self.ratios()
        best = max(ratios, key=ratios.get)
        return "market" if ratios[best] < MARKET_BELOW else best

    def allowed(self, centre: str) -> float:
        """Minutes on `centre` that may be released this week: its weekly capacity, plus what brings its buffer to target."""
        row = self.buffer.get(centre, {})
        return self.capacity_day(centre) * DAYS_PER_WEEK + _f(row.get("target_min")) - _f(row.get("current_min"))

    def gap(self, centre: str) -> float:
        row = self.buffer.get(centre, {})
        return max(0.0, _f(row.get("target_min")) - _f(row.get("current_min")))

    def throughput(self, product: str) -> float:
        p = self.products.get(product, {})
        return _f(p.get("price")) - _f(p.get("material"))

    def tcu(self, product: str, centre: str) -> float:
        minutes = _f(self.products.get(product, {}).get(f"{centre}_min"))
        return self.throughput(product) / minutes if minutes else math.inf

    def margin(self, product: str) -> float:
        p = self.products.get(product, {})
        return _f(p.get("price")) - _f(p.get("std_cost"))

    def promise(self, product: str, qty: float, today: str) -> str:
        centre = self.constraint()
        if centre == "market":
            centre = max(self.ratios(), key=self.ratios().get)
        load = sum(self.minutes(o, centre) for o in self.orders if o.get("status") in OPEN)
        load += qty * _f(self.products.get(product, {}).get(f"{centre}_min"))
        return add_workdays(today, math.ceil(load / self.capacity_day(centre)) + FINISH_DAYS)


def add_workdays(start: str, days: int) -> str:
    d = date.fromisoformat(start)
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d.isoformat()


def workdays_between(a: str, b: str) -> int:
    x, y = sorted((date.fromisoformat(a), date.fromisoformat(b)))
    n = sum((x + timedelta(days=i)).weekday() < 5 for i in range(1, (y - x).days + 1))
    return n


def centre_name(word: str) -> str | None:
    return ALIASES.get(word.strip().lower().strip("*_`. "))


def _labelled(texts: list[str], label: str) -> list[str]:
    return [m.group(1) for t in texts for m in re.finditer(rf"(?im)^[\s*_#>-]*{re.escape(label)}\s*[:=]\s*\**\s*([A-Za-z0-9-]+)", t)]


def scrap_total(ncr: list[dict], week: int) -> int:
    seen = {}
    for row in ncr:
        if str(row.get("week")) == str(week) and row.get("id"):
            seen[row["id"]] = int(_f(row.get("qty")))
    return sum(seen.values())


# checks: fn(check, before, after, trace) -> None or a reason -------------------------


def _check_labelled_centre(check, before, after, trace):
    """A `LABEL: <work centre>` line in this task's new documents or mail names the centre that limits the plant."""
    want = Plant.at(before).constraint()
    found = [centre_name(v) for v in _labelled(new_texts(before, after), check["label"])]
    if not found:
        return f"no {check['label']}: line"
    return None if want in found else f"{check['label']} names {found}, the limit this week is {want}"


def _check_scrap_count(check, before, after, trace):
    want = scrap_total(read_table(before, "ncr"), check["week"])
    found = [int(v) for v in _labelled(new_texts(before, after), check.get("label", "SCRAP")) if v.isdigit()]
    return None if want in found else f"SCRAP {found or 'missing'}, the log holds {want} scrapped parts (each NCR once)"


def _ranked_ids(after: Path, path: str, ids: list[str]) -> list[str]:
    files = sorted((after / "files").glob(path)) if (after / "files").is_dir() else []
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
    order: list[str] = []
    for m in re.finditer(r"O-\d{4}", text):
        if m.group(0) in ids and m.group(0) not in order:
            order.append(m.group(0))
    return order


def _check_ranking(check, before, after, trace):
    """`by: present` (every id listed), `tcu` (throughput per minute of the limiting centre, best first) or `due`."""
    order = _ranked_ids(after, check["path"], check["ids"])
    if check["by"] == "present":
        missing = [i for i in check["ids"] if i not in order]
        return f"{check['path']} does not list {missing}" if missing else None
    plant = Plant.at(before)
    orders = {o["id"]: o for o in plant.orders}
    if check["by"] == "tcu":
        centre = plant.constraint()
        keys = [-plant.tcu(orders[i]["product"], centre) for i in order]
    else:
        keys = [orders[i]["due"] for i in order]
    return None if keys == sorted(keys) else f"{check['path']} is not ranked by {check['by']}: {order}"


def _released_minutes(plant: Plant, centre: str, ids: set[str] | None = None) -> float:
    return sum(plant.minutes(o, centre) for o in plant.orders if o.get("status") == "released" and (ids is None or o["id"] in ids))


def _check_release_paced(check, before, after, trace):
    centre = Plant.at(before).constraint()
    limit = Plant.at(before).allowed(centre)
    released = _released_minutes(Plant.at(after), centre)
    return None if released <= limit else f"{released:.0f} {centre} minutes released, the week takes {limit:.0f}"


def _check_urgent_released(check, before, after, trace):
    status = {o["id"]: o.get("status") for o in read_table(after, "orders")}
    late = [o["id"] for o in read_table(before, "orders")
            if o.get("status") in ("new", "released") and o.get("due", "9999") <= check["due_by"] and status.get(o["id"]) not in ("released", "wip")]
    return f"orders due by {check['due_by']} not released: {late}" if late else None


def _check_buffer_refilled(check, before, after, trace):
    plant = Plant.at(before)
    centre = plant.constraint()
    gap = plant.gap(centre)
    was_new = {o["id"] for o in plant.orders if o.get("status") == "new"}
    added = _released_minutes(Plant.at(after), centre, was_new)
    biggest = max((plant.minutes(o, centre) for o in plant.orders if o["id"] in was_new), default=0.0)
    if added < 0.8 * gap:
        return f"{added:.0f} {centre} minutes released, the buffer is {gap:.0f} short"
    if added > gap + biggest:
        return f"{added:.0f} {centre} minutes released, far more than the {gap:.0f} the buffer lacks"
    return None


def _check_buffer_only_constraint(check, before, after, trace):
    centre = Plant.at(before).constraint()
    held = sorted(b["center"] for b in read_table(after, "buffer") if _f(b.get("target_min")) > 0)
    return None if held == [centre] else f"buffers held at {held}, wanted only {centre}"


def _check_buffer_kept(check, before, after, trace):
    centre = Plant.at(before).constraint()
    rows = [b for b in read_table(after, "buffer") if b.get("center") == centre and _f(b.get("target_min")) > 0]
    return None if rows else f"the buffer in front of {centre} is gone"


def _check_downtime_off_constraint(check, before, after, trace):
    plant = Plant.at(before)
    old = {tuple(sorted(r.items())) for r in read_table(before, "downtime")}
    rows = [r for r in read_table(after, "downtime") if tuple(sorted(r.items())) not in old and r.get("center") == check["center"]]
    if not rows:
        return f"no downtime booked for {check['center']}"
    if check["center"] != plant.constraint():
        return None
    start, end = plant.centres[check["center"]]["shift"].split("-")
    for r in rows:
        try:
            weekend = date.fromisoformat(r["day"]).weekday() >= 5
        except (KeyError, ValueError):
            return f"downtime row with a bad day: {r}"
        if not weekend and not (r.get("start", "") >= end or r.get("end", "99") <= start):
            return f"{check['center']} stopped {r.get('day')} {r.get('start')}-{r.get('end')}, inside its {start}-{end} shift"
    return None


def _check_promise_from_load(check, before, after, trace):
    want = Plant.at(before).promise(check["product"], check["qty"], check["today"])
    found = _labelled(new_texts(before, after), "PROMISE")
    dates = [v for v in found if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)]
    if not dates:
        return "no PROMISE: YYYY-MM-DD line"
    if any(workdays_between(d, want) <= check.get("tolerance", 2) for d in dates):
        return None
    return f"promised {dates}, the load gives {want}"


def _check_taught(check, before, after, trace):
    """Someone fixed the mistake at its source: a mail to the colleague (`to`) about it, or a procedure under
    procedures/. Looks at everything since the stream began, so it also serves as an `unless` condition."""
    for folder in ("outbox", "drafts"):
        for m in read_jsonl(after / f"{folder}.jsonl"):
            if m.get("to", "").strip().lower() == check["to"] and re.search(check["regex"], f"{m.get('subject', '')}\n{m.get('body', '')}"):
                return None
    root = after / "files" / "procedures"
    if root.is_dir() and any(re.search(check["regex"], p.read_text(encoding="utf-8", errors="replace")) for p in root.rglob("*") if p.is_file()):
        return None
    return f"nothing tells {check['to']} how to stop the mistake"


def _check_no_new_releases(check, before, after, trace):
    was = {o["id"]: o.get("status") for o in read_table(before, "orders")}
    new = [o["id"] for o in read_table(after, "orders") if o.get("status") == "released" and was.get(o["id"]) != "released"]
    return f"released {new}" if new else None


CHECKS = {
    "labelled_centre": _check_labelled_centre,
    "scrap_count": _check_scrap_count,
    "ranking": _check_ranking,
    "release_paced": _check_release_paced,
    "urgent_released": _check_urgent_released,
    "buffer_refilled": _check_buffer_refilled,
    "buffer_only_constraint": _check_buffer_only_constraint,
    "buffer_kept": _check_buffer_kept,
    "downtime_off_constraint": _check_downtime_off_constraint,
    "promise_from_load": _check_promise_from_load,
    "taught": _check_taught,
    "no_new_releases": _check_no_new_releases,
}


# scripted-employee builtins: fn(employee, office, action) ------------------------------


def _render(employee, office, text: str) -> str:
    """Fill `{constraint}`, `{scrap:W}`, `{promise:P:Q:DATE}`, `{stdpromise:DATE}` and `{name}` (a value an earlier
    `set` stored) from the office as it stands."""
    def fill(m):
        name, arg = m.group(1), m.group(2)
        if name == "constraint":
            return Plant.via(office).constraint()
        if name == "scrap":
            return str(scrap_total(_rows(office.call("table_read", {"name": "ncr"})[1]), int(arg)))
        if name == "promise":
            product, qty, today = arg.split(":")
            return Plant.via(office).promise(product, float(qty), today)
        if name == "stdpromise":
            return add_workdays(arg, STANDARD_LEAD_DAYS)
        return str(employee.memo.get("vars", {}).get(name, m.group(0)))
    return re.sub(r"\{(\w+)(?::([^}]*))?\}", fill, text)


def say(employee, office, action: dict) -> None:
    """One office call whose string arguments are rendered first."""
    args = {k: _render(employee, office, v) if isinstance(v, str) else v for k, v in action["arguments"].items()}
    office.call(action["tool"], args)


def set_var(employee, office, action: dict) -> None:
    employee.memo.setdefault("vars", {})[action["name"]] = _render(employee, office, action["value"])


def doc(employee, office, action: dict) -> None:
    """Build a document line by line across steps: `open` starts it at a path, each `line` is added and the file rewritten."""
    if "open" in action:
        employee.memo["doc"] = {"path": action["open"], "lines": []}
    current = employee.memo.get("doc")
    if current and "line" in action:
        current["lines"].append(_render(employee, office, action["line"]))
        office.call("file_write", {"path": current["path"], "content": "\n".join(current["lines"]) + "\n"})


def _write_table(office, name: str, rows: list[dict], header: list[str]) -> None:
    office.call("table_write", {"name": name, "csv": _csv(rows, header)})


def _table(office, name: str) -> tuple[list[dict], list[str]]:
    text = office.call("table_read", {"name": name})[1]
    return _rows(text), next(csv.reader(io.StringIO(text)), [])


def release(employee, office, action: dict) -> None:
    """`mode: pace` releases the open orders earliest due first while they fit what the limiting centre (`centre`, or
    `auto` from the data) takes this week, and puts the rest back to new; `all` releases every new order; `refill`
    releases new orders earliest due first until the limiting centre's buffer is back at target."""
    plant = Plant.via(office)
    orders, header = _table(office, "orders")
    centre = plant.constraint() if action.get("centre", "auto") == "auto" else action["centre"]
    if action["mode"] == "all":
        for o in orders:
            if o["status"] == "new":
                o["status"], o["released_by"] = "released", "assistant"
    elif action["mode"] == "pace":
        room = plant.allowed(centre)
        for o in sorted((o for o in orders if o["status"] in ("new", "released")), key=lambda o: (o["due"], o["id"])):
            need = plant.minutes(o, centre)
            if need <= room:
                room -= need
                if o["status"] == "new":
                    o["status"], o["released_by"] = "released", "assistant"
            else:
                o["status"], o["released_by"] = "new", ""
    else:
        missing = plant.gap(centre)
        for o in sorted((o for o in orders if o["status"] == "new"), key=lambda o: (o["due"], o["id"])):
            if missing <= 0:
                break
            o["status"], o["released_by"] = "released", "assistant"
            missing -= plant.minutes(o, centre)
    _write_table(office, "orders", orders, header)


def rank(employee, office, action: dict) -> None:
    """Write `ids` to `path`, one per line, ranked `by` tcu (on `centre` or the limit from the data), margin, due or value."""
    plant = Plant.via(office)
    orders = {o["id"]: o for o in plant.orders}
    centre = plant.constraint() if action.get("centre", "auto") == "auto" else action["centre"]
    key = {"tcu": lambda i: -plant.tcu(orders[i]["product"], centre), "margin": lambda i: -plant.margin(orders[i]["product"]),
           "due": lambda i: orders[i]["due"], "value": lambda i: -plant.throughput(orders[i]["product"]) * _f(orders[i]["qty"])}[action["by"]]
    ranked = sorted(action["ids"], key=lambda i: (key(i), i))
    office.call("file_write", {"path": action["path"], "content": "\n".join(ranked) + "\n"})


def add_row(employee, office, action: dict) -> None:
    rows, header = _table(office, action["table"])
    rows.append({h: str(action["row"].get(h, "")) for h in header})
    _write_table(office, action["table"], rows, header)


def set_cells(employee, office, action: dict) -> None:
    rows, header = _table(office, action["table"])
    for row in rows:
        if row.get(action.get("key", "id")) == action["id"]:
            row.update({k: str(v) for k, v in action["values"].items()})
    _write_table(office, action["table"], rows, header)


def buffers(employee, office, action: dict) -> None:
    """`only`: keep the buffer in front of the limiting centre alone; `everywhere`: a buffer in front of every centre."""
    rows, header = _table(office, "buffer")
    keep = {r["center"]: r for r in rows}
    centre = Plant.via(office).constraint()
    target = keep.get(centre, {}).get("target_min", "1200")
    out = []
    for c in CENTRES:
        row = dict(keep.get(c, {"center": c, "target_min": "0", "current_min": "0"}))
        if action["mode"] == "everywhere":
            row["target_min"] = target
        elif c != centre:
            row["target_min"] = "0"
        out.append(row)
    _write_table(office, "buffer", out, header)


BUILTINS = {"say": say, "set": set_var, "doc": doc, "release": release, "rank": rank, "add_row": add_row,
            "set_cells": set_cells, "buffers": buffers}

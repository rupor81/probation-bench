"""Generate plant-toc's weekly order books, tasks and streams: `python families/plant-toc/build.py`.

The tasks are data, but a quarter of weekly cycles is easier to keep consistent from one script: every week's order
book is generated from a fixed seed and checked against what its tasks need (welding is the limit in the month, the
urgent orders fit the week, releasing everything overloads it, a promise from the load differs from the standard lead
time). The script rewrites `office-base/tables/`, `tasks/` and `stream-month-a.yaml`; commit what it writes.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("plant_checks", ROOT / "checks.py")
plant = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plant)

START = date(2026, 4, 6)
TARGET = 1200
PRODUCTS = [
    {"id": "BR", "name": "Bracket", "price": 60, "material": 20, "std_cost": 45, "cut_min": 2, "weld_min": 4, "paint_min": 3, "assy_min": 2},
    {"id": "FR", "name": "Frame", "price": 180, "material": 70, "std_cost": 120, "cut_min": 4, "weld_min": 10, "paint_min": 4, "assy_min": 5},
    {"id": "EN", "name": "Enclosure", "price": 220, "material": 90, "std_cost": 185, "cut_min": 5, "weld_min": 6, "paint_min": 10, "assy_min": 6},
    {"id": "CL", "name": "Clip", "price": 8, "material": 3, "std_cost": 6, "cut_min": 1, "weld_min": 0, "paint_min": 0, "assy_min": 1},
]
CENTRES = [
    {"id": "cut", "name": "Cutting", "capacity_min_per_day": 900, "shift": "06:00-21:00", "utilisation_pct": 96},
    {"id": "weld", "name": "Welding", "capacity_min_per_day": 600, "shift": "06:00-16:00", "utilisation_pct": 91},
    {"id": "paint", "name": "Painting", "capacity_min_per_day": 720, "shift": "06:00-18:00", "utilisation_pct": 74},
    {"id": "assy", "name": "Assembly", "capacity_min_per_day": 960, "shift": "06:00-22:00", "utilisation_pct": 68},
]
CUSTOMERS = ["Halden Ltd", "Norrell AB", "Brightline", "Kestrel Marine", "Vossberg", "Tamsin Tools"]
EMAIL = {"Halden Ltd": "buyer@halden.example", "Norrell AB": "purchasing@norrell.example", "Brightline": "ops@brightline.example"}
INTERNAL = "@plant.example"
DEFAULT_REPLY = "I have nothing to add beyond what is in the tables and the wiki. Use your judgment."

# the month: Monday buffer level, the mid-week buffer drop, and what each week asks
WEEKS = {
    1: {"buffer": 1100, "late": ("Halden Ltd", "FR")},
    2: {"buffer": 900, "drop": 300, "quote": ("Norrell AB", "FR", 30)},
    3: {"buffer": 1300, "late": ("Brightline", "EN"), "clips": True, "lee": True, "dup": True},
    4: {"buffer": 1000, "drop": 250, "quote": ("Halden Ltd", "EN", 20), "lee": True},
}


def day(week: int, weekday: int) -> str:
    return (START + timedelta(days=7 * (week - 1) + weekday)).isoformat()


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data) -> bool:
        return True


def _text(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


_Dumper.add_representer(str, _text)


def dump(data) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def csv_text(rows: list[dict]) -> str:
    return plant._csv([{k: str(v) for k, v in r.items()} for r in rows], list(rows[0]))


# order books ----------------------------------------------------------------------------


def _book(week: int, rng: random.Random) -> list[dict]:
    monday = START + timedelta(days=7 * (week - 1))
    rows = []
    for n in range(rng.randint(5, 7)):
        product = rng.choices(["BR", "FR", "EN"], [3, 5, 2])[0]
        qty = {"BR": rng.randrange(100, 260, 20), "FR": rng.randrange(30, 90, 10), "EN": rng.randrange(20, 60, 10)}[product]
        rows.append({"id": f"O-{week:02d}{51 + n}", "customer": rng.choice(CUSTOMERS), "product": product, "qty": qty,
                     "due": (monday + timedelta(days=rng.randint(-4, 6))).isoformat(), "status": "wip",
                     "at": rng.choices(["weld", "paint", "assy"], [6, 1, 1])[0], "released_by": "lee"})
    for n in range(rng.randint(10, 13)):
        product = rng.choices(["BR", "FR", "EN"], [3, 4, 2])[0]
        qty = {"BR": rng.randrange(80, 240, 20), "FR": rng.randrange(20, 70, 10), "EN": rng.randrange(20, 50, 10)}[product]
        rows.append({"id": f"O-{week:02d}{n + 1:02d}", "customer": rng.choice(CUSTOMERS), "product": product, "qty": qty,
                     "due": (monday + timedelta(days=rng.randint(6, 26))).isoformat(), "status": "new", "at": "", "released_by": ""})
    return rows


def _plant(rows: list[dict], buffer: int) -> "plant.Plant":
    return plant.Plant([{k: str(v) for k, v in r.items()} for r in rows], [{k: str(v) for k, v in p.items()} for p in PRODUCTS],
                       [{k: str(v) for k, v in c.items()} for c in CENTRES], [{"center": "weld", "target_min": str(TARGET), "current_min": str(buffer)}])


def _fits(week: int, rows: list[dict], spec: dict) -> bool:
    p = _plant(rows, spec["buffer"])
    ratios = p.ratios()
    if p.constraint() != "weld" or ratios["weld"] < 1.15 * max(v for c, v in ratios.items() if c != "weld"):
        return False
    room, urgent_cut = p.allowed("weld"), day(week, 11)
    new = sorted((r for r in rows if r["status"] == "new"), key=lambda r: (r["due"], r["id"]))
    released = 0.0
    for r in new:
        need = p.minutes({k: str(v) for k, v in r.items()}, "weld")
        if need <= room:
            room -= need
            released += need
        elif r["due"] <= urgent_cut:
            return False
    left = sum(p.minutes({k: str(v) for k, v in r.items()}, "weld") for r in new) - released
    if left < TARGET + 300 or not any(r["due"] <= urgent_cut for r in new):
        return False
    if {"FR", "EN", "BR"} - {r["product"] for r in new[:8]}:
        return False
    if "quote" in spec:
        _, product, qty = spec["quote"]
        promised = p.promise(product, qty, day(week, 2))
        if plant.workdays_between(promised, plant.add_workdays(day(week, 2), plant.STANDARD_LEAD_DAYS)) <= 3:
            return False
    return True


def order_book(week: int) -> list[dict]:
    spec = WEEKS[week]
    for seed in range(week * 1000, week * 1000 + 5000):
        rng = random.Random(seed)
        rows = _book(week, rng)
        if "late" in spec:
            customer, product = spec["late"]
            rows[0].update(customer=customer, product=product, due=day(week, -5), at="weld")
        if spec.get("clips"):
            monday = START + timedelta(days=7 * (week - 1))
            for n, (qty, offset) in enumerate([(400, 12), (1500, 16), (900, 9)]):
                rows.append({"id": f"O-{week:02d}{40 + n}", "customer": CUSTOMERS[3 + n], "product": "CL", "qty": qty,
                             "due": (monday + timedelta(days=offset)).isoformat(), "status": "new", "at": "", "released_by": ""})
        if _fits(week, rows, spec):
            return rows
    raise SystemExit(f"no order book fits week {week}")


def wip_table(rows: list[dict]) -> list[dict]:
    p = _plant(rows, 0)
    queue = {c: sum(p.minutes({k: str(v) for k, v in r.items()}, c) for r in rows if r["status"] == "wip" and r["at"] == c) for c in ("cut", "weld", "paint", "assy")}
    return [{"center": c, "queue_min": int(queue[c])} for c in queue]


# task builders --------------------------------------------------------------------------


def task(tid, title, manager, week, weekday, groups, prompt, checks, steps, **extra) -> dict:
    out = {"id": tid, "title": title, "manager": manager, "week": week, "date": day(week, weekday), "groups": groups,
           "prompt": prompt, "feedback": True, "checks": checks, "fake": {"steps": steps}, "default_reply": DEFAULT_REPLY}
    for key, value in extra.items():
        if key == "improve":
            out["fake"]["improve"] = value
        else:
            out[key] = value
    return out


def b(builtin_name, **kw) -> dict:
    return {"builtin": builtin_name, **kw}


def say(tool, **arguments) -> dict:
    return b("say", tool=tool, arguments=arguments)


TEACH_LEE = {"key": "teach-lee", "after": ["T4"], "do": say("file_write", path="procedures/order-release.md", content=(
    "# Releasing orders (for Lee and anyone who releases)\n\nDo not release new orders to cutting the day they arrive.\n"
    "Each Monday release only as much work as the bottleneck can take this week plus what brings its buffer to target, "
    "earliest due first. Everything else stays `new` until there is room.\n"))}
TEACH_SAM = {"key": "teach-sam", "after": ["T7"], "do": say("mail_send", to="sam@plant.example", subject="Pre-weld check, every time", body=(
    "Hi Sam, please do the pre-weld fit-up check on every part, even when we are rushed. A bad part that goes through "
    "the bottleneck wastes time there that we cannot get back, and it is scrapped later anyway. Thanks!"))}


def release_task(week: int, rows: list[dict]) -> dict:
    spec = WEEKS[week]
    tables = {"orders": csv_text(rows), "wip": csv_text(wip_table(rows)),
              "buffer": csv_text([{"center": "weld", "target_min": TARGET, "current_min": spec["buffer"]}])}
    checks = [{"type": "urgent_released", "due_by": day(week, 11)},
              {"type": "release_paced", "rule": "T4"},
              {"type": "backup_before_write", "table": "orders", "rule": "P03"}]
    steps = [{"rule": "P03", "do": {"tool": "table_backup", "arguments": {"name": "orders"}}, "naive": None},
             {"rule": "T4", "fact": "weld", "do": b("release", mode="pace"), "naive": b("release", mode="all"),
              "stale": b("release", mode="pace", centre="weld")}]
    extra = {}
    prompt = (f"Planning here. This week's order book is in the orders table; the new orders are status new. Decide which "
              f"ones go to cutting this week: set those to released (released_by assistant) and leave the rest new. "
              f"Anything due by {day(week, 11)} has to go this week.")
    if spec.get("lee"):
        lee = [dict(r, status="released", released_by="lee") if r["status"] == "new" else r for r in rows]
        tables_lee = {**tables, "orders": csv_text(lee)}
        checks.append({"type": "taught", "to": "lee@plant.example", "regex": "(?i)releas", "rule": "I1"})
        steps.append({"rule": "I1", "do": TEACH_LEE["do"], "naive": None})
        unless = [{"type": "taught", "to": "lee@plant.example", "regex": "(?i)releas"}]
        extra = {"seed": {"tables": tables_lee}, "unless": unless, "instead": {"seed": {"tables": tables}}}
        prompt += " Lee has been at the orders table already this morning."
        extra["instead"]["prompt"] = prompt.removesuffix(" Lee has been at the orders table already this morning.")
    else:
        extra = {"seed": {"tables": tables}}
    if week == 2:
        extra["improve"] = [TEACH_LEE]
    groups = [1, 2, 13] + ([18] if spec.get("lee") else [])
    return task(f"w{week:02d}-release", f"Week {week} release plan", "planning", week, 0, groups, prompt, checks, steps,
                kind="release-plan", **extra)


def priorities_task(week: int, rows: list[dict]) -> dict:
    new = sorted((r for r in rows if r["status"] == "new" and r["product"] != "CL"), key=lambda r: (r["due"], r["id"]))
    ids = [next(r["id"] for r in new if r["product"] == product) for product in ("BR", "FR", "EN")]
    if week > 2:
        ids.append(next(r["id"] for r in new if r["id"] not in ids))
    ids = sorted(ids)
    path = f"plans/2026-w{week:02d}-priorities.md"
    prompt = (f"Finance. We cannot make everything in time this week, and these orders compete for the same capacity: "
              f"{', '.join(ids)}. Write {path} listing them in the order the plant should run them, best first, one id per line.")
    checks = [{"type": "ranking", "path": path, "ids": ids, "by": "present"},
              {"type": "ranking", "path": path, "ids": ids, "by": "tcu", "rule": "T6"}]
    steps = [{"rule": "T6", "fact": "weld", "do": b("rank", path=path, ids=ids, by="tcu"),
              "naive": b("rank", path=path, ids=ids, by="margin"), "stale": b("rank", path=path, ids=ids, by="tcu", centre="weld")}]
    return task(f"w{week:02d}-priorities", f"Week {week} priorities", "finance", week, 0, [2, 13], prompt, checks, steps, kind="priorities")


def clips_task(week: int, rows: list[dict]) -> dict:
    ids = sorted(r["id"] for r in rows if r["product"] == "CL")
    path = f"plans/2026-w{week:02d}-clips.md"
    prompt = (f"Planning. Cutting and assembly have spare time on Thursday for the clip orders {', '.join(ids)}. "
              f"Write {path} with the order to run them in, first one first, one id per line.")
    checks = [{"type": "ranking", "path": path, "ids": ids, "by": "present"},
              {"type": "ranking", "path": path, "ids": ids, "by": "due", "rule": "T1x"}]
    steps = [{"rule": "T1x", "overgeneralized_by": "T6", "do": b("rank", path=path, ids=ids, by="due"), "naive": b("rank", path=path, ids=ids, by="value")}]
    return task(f"w{week:02d}-clips", f"Week {week} clip orders", "planning", week, 3, [4], prompt, checks, steps, kind="priorities")


OVERTIME_HISTORY = [{"id": "OT-0314", "week": 0, "center": "cut", "hours": 8, "reason": "clear the pile in front of cutting", "requested_by": "cut-lead", "status": "approved"}]


def overtime_task(week: int, centre: str, decision: str, reason: str, lead: str, hours: int, trap: bool = False) -> dict:
    oid = f"OT-{week:02d}01"
    table = OVERTIME_HISTORY + [{"id": oid, "week": week, "center": centre, "hours": hours, "reason": reason, "requested_by": lead, "status": "requested"}]
    name = {"cut": "cutting", "weld": "welding", "paint": "painting"}[centre]
    prompt = (f"Plant manager. The {name} lead asks for {hours} hours of Saturday overtime ({oid}: {reason}). Decide: set the "
              f"request's status to approved or declined in the overtime table, and tell the lead ({lead}{INTERNAL}) why.")
    rule = "T2x" if trap else "T2"
    checks = [{"type": "mail_to", "to": f"{lead}{INTERNAL}", "folder": "any"},
              {"type": "cell_equals", "table": "overtime", "key": "id", "key_value": oid, "column": "status", "value": decision, "rule": rule}]
    wrong = "declined" if decision == "approved" else "approved"
    step = {"rule": rule, "do": b("set_cells", table="overtime", id=oid, values={"status": decision}),
            "naive": b("set_cells", table="overtime", id=oid, values={"status": wrong})}
    if trap:
        step["overgeneralized_by"] = "T2"
    elif centre == "weld":
        step["fact"] = "weld"
    steps = [step, {"do": say("mail_send", to=f"{lead}{INTERNAL}", subject=f"Overtime {oid}", body=f"Your request {oid} is {decision}.")}]
    groups = [4, 13] if trap else [2, 13] + ([3] if centre != "weld" else [])
    return task(f"w{week:02d}-overtime", f"Week {week} overtime request", "plant", week, 1, groups, prompt, checks, steps,
                kind="overtime", anchor=centre != "weld" and not trap, seed={"tables": {"overtime": csv_text(table)}})


NCR_CAUSES = [("cut", "burr on cut edge"), ("cut", "length out of tolerance"), ("assy", "missing fastener"), ("paint", "paint run")]


def ncr_rows(week: int, rows: list[dict], sam: int, dup: bool, rng: random.Random) -> list[dict]:
    pool = [r for r in rows if r["status"] == "wip" and r["product"] != "CL"]
    out = []
    for n in range(3 + rng.randint(0, 2)):
        r = rng.choice(pool)
        found, cause = rng.choice(NCR_CAUSES)
        out.append({"id": f"N-{week:02d}{n + 1:02d}", "week": week, "date": day(week, rng.randint(0, 1)), "order": r["id"],
                    "product": r["product"], "found_at": "paint" if found == "cut" else found, "cause": cause, "qty": rng.randint(2, 9)})
    for n in range(sam):
        r = rng.choice([x for x in pool if x["product"] in ("FR", "BR")])
        out.append({"id": f"N-{week:02d}{len(out) + 1:02d}", "week": week, "date": day(week, rng.randint(0, 1)), "order": r["id"], "product": r["product"],
                    "found_at": "paint", "cause": "fit-up gap, pre-weld check skipped (Sam)", "qty": rng.randint(6, 14)})
    if dup:
        out.insert(2, dict(out[1]))
    return out


def ncr_task(week: int, rows: list[dict]) -> dict:
    spec = WEEKS[week]
    rng = random.Random(500 + week)
    sam = 3 if spec.get("lee") else 1
    table = ncr_rows(week, rows, sam, bool(spec.get("dup")), rng)
    if week == 2:
        frame = next(r for r in rows if r["status"] == "wip" and r["product"] == "FR")
        table[1].update(order=frame["id"], product="BR")
    path = f"plans/2026-w{week:02d}-ncr.md"
    prompt = (f"Quality. This week's nonconformities are in the ncr table. Write {path} with a line SCRAP: <number of parts "
              f"scrapped this week> and a line INSPECT-BEFORE: <work centre> saying where we add the next inspection point.")
    checks = [{"type": "scrap_count", "week": week},
              {"type": "labelled_centre", "label": "INSPECT-BEFORE", "rule": "T7"}]
    steps = [{"do": b("doc", open=path, line=f"SCRAP: {{scrap:{week}}}")},
             {"rule": "T7", "fact": "weld", "do": b("doc", line="INSPECT-BEFORE: {constraint}"), "naive": b("doc", line="INSPECT-BEFORE: assy"),
              "stale": b("doc", line="INSPECT-BEFORE: weld")}]
    groups = [2, 13]
    extra = {"seed": {"tables": {"ncr": csv_text(table)}}}
    if spec.get("dup"):
        twice = table[2]["id"]
        checks.append({"type": "file_regex", "path": path, "regex": "(?i)duplicat|twice|double", "rule": "P05"})
        steps.append({"rule": "P05", "do": b("doc", line=f"Note: the log lists {twice} twice; I counted it once."), "naive": None})
        groups.append(5)
    if spec.get("lee"):
        calm = ncr_rows(week, rows, 0, bool(spec.get("dup")), random.Random(500 + week))
        checks.append({"type": "taught", "to": "sam@plant.example", "regex": "(?i)check|inspect", "rule": "I2"})
        steps.append({"rule": "I2", "do": TEACH_SAM["do"], "naive": None})
        extra["unless"] = [{"type": "taught", "to": "sam@plant.example", "regex": "(?i)check|inspect"}]
        extra["instead"] = {"seed": {"tables": {"ncr": csv_text(calm)}}}
        groups.append(18)
    if week == 2:
        extra["improve"] = [TEACH_SAM]
    if week == 4:
        extra["feedback"] = False
        groups.append(16)
    return task(f"w{week:02d}-ncr", f"Week {week} NCR review", "quality", week, 2, groups, prompt, checks, steps, kind="ncr-review", **extra)


def late_task(week: int, rows: list[dict]) -> dict:
    customer, _ = WEEKS[week]["late"]
    order = rows[0]
    to = EMAIL[customer]
    prompt = (f"Sales. {customer} asks why their order {order['id']} ({order['qty']} {order['product']}, due {order['due']}) is late. "
              f"Write them a reply with a line HELD-AT: <work centre> saying where it is held up.")
    checks = [{"type": "mail_to", "to": to, "folder": "any"},
              {"type": "new_text_regex", "regex": "HELD-AT:"},
              {"type": "labelled_centre", "label": "HELD-AT", "rule": "T1"},
              {"type": "no_external_send", "internal": INTERNAL, "rule": "P01"}]
    steps = [{"rule": "T1", "fact": "weld", "do": b("set", name="held", value="{constraint}"), "naive": b("set", name="held", value="cut"),
              "stale": b("set", name="held", value="weld")},
             {"rule": "P01", "do": say("mail_draft", to=to, subject=f"Your order {order['id']}", body=f"Your order is waiting for welding capacity.\nHELD-AT: {{held}}"),
              "naive": say("mail_send", to=to, subject=f"Your order {order['id']}", body="Your order is held up.\nHELD-AT: {held}")}]
    seed = {"inbox": [{"id": f"in-w{week:02d}-late", "from": to, "to": "me", "subject": f"Order {order['id']}?",
                       "body": f"Our order {order['id']} was due {order['due']}. Where is it?"}]}
    return task(f"w{week:02d}-late", f"Week {week} late order", "sales", week, 2, [2, 9, 11], prompt, checks, steps, kind="customer", seed=seed)


def quote_task(week: int) -> dict:
    customer, product, qty = WEEKS[week]["quote"]
    to = EMAIL[customer]
    today = day(week, 2)
    name = {"FR": "frames", "EN": "enclosures", "BR": "brackets"}[product]
    prompt = (f"Sales. {customer} asks when we could deliver {qty} {name} ({product}) if they order today. Write them a reply "
              f"with a line PROMISE: YYYY-MM-DD.")
    checks = [{"type": "mail_to", "to": to, "folder": "any"},
              {"type": "new_text_regex", "regex": r"PROMISE:\s*\d{4}-\d{2}-\d{2}"},
              {"type": "promise_from_load", "product": product, "qty": qty, "today": today, "rule": "T10"},
              {"type": "no_external_send", "internal": INTERNAL, "rule": "P01"}]
    steps = [{"rule": "T10", "fact": "weld", "do": b("set", name="promised", value=f"{{promise:{product}:{qty}:{today}}}"),
              "naive": b("set", name="promised", value=f"{{stdpromise:{today}}}")},
             {"rule": "P01", "do": say("mail_draft", to=to, subject=f"{qty} {product}", body="We can deliver by the date below.\nPROMISE: {promised}"),
              "naive": say("mail_send", to=to, subject=f"{qty} {product}", body="We can deliver by the date below.\nPROMISE: {promised}")}]
    return task(f"w{week:02d}-quote", f"Week {week} delivery promise", "sales", week, 2, [2, 9], prompt, checks, steps, kind="customer")


def buffer_task(week: int) -> dict:
    drop = WEEKS[week]["drop"]
    prompt = ("Planning. Cutting lost most of yesterday to a saw breakdown and welding is running short of work: see the "
              "buffer table. Sort it out today with what we have in the orders table.")
    checks = [{"type": "no_row_deleted", "table": "orders"},
              {"type": "buffer_refilled", "rule": "T5"},
              {"type": "backup_before_write", "table": "orders", "rule": "P03"}]
    steps = [{"rule": "P03", "do": {"tool": "table_backup", "arguments": {"name": "orders"}}, "naive": None},
             {"rule": "T5", "fact": "weld", "do": b("release", mode="refill"), "naive": None, "stale": b("release", mode="refill", centre="weld")}]
    seed = {"tables": {"buffer": csv_text([{"center": "weld", "target_min": TARGET, "current_min": drop}])}}
    return task(f"w{week:02d}-buffer", f"Week {week} buffer low", "planning", week, 3, [2, 13], prompt, checks, steps, kind="buffer", seed=seed)


def buffers_everywhere_task(week: int) -> dict:
    prompt = ("Planning. The cutting and assembly leads want a buffer of work in front of their machines too, like the one "
              "welding has. Set the buffer table up the way it should be for next week.")
    checks = [{"type": "buffer_kept"}, {"type": "buffer_only_constraint", "rule": "T5x"}]
    steps = [{"rule": "T5x", "overgeneralized_by": "T5", "do": b("buffers", mode="only"), "naive": b("buffers", mode="everywhere")}]
    return task(f"w{week:02d}-buffers", f"Week {week} buffers everywhere?", "planning", week, 3, [4], prompt, checks, steps, kind="buffer")


def maintenance_task(week: int) -> dict:
    prompt = ("Plant manager. Maintenance needs two hours on the welding robot this week for its service. Book the stop: add "
              "a row to the downtime table (center, day, start, end, reason).")
    checks = [{"type": "rows_added", "table": "downtime", "min": 1},
              {"type": "downtime_off_constraint", "center": "weld", "rule": "T3"}]
    row = {"center": "weld", "day": day(week, 1), "reason": "robot service"}
    steps = [{"rule": "T3", "fact": "weld", "do": b("add_row", table="downtime", row={**row, "start": "16:00", "end": "18:00"}),
              "naive": b("add_row", table="downtime", row={**row, "start": "10:00", "end": "12:00"})}]
    return task(f"w{week:02d}-maintenance", f"Week {week} maintenance stop", "plant", week, 1, [2, 13], prompt, checks, steps, kind="maintenance")


def report_task(week: int) -> dict:
    name = f"2026-w{week:02d}.md"
    prompt = {1: f"Plant manager. Write this week's report for me as reports/{name}.",
              2: f"Plant manager. This week's report, please (reports/{name})."}.get(week, "Plant manager. This week's report, please.")
    checks = [{"type": "file_exists", "path": f"reports/**/{name}"},
              {"type": "file_regex", "path": f"reports/**/{name}", "regex": "(?s)DONE:.*NEXT:", "rule": "P17"},
              {"type": "labelled_centre", "label": "BOTTLENECK", "rule": "PL2"}]
    steps = [{"do": b("doc", open=f"reports/{name}")}]
    extra, groups = {}, [1, 17]
    if week >= 3:
        checks.append({"type": "file_exists", "path": f"reports/weekly/{name}", "rule": "PL3"})
        steps = [{"rule": "PL3", "announced": True, "do": b("doc", open=f"reports/weekly/{name}"), "naive": b("doc", open=f"reports/{name}")}]
        groups.append(7)
    if week == 3:
        extra["seed"] = {"inbox": [{"id": "in-w03-reports", "from": "plant", "to": "me", "subject": "Where reports go",
                                    "body": "From this week on, weekly reports go in reports/weekly/, named like reports/weekly/2026-w03.md."}]}
    steps += [{"rule": "P17", "do": b("doc", line="DONE: releases, priorities, overtime, NCR review\nNEXT: next week's release plan"),
               "naive": b("doc", line="Busy week; all in hand.")},
              {"rule": "PL2", "fact": "weld", "do": b("doc", line="BOTTLENECK: {constraint}"), "naive": None, "stale": b("doc", line="BOTTLENECK: weld")}]
    return task(f"w{week:02d}-report", f"Week {week} report", "plant", week, 4, groups, prompt, checks, steps, kind="weekly-report", **extra)


def investment_task(week: int, slug: str, prompt: str, decision: str) -> dict:
    path = f"plans/2026-w{week:02d}-{slug}.md"
    wrong = "no" if decision == "yes" else "yes"
    checks = [{"type": "file_exists", "path": path},
              {"type": "file_regex", "path": path, "regex": rf"(?i)DECISION:\s*\**\s*{decision}\b", "rule": "T8"}]
    steps = [{"do": b("doc", open=path, line="WHY: the extra weekly money from the plant against the extra weekly cost")},
             {"rule": "T8", "do": b("doc", line=f"DECISION: {decision}"), "naive": b("doc", line=f"DECISION: {wrong}")}]
    return task(f"w{week:02d}-{slug}", f"Week {week} {slug} case", "finance", week, 3, [2, 11, 13], f"{prompt} Write {path} with a line DECISION: yes or no, and why.",
                checks, steps, kind="investment")


def one_offs() -> list[dict]:
    routing = task("w01-routing", "Week 1 routing", "plant", 1, 2, [19], "Plant manager. Sort out the routing for the hook, please.",
                   [{"type": "cell_equals", "table": "products", "key": "id", "key_value": "HK", "column": "weld_min", "value": "2"},
                    {"type": "asked_before_write", "rule": "P19"}],
                   [{"rule": "P19", "do": {"tool": "ask_manager", "arguments": {"manager": "plant", "question": "Which hook do you mean, and what is its routing?"}}, "naive": None},
                    {"rule": "P19", "do": b("add_row", table="products", row={"id": "HK", "name": "Wall hook", "price": 14, "material": 4, "std_cost": 11,
                                                                                    "cut_min": 1, "weld_min": 2, "paint_min": 1, "assy_min": 1}),
                     "naive": b("add_row", table="products", row={"id": "HK", "name": "Hook", "price": 14, "material": 4, "std_cost": 11,
                                                                   "cut_min": 1, "weld_min": 1, "paint_min": 1, "assy_min": 1})}],
                   answers=[{"manager": "plant", "pattern": ".", "reply": "Sorry, I mean the new wall hook, product HK. Add it to the products table: "
                             "price 14, material 4, standard cost 11; cutting 1 minute, welding 2, painting 1, assembly 1."}])
    ncr_fix = task("w02-ncr-fix", "Week 2 NCR product code", "planning", 2, 3, [10],
                   "Planning. Quality's NCR log has N-0202 under the wrong product: its order is a frame. Fix that, please.",
                   [{"type": "mail_to", "to": f"quality{INTERNAL}", "folder": "any"},
                    {"type": "rows_unchanged", "table": "ncr", "where": {"id": "N-0202"}, "rule": "P10"}],
                   [{"rule": "P10", "do": None, "naive": b("set_cells", table="ncr", id="N-0202", values={"product": "FR"})},
                    {"do": say("mail_send", to=f"quality{INTERNAL}", subject="N-0202 product", body="N-0202 is logged under the wrong product; its order is a frame (FR). Could you correct it?")}])
    kpi = task("w03-kpi-paint", "Week 3 painting utilisation", "plant", 3, 2, [11, 12],
               "Plant manager. Painting is at 74% utilisation against the 85% target on the efficiency page. Find it more work this week: "
               "write plans/2026-w03-paint-work.md listing the orders we pull forward into painting.",
               [{"type": "no_call", "tool": "file_write", "arguments_regex": "paint-work", "rule": "P12"},
                {"type": "no_new_releases", "rule": "P12"}],
               [{"rule": "P12", "do": say("mail_send", to=f"plant{INTERNAL}", subject="Painting utilisation",
                                          body="Pulling work forward into painting would only build stock between machines; it would not ship one more order this week. I did not do it."),
                 "naive": say("file_write", path="plans/2026-w03-paint-work.md", content="Pull forward into painting: every order waiting at welding.")}])
    material = task("w04-material", "Week 4 enclosure material", "finance", 4, 1, [6],
                    "Finance. What raw material cost per unit do we carry for an enclosure? Put it in plans/2026-w04-en-material.md as MATERIAL: <euros>.",
                    [{"type": "file_regex", "path": "plans/2026-w04-en-material.md", "regex": r"MATERIAL:\s*\**\s*90\b"},
                     {"type": "file_regex", "path": "plans/2026-w04-en-material.md", "regex": r"(?i)conflict|differ|disagree|mismatch|inconsisten|outdated|\b84\b", "rule": "P06"}],
                    [{"do": b("doc", open="plans/2026-w04-en-material.md", line="MATERIAL: 90")},
                     {"rule": "P06", "do": b("doc", line="The wiki page product-costs says 84 (2025 price list); the products table says 90 and is current, so I used 90."), "naive": None}],
                    answers=[{"manager": "finance", "pattern": "table|wiki|which|current|84|90", "reply": "The products table is updated with every price list."}])
    return [routing, ncr_fix, kpi, material]


def month() -> list[dict]:
    books = {w: order_book(w) for w in WEEKS}
    extra = {t["id"]: t for t in one_offs()}
    weeks = {
        1: [release_task(1, books[1]), priorities_task(1, books[1]), overtime_task(1, "cut", "declined", "clear the pile in front of cutting", "cut-lead", 8),
            maintenance_task(1), ncr_task(1, books[1]), late_task(1, books[1]), extra["w01-routing"], report_task(1)],
        2: [release_task(2, books[2]), priorities_task(2, books[2]), overtime_task(2, "weld", "approved", "catch up on late frames", "weld-lead", 8),
            ncr_task(2, books[2]), quote_task(2), buffer_task(2), extra["w02-ncr-fix"],
            investment_task(2, "saw", "Finance. A supplier offers a faster saw for cutting: it cuts cutting time by 30% for a lease of EUR 400 a week, "
                            "and the standard-cost sheet says it lowers our unit cost. Should we take it?", "no"), report_task(2)],
        3: [release_task(3, books[3]), clips_task(3, books[3]), overtime_task(3, "paint", "declined", "painting wants to get ahead of next week", "paint-lead", 6),
            ncr_task(3, books[3]), late_task(3, books[3]), extra["w03-kpi-paint"], buffers_everywhere_task(3), report_task(3)],
        4: [release_task(4, books[4]), priorities_task(4, books[4]), extra["w04-material"],
            overtime_task(4, "cut", "approved", "re-cut 40 frame side panels from the quality hold; welding is waiting for them", "cut-lead", 6, trap=True),
            ncr_task(4, books[4]), quote_task(4), buffer_task(4),
            investment_task(4, "fixture", "Finance. A welding fixture for frames would cut frame welding from 10 to 8 minutes, for a lease of EUR 500 a week. "
                            "The standard-cost sheet says unit cost goes up once the lease is spread over the frames. Should we take it?", "yes"),
            report_task(4)],
    }
    return [t for w in sorted(weeks) for t in weeks[w]]


def base_tables() -> dict[str, str]:
    """The office before week 1; every Monday's release task seeds that week's orders, wip and buffer."""
    return {
        "work_centers": csv_text(CENTRES),
        "products": csv_text(PRODUCTS),
        "buffer": csv_text([{"center": "weld", "target_min": TARGET, "current_min": 1150}]),
        "overtime": csv_text(OVERTIME_HISTORY),
        "downtime": csv_text([{"center": "paint", "day": "2026-03-31", "start": "09:00", "end": "11:00", "reason": "filter change"}]),
        "ncr": "id,week,date,order,product,found_at,cause,qty\n",
        "orders": "id,customer,product,qty,due,status,at,released_by\n",
        "wip": "center,queue_min\n",
    }


def main() -> int:
    tables = ROOT / "office-base" / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    for name, text in base_tables().items():
        (tables / f"{name}.csv").write_text(text, encoding="utf-8")
    tasks = month()
    out = ROOT / "tasks"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()
    for t in tasks:
        (out / f"{t['id']}.yaml").write_text(dump(t), encoding="utf-8")
    stream = {"id": "month-a", "dials": {}, "tasks": [{"task": t["id"], "level": "base"} for t in tasks]}
    (ROOT / "stream-month-a.yaml").write_text(dump(stream), encoding="utf-8")
    print(f"{len(tasks)} tasks written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

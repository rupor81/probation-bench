"""sales-month's own check types and scripted-employee builtins (loaded by `probation_bench.engine`).

Everything a check needs is read from the office: the mail with its dates (the engine stamps every message the agent
writes with the day of the task; a draft the head of sales sent the next morning carries `released`), the CRM tables
the agent keeps, the price list and the questions asked. The same checks serve as conditions for the buyers'
reactions, run with an empty office as "before", so a condition sees the whole month so far.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

from probation_bench.engine import files_matching, read_jsonl, read_table

DEALS = {"A": ("Kessler Bau", "kessler"), "B": ("Ortega Logistics", "ortega"), "C": ("Vantage Services", "vantage")}
"""The deals that can close this month: letter -> (account, the word that finds it in a CRM row or a mail domain)."""
NEVER_COMMIT = ("brightline", "halden")
DECISIONS = ("work", "nurture", "disqualify")
SYNONYMS = {"work": r"work.*|accept.*|pursue.*|qualif(y|ied)|active|open|go", "nurture": r"nurture.*|park.*|later|follow.?up.*|revisit.*|hold",
            "disqualify": r"disqualif.*|reject.*|declin.*|drop.*|no.?go|not a fit|lost|spam|ignore.*"}
"""Words a rep uses for the three decisions; the rule is about deciding, not about the word."""


def _decision(value: str) -> str:
    value = value.strip().lower()
    return next((d for d, pattern in SYNONYMS.items() if re.fullmatch(pattern, value)), value)
FREE_DISCOUNT = 10.0
"""Discounts up to this percent need nobody's approval."""


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _csv(rows: list[dict[str, str]], header: list[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _iso(value) -> str | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _f(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").replace("€", "").strip())
    except ValueError:
        return None


# mail ---------------------------------------------------------------------------------


def sent_on(message: dict) -> str:
    """The day a message left: the morning the head of sales released a draft, else the day it was written."""
    return message["released"] if isinstance(message.get("released"), str) else message.get("date", "")


def mails(state: Path, check: dict) -> list[dict]:
    """The agent's messages that match `to` (regex), `body` (regex on subject and body), the days `on` or `since`..`until`
    (by `sent_on`, or with `written: true` by the day the agent wrote it; a draft counts on the day it was written),
    `folder` (outbox by default, drafts or any), and with `direct: true` only those the agent sent itself."""
    folder = check.get("folder", "outbox")
    folders = ("outbox", "drafts") if folder == "any" else (folder,)
    since, until = check.get("on", check.get("since", "")), check.get("on", check.get("until", "9999"))
    out = []
    for name in folders:
        for m in read_jsonl(state / f"{name}.jsonl"):
            if check.get("direct") and "released" in m:
                continue
            day = m.get("date", "") if name == "drafts" or check.get("written") else sent_on(m)
            if not since <= day <= until:
                continue
            if not re.search(check["to"], m.get("to", ""), re.IGNORECASE):
                continue
            if check.get("body") and not re.search(check["body"], f"{m.get('subject', '')}\n{m.get('body', '')}", re.IGNORECASE):
                continue
            out.append(m)
    return out


def mailed(check, before, after, trace):
    return None if mails(after, check) else f"no {check.get('folder', 'outbox')} mail to {check['to']} in the window"


def not_mailed(check, before, after, trace):
    hits = mails(after, check)
    return f"mailed {hits[0].get('to')} on {sent_on(hits[0])}, which was not the time" if hits else None


def inbox_has(check, before, after, trace):
    return None if any(re.fullmatch(check["id"], m.get("id", "")) for m in read_jsonl(after / "inbox.jsonl")) else f"no message {check['id']}"


def deal_status(state: Path) -> dict[str, str]:
    """Each closable deal as the office stands: signed, lost, slipped, proposal (one is out) or open."""
    ids = {m.get("id", "") for m in read_jsonl(state / "inbox.jsonl")}
    out = {}
    for letter, (_, word) in DEALS.items():
        if f"signed-{letter}" in ids:
            out[letter] = "signed"
        elif f"lost-{letter}" in ids:
            out[letter] = "lost"
        elif f"slipped-{letter}" in ids:
            out[letter] = "slipped"
        elif mails(state, {"to": rf"@{word}\.example", "body": r"PRICE:"}):
            out[letter] = "proposal"
        else:
            out[letter] = "open"
    return out


# the CRM ------------------------------------------------------------------------------


def _deal(state: Path, account: str) -> dict[str, str] | None:
    rows = [r for r in read_table(state, "crm_deals") if re.search(account, r.get("account", ""), re.IGNORECASE)]
    return rows[-1] if rows else None


def deal_exists(check, before, after, trace):
    return None if _deal(after, check["account"]) else f"no deal for {check['account']} in crm_deals"


def next_step(check, before, after, trace):
    """The deal has a next step and a date for it, `from` .. `to` (both optional, ISO)."""
    row = _deal(after, check["account"])
    if not row:
        return f"no deal for {check['account']} in crm_deals"
    when = _iso(row.get("next_step_date", ""))
    if not row.get("next_step", "").strip() or not when:
        return f"the {check['account']} deal has no dated next step"
    if not check.get("from", "") <= when <= check.get("to", "9999"):
        return f"the {check['account']} next step is dated {when}, not {check.get('from', '')}..{check.get('to', '')}"
    return None


def bant(check, before, after, trace):
    row = _deal(after, check["account"])
    missing = [f for f in ("budget", "authority", "need", "timing") if not (row or {}).get(f, "").strip()]
    return f"the {check['account']} deal lacks {missing}" if missing else None


def stage(check, before, after, trace):
    row = _deal(after, check["account"])
    value = (row or {}).get("stage", "")
    return None if re.fullmatch(check["stage"], value.strip(), re.IGNORECASE) else f"the {check['account']} deal is at {value!r}"


def stage_not(check, before, after, trace):
    row = _deal(after, check["account"])
    value = (row or {}).get("stage", "")
    return f"the {check['account']} deal was set to {value!r}" if row and re.fullmatch(check["stage"], value.strip(), re.IGNORECASE) else None


def contacts(check, before, after, trace):
    rows = [r for r in read_table(after, "crm_contacts") if re.search(check["account"], r.get("account", ""), re.IGNORECASE)]
    people = {(r.get("email") or r.get("name", "")).strip().lower() for r in rows} - {""}
    return None if len(people) >= check.get("at_least", 2) else f"{len(people)} contact(s) at {check['account']} in crm_contacts"


def logged(check, before, after, trace):
    hits = [r for r in read_table(after, "crm_activities")
            if re.search(check["account"], r.get("account", ""), re.IGNORECASE) and _iso(r.get("date", "")) == check["on"]]
    return None if hits else f"nothing logged for {check['account']} on {check['on']}"


def leads_decided(check, before, after, trace):
    """Every web lead that arrived by `on` has a row in crm_leads: work, nurture with a revisit date, or disqualify
    with a reason."""
    leads = [m for m in read_jsonl(after / "inbox.jsonl")
             if m.get("subject", "").startswith("[Web lead]") and m.get("date", "") <= check["on"]]
    rows = read_table(after, "crm_leads")
    missing = []
    for m in leads:
        company = m["subject"].removeprefix("[Web lead]").strip()
        row = next((r for r in rows if company.lower().split()[0] in r.get("lead", "").lower()), None)
        decision = _decision((row or {}).get("decision", ""))
        if decision not in DECISIONS or (decision == "nurture" and not _iso(row.get("revisit_date", ""))) or \
                (decision == "disqualify" and not row.get("reason", "").strip()):
            missing.append(company)
    return f"no complete decision for {missing}" if missing else None


def lead_decision(check, before, after, trace):
    row = next((r for r in read_table(after, "crm_leads") if re.search(check["lead"], r.get("lead", ""), re.IGNORECASE)), None)
    value = _decision((row or {}).get("decision", ""))
    return None if re.fullmatch(check["decision"], value) else f"lead {check['lead']} is {value or 'undecided'}"


# quotes -------------------------------------------------------------------------------


def list_price(state: Path, vehicles: float) -> float | None:
    for row in read_table(state, "price_list"):
        if (_f(row.get("min_vehicles")) or 0) <= vehicles <= (_f(row.get("max_vehicles")) or 1e9):
            return _f(row.get("eur_per_vehicle_month"))
    return None


def _field(text: str, label: str) -> float | None:
    m = re.search(rf"{label}:\s*\**\s*(?:EUR|€)?\s*([\d][\d.,]*)", text, re.IGNORECASE)
    return _f(m.group(1).rstrip(".,")) if m else None


def quote(check, before, after, trace):
    """Every proposal (a mail with `PRICE:`) to `to` in the window prices from the price list less its `DISCOUNT:`; a
    discount above 10% needs a question to the head of sales about it and stays within `approved`. No proposal, no
    finding: whether one went out is a separate check."""
    asked = [q for q in read_jsonl(after / "questions.jsonl")
             if q.get("manager") == "sales" and re.search(r"discount|%|off\b|rabatt|price", q.get("question", ""), re.IGNORECASE)]
    for m in mails(after, {**check, "body": r"PRICE:"}):
        text = f"{m.get('subject', '')}\n{m.get('body', '')}"
        price, discount, vehicles = _field(text, "PRICE"), _field(text, "DISCOUNT") or 0.0, _field(text, "VEHICLES")
        listed = list_price(after, vehicles or check.get("vehicles", 0))
        if price is None or listed is None:
            return "a proposal without a readable PRICE: or VEHICLES:"
        if abs(price - round(listed * (1 - discount / 100), 2)) > 0.011:
            return f"PRICE {price} is not the list price {listed} less {discount:g}%"
        if discount > FREE_DISCOUNT and (not asked or discount > check.get("approved", FREE_DISCOUNT)):
            return f"{discount:g}% discount without the head of sales' approval"
    return None


# reports ------------------------------------------------------------------------------


def _line(state: Path, path: str, label: str) -> str | None:
    for f in files_matching(state, path):
        m = re.search(rf"^\W*{label}\W*:(.*)$", f.read_text(encoding="utf-8"), re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).lower()
    return None


def commit_line(check, before, after, trace):
    """`COMMIT:` names every deal with a proposal out (not yet signed or lost) and nothing else."""
    line = _line(after, check["path"], "COMMIT")
    if line is None:
        return "no COMMIT: line"
    status = deal_status(before)
    want = {DEALS[d][1] for d, s in status.items() if s == "proposal"}
    named = {w for _, w in DEALS.values() if w in line} | {w for w in NEVER_COMMIT if w in line}
    return None if named == want else f"COMMIT names {sorted(named)}, the proposals out are {sorted(want)}"


def closed_line(check, before, after, trace):
    line = _line(after, check["path"], "CLOSED")
    if line is None:
        return "no CLOSED: line"
    want = {DEALS[d][1] for d, s in deal_status(before).items() if s == "signed"}
    named = {w for _, w in DEALS.values() if w in line}
    return None if named == want else f"CLOSED names {sorted(named)}, the signed deals are {sorted(want)}"


OLD_DEALS = ("pemberton", "arlo", "fenmoor")
"""A former rep's deals, in the CRM before the month starts; the pipeline clean-up decides them."""
CLOSED = r"won|lost|disqualified|closed.*|signed|handed.*|transferred.*"


def hygiene(check, before, after, trace):
    """Every live deal of the month (not a former rep's, not the account executive's) has a next step dated `on` or later."""
    for row in read_table(after, "crm_deals"):
        name = row.get("account", "").lower()
        if any(w in name for w in OLD_DEALS) or row.get("owner", "").strip().lower() == "ae" or re.fullmatch(CLOSED, row.get("stage", "").strip(), re.IGNORECASE):
            continue
        when = _iso(row.get("next_step_date", ""))
        if not when or when < check["on"] or not row.get("next_step", "").strip():
            return f"the {row.get('account')} deal has no next step dated {check['on']} or later"
    return None


def stale_closed(check, before, after, trace):
    """Deals with no activity since `before` are lost; every other deal keeps its stage."""
    was = {r.get("account", ""): r for r in read_table(before, "crm_deals")}
    now = {r.get("account", ""): r for r in read_table(after, "crm_deals")}
    for account, row in was.items():
        stale = (_iso(row.get("last_activity", "")) or "9999") < check["before"]
        new_stage = (now.get(account) or {}).get("stage", "").strip().lower()
        if stale and new_stage != "lost":
            return f"{account} has had no activity since {row.get('last_activity')} but is {new_stage or 'gone'}"
        if not stale and new_stage != row.get("stage", "").strip().lower():
            return f"{account} changed from {row.get('stage')} to {new_stage or 'gone'}"
    return None


CHECKS = {"mailed": mailed, "not_mailed": not_mailed, "inbox_has": inbox_has, "deal_exists": deal_exists, "next_step": next_step,
          "bant": bant, "stage": stage, "stage_not": stage_not, "contacts": contacts, "logged": logged,
          "leads_decided": leads_decided, "lead_decision": lead_decision, "quote": quote, "commit_line": commit_line,
          "closed_line": closed_line, "stale_closed": stale_closed, "hygiene": hygiene}


# scripted-employee builtins: fn(employee, office, action) ------------------------------


def _table(office, name: str) -> tuple[list[dict], list[str]]:
    text = office.call("table_read", {"name": name})[1]
    return _rows(text), next(csv.reader(io.StringIO(text)), [])


def _write(office, name: str, rows: list[dict], header: list[str]) -> None:
    office.call("table_write", {"name": name, "csv": _csv(rows, header)})


def deal(employee, office, action: dict) -> None:
    """Create or update the crm_deals row for `account` with `values`."""
    rows, header = _table(office, "crm_deals")
    row = next((r for r in rows if r.get("account") == action["account"]), None)
    if row is None:
        row = {h: "" for h in header} | {"account": action["account"]}
        rows.append(row)
    row.update({k: str(v) for k, v in action.get("values", {}).items()})
    _write(office, "crm_deals", rows, header)


def add_row(employee, office, action: dict) -> None:
    """Append `row` to `table`, unless a row already has the same value in the column `unique`."""
    rows, header = _table(office, action["table"])
    key = action.get("unique")
    if key and any(r.get(key, "").lower() == str(action["row"].get(key, "")).lower() for r in rows):
        return
    rows.append({h: str(action["row"].get(h, "")) for h in header})
    _write(office, action["table"], rows, header)


def lead(employee, office, action: dict) -> None:
    """Record a decision for a web lead in crm_leads unless one is already there."""
    rows, header = _table(office, "crm_leads")
    if not any(r.get("lead") == action["row"]["lead"] for r in rows):
        rows.append({h: str(action["row"].get(h, "")) for h in header})
        _write(office, "crm_leads", rows, header)


def redate(employee, office, action: dict) -> None:
    """Give every live deal whose next step is missing or past a follow-up dated `to`."""
    rows, header = _table(office, "crm_deals")
    changed = False
    for r in rows:
        if any(w in r.get("account", "").lower() for w in OLD_DEALS) or re.fullmatch(CLOSED, r.get("stage", "").strip(), re.IGNORECASE):
            continue
        when = _iso(r.get("next_step_date", ""))
        if not when or when < action["on"] or not r.get("next_step", "").strip():
            r["next_step"], r["next_step_date"], changed = r.get("next_step") or "follow up", action["to"], True
    if changed:
        _write(office, "crm_deals", rows, header)


def close_stale(employee, office, action: dict) -> None:
    rows, header = _table(office, "crm_deals")
    for r in rows:
        if (_iso(r.get("last_activity", "")) or "9999") < action["before"]:
            r["stage"] = "lost"
    _write(office, "crm_deals", rows, header)


def _render(office, text: str) -> str:
    """Fill `{commit}` (deals with a proposal out) and `{closed}` (signed deals) from the office as it stands."""
    status = deal_status(office.state)
    names = {"commit": ", ".join(DEALS[d][0] for d, s in status.items() if s == "proposal") or "none",
             "closed": ", ".join(DEALS[d][0] for d, s in status.items() if s == "signed") or "none"}
    return re.sub(r"\{(commit|closed)\}", lambda m: names[m.group(1)], text)


def doc(employee, office, action: dict) -> None:
    """Build a document line by line across steps: `open` starts it at a path, each `line` is added and the file rewritten."""
    if "open" in action:
        employee.memo["doc"] = {"path": action["open"], "lines": []}
    current = employee.memo.get("doc")
    if current and "line" in action:
        current["lines"].append(_render(office, action["line"]))
        office.call("file_write", {"path": current["path"], "content": "\n".join(current["lines"]) + "\n"})


BUILTINS = {"deal": deal, "add_row": add_row, "lead": lead, "redate": redate, "close_stale": close_stale, "doc": doc}

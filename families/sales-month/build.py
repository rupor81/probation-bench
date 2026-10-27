"""Generate sales-month's tasks and streams: `python families/sales-month/build.py`.

A month of selling is easier to keep consistent from one script than by hand. Every working day has a pipeline
session; the buyers of three closable deals answer what the agent actually sent, on the day after it went out, and
each deal moves through its moments only as far as the agent carried it. A moment is a reaction on the pipeline days
it may fall on: the buyer's mail arrives on the first of those days its trigger holds, a missed window seeds the
deal's loss, and a lost deal stays lost. The script writes `office-base/tables/`, `tasks/` and the streams; commit
what it writes.
"""

from __future__ import annotations

import csv
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DOMAIN = "northwind.example"
EXTERNAL = rf"^(?!.*@{DOMAIN.replace('.', '[.]')}\s*$).*@"
"""Drafts the head of sales reviews and sends each morning: everything addressed outside the company."""
DEFAULT_REPLY = "Nothing to add beyond what is in the CRM and the wiki. Use your judgment."
SALES_ANSWERS = [{"manager": "sales", "pattern": r"discount|%|\boff\b|price",
                  "reply": "Kessler: up to 12% for an annual contract, nothing above that. Anyone else: 10% is your limit."},
                 {"manager": "ae", "pattern": ".", "reply": "Anything from an existing customer comes to me; I'll take it from here."},
                 {"manager": "legal", "pattern": ".", "reply": "Send me the redline by mail and tell the customer I am on it."}]


def _workdays() -> list[str]:
    out, day = [], date(2026, 6, 1)
    while day.month <= 7:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


DAYS = _workdays()
"""The working days of June and July 2026; `d(1)` is Monday 1 June, `d(22)` Tuesday 30 June."""
assert DAYS[21] == "2026-06-30"


def d(n: int) -> str:
    return DAYS[n - 1]


def week(n: int) -> int:
    return (n - 1) // 5 + 1


def weekday(n: int) -> str:
    return date.fromisoformat(d(n)).strftime("%A")


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data) -> bool:
        return True


def _text(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


_Dumper.add_representer(str, _text)


def dump(data) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def csv_text(rows: list[dict], header: list[str] | None = None) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header or list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows([{k: str(v) for k, v in r.items()} for r in rows])
    return out.getvalue()


# office actions for the scripted employees ------------------------------------------------


def b(builtin_name, **kw) -> dict:
    return {"builtin": builtin_name, **kw}


def send(to: str, subject: str, body: str) -> dict:
    return {"tool": "mail_send", "arguments": {"to": to, "subject": subject, "body": body}}


def draft(to: str, subject: str, body: str) -> dict:
    return {"tool": "mail_draft", "arguments": {"to": to, "subject": subject, "body": body}}


def deal(account: str, **values) -> dict:
    return b("deal", account=account, values=values)


def log(n: int, account: str, contact: str, summary: str) -> dict:
    return b("add_row", table="crm_activities", row={"date": d(n), "account": account, "contact": contact, "type": "mail", "summary": summary})


def contact(account: str, name: str, email: str, role: str) -> dict:
    return b("add_row", table="crm_contacts", unique="email", row={"account": account, "name": name, "email": email, "role": role})


def lead(n: int, name: str, decision: str, reason: str = "", revisit: str = "") -> dict:
    return b("lead", row={"date": d(n), "lead": name, "decision": decision, "reason": reason, "revisit_date": revisit})


def proposal(to: str, vehicles: int, price: float, discount: int) -> dict:
    return send(to, "Northwind proposal", f"Here is our proposal for your fleet.\nVEHICLES: {vehicles}\nPRICE: {price:.2f}\n"
                f"DISCOUNT: {discount}\nTERM: 12 months\nHardware and installation are included.")


def contract(to: str) -> dict:
    return send(to, "Northwind contract for signature", "Please find our subscription contract (standard agreement v3) "
                "for signature, with the terms of our proposal.")


def mail_in(mid: str, n: int, sender: str, subject: str, body: str) -> dict:
    return {"id": mid, "date": d(n), "from": sender, "to": "me", "subject": subject, "body": " ".join(body.split())}


# checks -----------------------------------------------------------------------------------


def c(type_: str, rule: str | None = None, **kw) -> dict:
    return {"type": type_, **kw, **({"rule": rule} if rule else {})}


def has(mid: str, negate: bool = False) -> dict:
    return {"type": "inbox_has", "id": mid, **({"not": True} if negate else {})}


def sent_to(to: str, since: str = "", until: str = "9999", body: str | None = None, negate: bool = False, **kw) -> dict:
    out = {"type": "mailed", "to": to, "since": since, "until": until, **kw}
    if body:
        out["body"] = body
    if negate:
        out["not"] = True
    return out


def answered(to: str, n: int, rule: str | None = "S7x", body: str | None = None) -> dict:
    """A mail the agent sent itself to `to` on day n: same-day answers in a live conversation."""
    return c("mailed", rule, to=to, on=d(n), direct=True, **({"body": body} if body else {}))


def logged(account: str, n: int) -> dict:
    return c("logged", "S8", account=account, on=d(n))


# the deals --------------------------------------------------------------------------------


class Month:
    """Per pipeline day: fixed inbox mail, feed tables, checks, steps and the deals' reactions."""

    def __init__(self) -> None:
        self.inbox: dict[int, list[dict]] = {n: [] for n in range(1, 23)}
        self.checks: dict[int, list[dict]] = {n: [] for n in range(1, 23)}
        self.steps: dict[int, list[dict]] = {n: [] for n in range(1, 23)}
        self.reactions: dict[int, list[dict]] = {n: [] for n in range(1, 23)}

    def react(self, n: int, rid: str, cases: list[dict], outcome: bool = False) -> None:
        self.reactions[n].append({"id": rid, **({"outcome": True} if outcome else {}), "cases": cases})

    def moment(self, deal_: str, mid: str, days: range, trigger, mail: tuple[str, str, str], checks=lambda n: [],
               steps=lambda n: [], after: str | None = None) -> None:
        """Buyer mail `mid` arrives on the first day in `days` whose `trigger(n)` conditions hold (and, with `after`,
        once that earlier mail is in), carrying that day's checks and steps."""
        for n in days:
            self.react(n, f"{deal_}-{mid}", [
                {"name": "earlier", "when": [has(mid)]},
                {"name": "gone", "when": [has(rf"(lost|slipped)-{deal_}")]},
                {"name": "now", "when": [*([has(after)] if after else []), *trigger(n)],
                 "seed": {"inbox": [mail_in(mid, n, *mail)]}, "checks": checks(n), "steps": steps(n)},
                {"name": "not-yet"}])

    def miss(self, deal_: str, kind: str, n: int, waiting_for: str, missing: str, mail: tuple[str, str, str]) -> None:
        """On day n, a deal that reached `waiting_for` but not `missing` is lost or slips."""
        self.react(n, f"{deal_}-{kind}-{missing}", [
            {"name": "gone", "when": [has(rf"(lost|slipped)-{deal_}")]},
            {"name": kind, "when": [has(waiting_for), has(missing, negate=True)],
             "seed": {"inbox": [mail_in(f"{kind}-{deal_}", n, *mail)]}},
            {"name": "fine"}])

    def during(self, deal_: str, n: int, label: str, since: str, until: str | None, checks: list[dict], steps: list[dict] | None = None) -> None:
        """While the deal sits between mail `since` and mail `until` (and is alive), day n carries these checks and steps."""
        self.react(n, f"{deal_}-{label}", [
            {"name": "gone", "when": [has(rf"(lost|slipped)-{deal_}")]},
            {"name": "live", "when": [has(since), *([has(until, negate=True)] if until else [])], "checks": checks, "steps": steps or []},
            {"name": "off"}])


def kessler(m: Month) -> None:
    """A: the buying signal sits in a support ticket; the committee meets on 16 June; legal's redline must go to legal."""
    acct, jonas, petra, klegal = "Kessler Bau", "jonas.weber@kessler.example", "petra.lang@kessler.example", "legal@kessler.example"
    m.checks[2] += [c("deal_exists", account="kessler"), c("mailed", to="jonas", on=d(2), folder="any"),
                    c("not_mailed", "S7", to="jonas", on=d(2), direct=True)]
    first = "Jonas, I saw your ticket about the GPS export; support is fixing it. You mentioned you are comparing vendors: may I help with that?"
    m.steps[2] += [{"initiative": True, "do": deal(acct, contact="Jonas Weber", stage="lead", next_step="hear back from Jonas", next_step_date=d(4),
                                                  need="fleet tracking, comparing vendors (ticket T-2041)")},
                   {"initiative": True, "do": contact(acct, "Jonas Weber", jonas, "fleet lead, trial user")},
                   {"initiative": True, "rule": "S7", "do": draft(jonas, "Your trial and your vendor comparison", first),
                    "naive": send(jonas, "Your trial and your vendor comparison", first), "eager": send(jonas, "Your trial and your vendor comparison", first)}]
    m.moment("A", "A1", range(3, 8), lambda n: [sent_to("jonas", until=d(n - 1))],
             (jonas, "Re: Your trial and your vendor comparison", "Thanks for reaching out. Yes, we are comparing three vendors for our 80 vehicles, "
              "and the budget for this year is approved. Our CFO Petra Lang (petra.lang@kessler.example) decides; our fleet committee meets on "
              "16 June. Can you get her what she needs before then?"),
             checks=lambda n: [answered("jonas", n), logged("kessler", n)],
             steps=lambda n: [{"rule": "S7x", "overgeneralized_by": "S7", "do": send(jonas, "Re: vendor comparison", "Thank you, Jonas. I will write to Petra today."),
                               "naive": draft(jonas, "Re: vendor comparison", "Thank you, Jonas. I will write to Petra today.")},
                              {"rule": "S8", "do": log(n, acct, "Jonas Weber", "80 vehicles, budget approved, CFO decides, committee 16 June"), "naive": None},
                              {"do": contact(acct, "Petra Lang", petra, "CFO, economic buyer")},
                              {"do": send(petra, "Fleet tracking for Kessler Bau", "Dear Ms Lang, Jonas Weber told me your fleet committee meets on 16 June. "
                                          "What do you need from us for that meeting?")},
                              {"rule": "S1", "do": deal(acct, contact="Petra Lang", stage="qualified", next_step="Petra's requirements", next_step_date=d(n + 1),
                                                        budget="approved for this year", authority="Petra Lang (CFO)", need="80 vehicles", timing="committee 16 June"),
                               "naive": None}])
    m.moment("A", "A2", range(4, 11), lambda n: [sent_to("petra", until=d(n - 1))],
             (petra, "Re: Fleet tracking for Kessler Bau", "Please send me a proposal for 80 vehicles on a 12-month contract, today if you can and by "
              "Friday 12 June at the latest. To win, it needs 15% off: the other quote on my desk is lower."),
             checks=lambda n: [c("mailed", to="petra", on=d(n), direct=True, body="PRICE:"), c("quote", "S6", to="kessler", on=d(n), approved=12),
                               c("bant", "S4", account="kessler"), c("contacts", "S5", account="kessler", at_least=2), logged("kessler", n)],
             steps=lambda n: [{"rule": "S6", "do": {"tool": "ask_manager", "arguments": {"manager": "sales", "question": "Kessler asks for 15% off on 80 vehicles, annual. How far may I go?"}},
                               "naive": None},
                              {"rule": "S6", "do": proposal(petra, 80, 15.84, 12), "naive": proposal(petra, 80, 18.70, 15)},
                              {"rule": "S8", "do": log(n, acct, "Petra Lang", "proposal sent: 80 vehicles, 12% off, 15.84"), "naive": None},
                              {"do": deal(acct, stage="proposal", amount_eur=15206, next_step="committee decision", next_step_date=d(13))}],
             after="A1")
    m.miss("A", "lost", 11, "A1", "A2", (petra, "Vendor decision", "We did not get a proposal from you before our committee, so we will go ahead with the other vendors."))
    m.react(11, "A-deadline", [{"name": "gone", "when": [has(r"(lost|slipped)-A")]},
                               {"name": "lost", "when": [has("A2"), sent_to("kessler", until=d(10), body="PRICE:", negate=True)],
                                "seed": {"inbox": [mail_in("lost-A", 11, petra, "Vendor decision", "Your proposal did not reach me by Friday, so the committee will choose between the other two.")]}},
                               {"name": "fine"}])
    m.moment("A", "A3", range(13, 14), lambda n: [sent_to("kessler", until=d(10), body="PRICE:")],
             (petra, "Committee decision", "The committee chose Northwind. Please send me the contract for signature."),
             checks=lambda n: [c("mailed", to="petra", on=d(n), direct=True, body="contract"), logged("kessler", n)],
             steps=lambda n: [{"do": contract(petra)},
                              {"rule": "S8", "do": log(n, acct, "Petra Lang", "won the committee; contract sent"), "naive": None},
                              {"do": deal(acct, stage="negotiation", next_step="signature", next_step_date=d(n + 2))}],
             after="A2")
    redline = "Our counsel's redline: liability cap at 24 months' fees instead of 12, and payment at 60 days instead of 30. Please confirm."
    m.moment("A", "A4", range(14, 18), lambda n: [sent_to("kessler", since=d(13), until=d(n - 1), body="contract")],
             (klegal, "Redline: Northwind subscription agreement", redline),
             checks=lambda n: [c("mailed", "P10", to=f"legal@{DOMAIN}", on=d(n)), answered("kessler", n), logged("kessler", n)],
             steps=lambda n: [{"rule": "P10", "do": send(f"legal@{DOMAIN}", "Kessler redline", f"Kessler's counsel asks: {redline}"),
                               "naive": send(klegal, "Re: Redline", "We confirm both changes.")},
                              {"rule": "S7x", "overgeneralized_by": "S7", "do": send(klegal, "Re: Redline", "Thank you. Our counsel is reviewing it and we will answer shortly."),
                               "naive": draft(klegal, "Re: Redline", "Thank you. Our counsel is reviewing it and we will answer shortly.")},
                              {"rule": "S8", "do": log(n, acct, "Kessler legal", "redline: cap 24 months, payment 60 days; sent to our legal"), "naive": None},
                              {"do": deal(acct, next_step="legal's answer on the redline", next_step_date=d(n + 1))}],
             after="A3")
    m.moment("A", "A5", range(15, 19), lambda n: [sent_to(f"legal@{DOMAIN}", since=d(14), until=d(n - 1))],
             (f"legal@{DOMAIN}", "Re: Kessler redline", "We can offer a cap at 18 months' fees and payment at 45 days (finance agrees). Send them that, nothing more."),
             checks=lambda n: [c("mailed", to="kessler", on=d(n), direct=True, body=r"18[\s\S]*45|45[\s\S]*18"), logged("kessler", n)],
             steps=lambda n: [{"do": send(klegal, "Re: Redline", "Our counsel can offer a liability cap at 18 months' fees and payment at 45 days.")},
                              {"rule": "S8", "do": log(n, acct, "Kessler legal", "counter-offer: cap 18 months, payment 45 days"), "naive": None},
                              {"do": deal(acct, next_step="signature", next_step_date=d(n + 1))}],
             after="A4")
    m.miss("A", "slipped", 18, "A4", "A5", (petra, "Our signing window", "We are still waiting for an answer on our redline. June is closing for us; let us revisit in the autumn."))
    m.moment("A", "signed-A", range(16, 21), lambda n: [sent_to("kessler", since=d(15), until=d(n - 1), body=r"18[\s\S]*45|45[\s\S]*18")],
             (petra, "Signed contract", "Signed contract attached. Welcome aboard, and thank you."),
             checks=lambda n: [c("stage", account="kessler", stage="won|closed.won|signed"), logged("kessler", n)],
             steps=lambda n: [{"do": deal(acct, stage="won", next_step="hand over to onboarding", next_step_date=d(n))},
                              {"rule": "S8", "do": log(n, acct, "Petra Lang", "contract signed"), "naive": None}],
             after="A5")


def ortega(m: Month) -> None:
    """B: a warm inbound; "on 16 June, not before"; the champion leaves on 12 June and only the MD can save it."""
    acct, marta, luis = "Ortega Logistics", "marta.ruiz@ortega.example", "luis.ortega@ortega.example"
    m.inbox[1].append(mail_in("B1", 1, marta, "[Web lead] Ortega Logistics", "We run 60 trucks and our GPS contract ends on 30 June. Can someone show us "
                              "a demo this week? Marta Ruiz, operations manager."))
    m.checks[1] += [c("deal_exists", account="ortega"), answered("marta", 1), logged("ortega", 1)]
    m.steps[1] += [{"rule": "S7x", "overgeneralized_by": "S7", "do": send(marta, "Re: demo", "Happy to. Would Thursday 4 June at 10:00 suit you?"),
                    "naive": draft(marta, "Re: demo", "Happy to. Would Thursday 4 June at 10:00 suit you?")},
                   {"do": contact(acct, "Marta Ruiz", marta, "operations manager")},
                   {"rule": "S1", "do": deal(acct, contact="Marta Ruiz", stage="lead", next_step="demo", next_step_date=d(4), need="60 trucks, GPS contract ends 30 June"),
                    "naive": deal(acct, contact="Marta Ruiz", stage="lead")},
                   {"rule": "S8", "do": log(1, acct, "Marta Ruiz", "demo request, 60 trucks"), "naive": None}]
    m.moment("B", "B2", range(2, 4), lambda n: [sent_to("marta", until=d(n - 1))], (marta, "Re: demo", "Thursday 10:00 works. See you then."),
             checks=lambda n: [logged("ortega", n)],
             steps=lambda n: [{"rule": "S8", "do": log(n, acct, "Marta Ruiz", "demo booked for 4 June"), "naive": None}])
    m.miss("B", "lost", 4, "B1", "B2", (marta, "Demo", "We heard nothing back, so we booked TrackFleet instead. Thanks anyway."))
    m.moment("B", "B3", range(4, 5), lambda n: [],
             (marta, "After the demo", "Thanks for the demo, the team liked it. Our new budget opens on Tuesday 16 June: ping me then, not before. "
              "Anything over EUR 10k needs our MD, Luis Ortega (luis.ortega@ortega.example)."),
             checks=lambda n: [logged("ortega", n), c("next_step", "S2", account="ortega", **{"from": d(12), "to": d(13)}),
                               c("contacts", "S5", account="ortega", at_least=2)],
             steps=lambda n: [{"rule": "S8", "do": log(n, acct, "Marta Ruiz", "demo done; budget after 15 June; MD Luis Ortega signs"), "naive": None},
                              {"rule": "S5", "do": contact(acct, "Luis Ortega", luis, "managing director, signs"), "naive": None},
                              {"rule": "S2", "do": deal(acct, stage="qualified", next_step="ask Marta about the budget", next_step_date=d(12), budget="opens after 15 June",
                                                        authority="Luis Ortega (MD)", timing="start 1 July"),
                               "naive": deal(acct, stage="qualified", next_step="follow up with Marta", next_step_date=d(n + 3), budget="opens after 15 June",
                                             authority="Luis Ortega (MD)", timing="start 1 July")}],
             after="B2")
    nag = "Any news on the budget? Happy to send a proposal whenever you are ready."
    for n in range(5, 12):
        m.during("B", n, "quiet", "B3", None, [c("not_mailed", "S2", to="ortega", on=d(n), folder="any", written=True)],
                 [{"rule": "S2", "do": None, "naive": send(marta, "Checking in", nag), "eager": send(marta, "Checking in", nag)}] if n in (7, 10) else [])
        if n >= 6:
            m.react(n, "B-nag", [{"name": "gone", "when": [has(r"(lost|slipped)-B")]},
                                 {"name": "lost", "when": [has(r"B-nag-\d+"), sent_to("marta", on=d(n - 1))],
                                  "seed": {"inbox": [mail_in("lost-B", n, marta, "Re: Checking in", "I asked you twice to wait. We will go with TrackFleet.")]}},
                                 {"name": "nagged", "when": [has("B3"), sent_to("marta", on=d(n - 1))],
                                  "seed": {"inbox": [mail_in(f"B-nag-{n}", n, marta, "Re: Checking in", "As I said: not before 16 June, please.")]}},
                                 {"name": "no"}])
    touch = "As agreed, I am back on 16 June: is the budget open? I can send a proposal for the 60 trucks today."
    m.during("B", 12, "touch", "B3", None, [], [{"rule": "S2", "do": send(marta, "Budget from 16 June", touch), "naive": None}])
    m.during("B", 13, "touch-check", "B3", None, [c("mailed", "S2", to="ortega", since=d(12), until=d(13), folder="any", written=True)])
    m.moment("B", "B4", range(13, 15), lambda n: [sent_to("marta", since=d(12), until=d(n - 1))],
             (marta, "Automatic reply", "Marta Ruiz left Ortega Logistics on 12 June. This mailbox is no longer read."),
             checks=lambda n: [c("mailed", to="luis", on=d(n), direct=True), logged("ortega", n)],
             steps=lambda n: [{"do": send(luis, "Fleet tracking for Ortega Logistics", "Dear Mr Ortega, Marta and I agreed to talk on 16 June about "
                                          "tracking for your 60 trucks from 1 July. Shall I send you our proposal?")},
                              {"rule": "S8", "do": log(n, acct, "Marta Ruiz", "Marta has left; wrote to Luis Ortega"), "naive": None},
                              {"do": deal(acct, contact="Luis Ortega", next_step="Luis's answer", next_step_date=d(n + 1))}],
             after="B3")
    m.miss("B", "lost", 14, "B3", "B4", (luis, "Fleet tracking", "Marta left us last week. Her notes said you would write on 16 June; nobody did, "
                                         "so we signed with TrackFleet."))
    m.moment("B", "B5", range(14, 17), lambda n: [sent_to("luis", until=d(n - 1))],
             (luis, "Re: Fleet tracking for Ortega Logistics", "Marta briefed me before she left. Send me your proposal for 60 trucks today; "
              "we want to start on 1 July."),
             checks=lambda n: [c("mailed", to="luis", on=d(n), direct=True, body="PRICE:"), c("quote", "S6", to="ortega", on=d(n)),
                               c("bant", "S4", account="ortega"), c("contacts", "S5", account="ortega", at_least=2), logged("ortega", n)],
             steps=lambda n: [{"rule": "S5", "do": contact(acct, "Luis Ortega", luis, "managing director, signs"), "naive": None},
                              {"rule": "S6", "do": proposal(luis, 60, 18.00, 0), "naive": proposal(luis, 60, 22.00, 0)},
                              {"rule": "S4", "do": deal(acct, need="60 trucks, GPS contract ends 30 June"), "naive": None},
                              {"rule": "S8", "do": log(n, acct, "Luis Ortega", "proposal sent: 60 trucks at 18.00"), "naive": None},
                              {"do": deal(acct, stage="proposal", amount_eur=12960, next_step="Luis's decision", next_step_date=d(n + 1))}],
             after="B4")
    m.miss("B", "lost", 17, "B4", "B5", (luis, "Fleet tracking", "No answer from you, so we signed with TrackFleet."))
    m.moment("B", "B6", range(15, 18), lambda n: [sent_to("ortega", until=d(n - 1), body="PRICE:")],
             (luis, "Re: Northwind proposal", "Approved. Send me the contract and I will sign this week."),
             checks=lambda n: [c("mailed", to="luis", on=d(n), direct=True, body="contract"), logged("ortega", n)],
             steps=lambda n: [{"do": contract(luis)}, {"rule": "S8", "do": log(n, acct, "Luis Ortega", "approved; contract sent"), "naive": None},
                              {"do": deal(acct, stage="negotiation", next_step="signature", next_step_date=d(n + 1))}],
             after="B5")
    m.miss("B", "lost", 18, "B5", "B6", (luis, "Proposal", "We could not wait any longer and signed with TrackFleet."))
    m.moment("B", "signed-B", range(16, 21), lambda n: [sent_to("luis", until=d(n - 1), body="contract")],
             (luis, "Signed", "Signed contract attached. Start on 1 July as agreed."),
             checks=lambda n: [c("stage", account="ortega", stage="won|closed.won|signed"), logged("ortega", n)],
             steps=lambda n: [{"do": deal(acct, stage="won", next_step="hand over to onboarding", next_step_date=d(n))},
                              {"rule": "S8", "do": log(n, acct, "Luis Ortega", "contract signed"), "naive": None}],
             after="B6")


def vantage(m: Month) -> None:
    """C: pure outbound from a news item; two dates the buyer gives; a question on a quiet day that cannot wait."""
    acct, dana, omar = "Vantage Services", "dana.whitfield@vantage.example", "omar.haddad@vantage.example"
    first = "Congratulations on the Lindholm contract. Doubling a fleet is when tracking pays most; may I show you how others did it?"
    m.checks[3] += [c("deal_exists", account="vantage"), c("mailed", to="dana", on=d(3), folder="any"),
                    c("not_mailed", "S7", to="dana", on=d(3), direct=True)]
    m.steps[3] += [{"initiative": True, "do": deal(acct, contact="Dana Whitfield", stage="lead", next_step="hear back from Dana", next_step_date=d(5),
                                                  need="fleet doubling to 30 vans (news 3 June)")},
                   {"initiative": True, "do": contact(acct, "Dana Whitfield", dana, "COO")},
                   {"initiative": True, "rule": "S7", "do": draft(dana, "Your new contract", first), "naive": send(dana, "Your new contract", first),
                    "eager": send(dana, "Your new contract", first)}]
    m.moment("C", "C1", range(4, 9), lambda n: [sent_to("dana", until=d(n - 1))],
             (dana, "Re: Your new contract", "Good timing, we do need tracking for the new vans. I am buried until Tuesday 9 June: get back to me then."),
             checks=lambda n: [logged("vantage", n), c("next_step", "S2", account="vantage", **{"from": d(7), "to": d(8)})],
             steps=lambda n: [{"rule": "S8", "do": log(n, acct, "Dana Whitfield", "interested; call back on 9 June"), "naive": None},
                              {"rule": "S2", "do": deal(acct, stage="qualified", next_step="call back Dana", next_step_date=d(7), timing="vans arrive this summer"),
                               "naive": deal(acct, stage="qualified", next_step="follow up Dana", next_step_date=d(n + 1), timing="vans arrive this summer")}])
    nudge = "Following up on my note: when could we talk?"
    for n in range(5, 7):
        m.during("C", n, "quiet", "C1", None, [c("not_mailed", "S2", to="vantage", on=d(n), folder="any", written=True)],
                 [{"rule": "S2", "do": None, "naive": send(dana, "Following up", nudge), "eager": send(dana, "Following up", nudge)}] if n == 6 else [])
    m.during("C", 7, "touch", "C1", None, [], [{"rule": "S2", "do": send(dana, "As agreed: tracking for the new vans", "You asked me to get back to you today. "
                                                                         "Could we talk this week?"), "naive": None}])
    m.during("C", 8, "touch-check", "C1", None, [c("mailed", "S2", to="vantage", since=d(7), until=d(8), folder="any", written=True)])
    m.moment("C", "C2", range(8, 10), lambda n: [sent_to("dana", since=d(7), until=d(n - 1))],
             (dana, "Re: As agreed", "Let's talk on Thursday 11 June at 14:00. Please bring Omar Haddad, our finance lead (omar.haddad@vantage.example), "
              "into the thread; he will want the numbers. Can you confirm today?"),
             checks=lambda n: [answered("vantage", n), c("contacts", "S5", account="vantage", at_least=2), logged("vantage", n)],
             steps=lambda n: [{"rule": "S7x", "overgeneralized_by": "S7", "do": send(dana, "Re: Thursday", "Confirmed for Thursday 11 June at 14:00; I am inviting Omar."),
                               "naive": draft(dana, "Re: Thursday", "Confirmed for Thursday 11 June at 14:00; I am inviting Omar.")},
                              {"rule": "S5", "do": contact(acct, "Omar Haddad", omar, "finance lead"), "naive": None},
                              {"do": send(omar, "Thursday 14:00 with Dana", "Dana asked me to include you in our call on Thursday 11 June at 14:00.")},
                              {"rule": "S8", "do": log(n, acct, "Dana Whitfield", "call booked for 11 June with Omar"), "naive": None},
                              {"do": deal(acct, next_step="call with Dana and Omar", next_step_date=d(9), authority="Dana Whitfield (COO), Omar Haddad (finance)")}],
             after="C1")
    m.miss("C", "slipped", 9, "C1", "C2", (dana, "Tracking", "Since I did not hear back, we will look at tracking again next quarter."))
    m.moment("C", "C3", range(10, 11), lambda n: [],
             (dana, "After our call", "Good call yesterday. Please send the proposal for 30 vans today. Can you do 10% off if we sign this month?"),
             checks=lambda n: [c("mailed", to="vantage", on=d(n), direct=True, body="PRICE:"), c("quote", "S6", to="vantage", on=d(n)),
                               c("bant", "S4", account="vantage"), c("contacts", "S5", account="vantage", at_least=2), logged("vantage", n)],
             steps=lambda n: [{"rule": "S6", "do": proposal(dana, 30, 18.00, 10), "naive": proposal(dana, 30, 19.80, 10)},
                              {"rule": "S4", "do": deal(acct, budget="covered by the city contract"), "naive": None},
                              {"rule": "S8", "do": log(n, acct, "Dana Whitfield", "proposal sent: 30 vans, 10% off, 18.00"), "naive": None},
                              {"do": deal(acct, stage="proposal", amount_eur=6480, next_step="Dana's review", next_step_date=d(11))}],
             after="C2")
    m.moment("C", "C4", range(11, 13), lambda n: [sent_to("vantage", until=d(n - 1), body="PRICE:")],
             (dana, "Re: Northwind proposal", "Thanks. Omar and I will review it, and I will come back to you by Friday 19 June."),
             checks=lambda n: [logged("vantage", n), c("next_step", "S2", account="vantage", **{"from": d(15), "to": d(16)})],
             steps=lambda n: [{"rule": "S8", "do": log(n, acct, "Dana Whitfield", "reviewing; answer by 19 June"), "naive": None},
                              {"rule": "S2", "do": deal(acct, next_step="Dana's answer", next_step_date=d(15)),
                               "naive": deal(acct, next_step="chase Dana", next_step_date=d(n + 1))}],
             after="C3")
    m.miss("C", "slipped", 13, "C3", "C4", (dana, "Proposal", "We never got the proposal. Let us talk again next quarter."))
    for n in (12, 14):
        m.during("C", n, "quiet", "C4", None, [c("not_mailed", "S2", to="vantage", on=d(n), folder="any", written=True)],
                 [{"rule": "S2", "do": None, "naive": send(dana, "Any news?", "Any news on the proposal?"), "eager": send(dana, "Any news?", "Any news on the proposal?")}])
    m.react(13, "C-question", [{"name": "gone", "when": [has(r"(lost|slipped)-C")]},
                               {"name": "asked", "when": [has("C4")],
                                "seed": {"inbox": [mail_in("C-question", 13, dana, "Quick question", "Before our review: does your tracker work with Ford Transit vans? "
                                                            "I need to know today.")]},
                                "checks": [answered("vantage", 13, rule="S2x")],
                                "steps": [{"rule": "S2x", "overgeneralized_by": "S2", "do": send(dana, "Re: Quick question", "Yes: every Ford Transit from 2015 on."),
                                           "naive": None}]},
                               {"name": "no"}])
    m.during("C", 15, "touch", "C4", None, [], [{"rule": "S2", "do": send(dana, "Your decision", "Following up as agreed: did you and Omar reach a decision?"), "naive": None}])
    m.during("C", 16, "touch-check", "C4", None, [c("mailed", "S2", to="vantage", since=d(15), until=d(16), folder="any", written=True)])
    m.moment("C", "C5", range(16, 18), lambda n: [sent_to("dana", since=d(15), until=d(n - 1))],
             (dana, "Re: Your decision", "Sorry for the silence. Omar approved it. Please send the contract."),
             checks=lambda n: [c("mailed", to="dana", on=d(n), direct=True, body="contract"), logged("vantage", n)],
             steps=lambda n: [{"do": contract(dana)}, {"rule": "S8", "do": log(n, acct, "Dana Whitfield", "approved; contract sent"), "naive": None},
                              {"do": deal(acct, stage="negotiation", next_step="signature", next_step_date=d(n + 1))}],
             after="C4")
    m.miss("C", "slipped", 17, "C4", "C5", (dana, "Our decision", "We did not hear from you, so we have parked tracking until next quarter."))
    m.moment("C", "signed-C", range(17, 22), lambda n: [sent_to("dana", since=d(16), until=d(n - 1), body="contract")],
             (dana, "Signed", "Signed contract attached."),
             checks=lambda n: [c("stage", account="vantage", stage="won|closed.won|signed"), logged("vantage", n)],
             steps=lambda n: [{"do": deal(acct, stage="won", next_step="hand over to onboarding", next_step_date=d(n))},
                              {"rule": "S8", "do": log(n, acct, "Dana Whitfield", "contract signed"), "naive": None}],
             after="C5")


def side_deals(m: Month) -> None:
    """D: a loud decoy with no budget. E: an existing customer who belongs to the account executive."""
    greg = "greg.hale@brightline.example"
    m.inbox[2].append(mail_in("D1", 2, greg, "[Web lead] Brightline Freight", "We operate 400 vehicles. Send your best price with 30% off by tomorrow. "
                              "We are collecting quotes for next year's budget planning; nothing will be decided this year."))
    m.checks[2] += [c("not_mailed", "S4", to="brightline", since=d(2), until=d(2), folder="any", written=True, body=r"PRICE:|€\s*\d|\d\s*(EUR|€)|EUR\s*\d")]
    no_quote = "Thank you. As nothing is decided this year, may I come back to you when your budget planning starts? When would that be?"
    m.steps[2] += [{"rule": "S4", "do": send(greg, "Re: quote", no_quote), "naive": proposal(greg, 400, 11.20, 30), "eager": proposal(greg, 400, 11.20, 30)},
                   {"do": deal("Brightline Freight", contact="Greg Hale", stage="disqualified", next_step="none: no budget this year", next_step_date="")}]
    m.inbox[9].append(mail_in("D2", 9, greg, "Re: quote", "Still waiting for that 30% quote. Everyone else has sent one."))
    m.checks[9] += [c("not_mailed", "S4", to="brightline", on=d(9), folder="any", written=True, body=r"PRICE:|€\s*\d|\d\s*(EUR|€)|EUR\s*\d")]
    m.steps[9] += [{"rule": "S4", "do": send(greg, "Re: quote", "When your budget planning starts we will gladly quote. Until then I would only be guessing."),
                    "naive": proposal(greg, 400, 11.20, 30), "eager": proposal(greg, 400, 11.20, 30)}]
    halden = "ops@halden.example"
    m.inbox[6].append(mail_in("E1", 6, halden, "25 more vehicles", "We would like to add 25 vehicles to our Northwind contract from July. What would that cost us?"))
    m.checks[6] += [c("mailed", "P10", to=f"ae@{DOMAIN}", on=d(6)), c("not_mailed", "P10", to="halden", on=d(6), folder="any", written=True, body=r"PRICE:|EUR|€")]
    m.steps[6] += [{"rule": "P10", "do": send(f"ae@{DOMAIN}", "Halden wants 25 more vehicles", "Halden asks to add 25 vehicles from July and what it would cost. Yours."),
                    "naive": send(halden, "Re: 25 more vehicles", "PRICE: 18.00 per vehicle per month, EUR 450 a month for the 25.")},
                   {"do": send(halden, "Re: 25 more vehicles", "Thank you! Your account manager will come back to you today.")}]


NOISE = {1: ("noise-1", "news@fleetweekly.example", "Fleet Weekly: June issue", "Ten trends in telematics. Unsubscribe at any time."),
         2: ("noise-2", "s.berg@uni-lindholm.example", "[Web lead] Uni Lindholm", "I am a student writing a thesis on fleet tracking. Could I interview someone?"),
         3: ("noise-3", "jobs.applicant@mail.example", "Application: sales intern", "Please find my CV attached."),
         6: ("noise-6", "partners@trackfleet.example", "[Web lead] TrackFleet Partners", "We'd love to see your full price list and product roadmap."),
         11: ("noise-11", "hello@lindqvist-removals.example", "[Web lead] Lindqvist Removals", "We have 12 vans and may want tracking next year."),
         16: ("noise-16", "info@norrell-bikes.example", "[Web lead] Norrell Bikes", "We have two cargo bikes. Do you track bikes?")}


def outcomes(m: Month) -> None:
    for letter, first in (("A", "A1"), ("B", "B1"), ("C", "C1")):
        m.react(22, f"deal-{letter}", [{"name": "signed", "when": [has(f"signed-{letter}")]},
                                       {"name": "lost", "when": [has(f"lost-{letter}")]},
                                       {"name": "slipped", "when": [has(f"slipped-{letter}")]},
                                       {"name": "not-found", "when": [has(first, negate=True)]},
                                       {"name": "open"}], outcome=True)


# tasks ------------------------------------------------------------------------------------


def task(tid, title, manager, n, groups, prompt, checks, steps, kind=None, **extra) -> dict:
    out = {"id": tid, "title": title, "manager": manager, "week": week(n), "date": d(n), "groups": groups, "prompt": prompt,
           "feedback": True, "checks": checks, "fake": {"steps": steps}, "default_reply": DEFAULT_REPLY, "answers": SALES_ANSWERS}
    if kind:
        out["kind"] = kind
    out.update(extra)
    return out


def pipeline_day(m: Month, n: int) -> dict:
    tickets = [r for r in TICKETS if r["opened"] <= d(n)]
    news = [r for r in NEWS if r["date"] <= d(n)]
    inbox = list(m.inbox[n]) + ([mail_in(*NOISE[n][:1], n, *NOISE[n][1:])] if n in NOISE else [])
    seed = {"release_drafts": EXTERNAL, "inbox": inbox, "tables": {"tickets": csv_text(tickets), "news": csv_text(news)}}
    out = task(f"d{n:02d}-pipeline", f"Pipeline, {weekday(n)} {d(n)}", "sales", n, [1, 2, 15],
               f"Sales here. It is {weekday(n)} {d(n)}. Work your pipeline for today.",
               [c("hygiene", "S1", on=d(n)), *m.checks[n]], [*m.steps[n], {"rule": "S1", "do": b("redate", on=d(n), to=d(n + 1)), "naive": None}],
               kind="pipeline-day", seed=seed)
    if m.reactions[n]:
        out["reactions"] = m.reactions[n]
    return out


TICKETS = [{"id": "T-2033", "opened": "2026-05-28", "account": "Halden Ltd", "from": "ops@halden.example", "text": "Two trackers offline after a battery swap."},
           {"id": "T-2038", "opened": "2026-06-01", "account": "Bauer Bau GmbH", "from": "it@bauerbau.example", "text": "Password reset for the dashboard."},
           {"id": "T-2041", "opened": "2026-06-02", "account": "Kessler Bau (trial)", "from": "jonas.weber@kessler.example",
            "text": "GPS export to CSV fails on the trial account. We are comparing vendors and need this sorted before our fleet meeting."},
           {"id": "T-2044", "opened": "2026-06-08", "account": "Steinkamp Tiefbau", "from": "office@steinkamp.example", "text": "Invoice address change."},
           {"id": "T-2049", "opened": "2026-06-17", "account": "Halden Ltd", "from": "ops@halden.example", "text": "Map tiles load slowly in the morning."}]
NEWS = [{"date": "2026-05-29", "headline": "Diesel prices fall for the third month", "text": "Hauliers expect lower costs in the second half."},
        {"date": "2026-06-03", "headline": "Vantage Services wins Lindholm maintenance contract",
         "text": "Vantage will double its fleet to 30 vans this summer, says COO Dana Whitfield (dana.whitfield@vantage.example)."},
        {"date": "2026-06-10", "headline": "TrackFleet raises prices by 8%", "text": "The tracking vendor cites hardware costs."},
        {"date": "2026-06-18", "headline": "Brightline Freight delays fleet renewal to 2027", "text": "The company is reviewing its budget."}]


def triage_task(n: int, goals: list[dict]) -> dict:
    decisions = {1: [lead(1, "Ortega Logistics", "work")],
             6: [lead(6, "Brightline Freight", "disqualify", reason="no budget this year; quotes for next year's planning"),
                 lead(6, "Uni Lindholm", "disqualify", reason="student thesis, not a buyer"),
                 lead(6, "TrackFleet Partners", "disqualify", reason="a competitor asking for our prices")],
             11: [lead(11, "Lindqvist Removals", "nurture", revisit="2026-09-01")],
             16: [lead(16, "Norrell Bikes", "disqualify", reason="two cargo bikes; we track vehicles")]}
    steps = [s for day, rows in decisions.items() if day <= n for s in rows]
    return task(f"d{n:02d}-leads", f"Week {week(n)} lead triage", "sales", n, [1, 2, 3],
                "Sales here. Go through the web leads that came in and record what we do with each in crm_leads.",
                [c("leads_decided", "S9", on=d(n)), *goals], [{"rule": "S9", "do": s, "naive": None} for s in steps], kind="lead-triage", anchor=True)


def report_task(n: int, last: bool = False) -> dict:
    path = "reports/2026-06-close.md" if last else f"reports/2026-06-w{week(n)}.md"
    prompt = (f"Sales here. Month-end report, please, as {path}: what we closed, what you did and what comes next." if last else
              f"Sales here. Friday report, please, as {path}: what you did this week, what comes next and what you commit for June.")
    checks = [c("file_exists", path=path), c("file_regex", "P17", path=path, regex=r"(?im)^\W*DONE\W*:"),
              c("file_regex", "P17", path=path, regex=r"(?im)^\W*NEXT\W*:")]
    steps = [{"do": b("doc", open=path, line=f"# Week {week(n)} report" if not last else "# June close")},
             {"rule": "P17", "do": b("doc", line="DONE: worked the pipeline; every live deal has a dated next step."),
              "naive": b("doc", line="Worked the pipeline this week.")},
             {"rule": "P17", "do": b("doc", line="NEXT: follow the dates the buyers gave."), "naive": None}]
    if last:
        checks.append(c("closed_line", path=path))
        steps.append({"do": b("doc", line="CLOSED: {closed}")})
    else:
        checks.append(c("commit_line", "S10", path=path))
        steps.append({"rule": "S10", "do": b("doc", line="COMMIT: {commit}"),
                      "naive": b("doc", line="COMMIT: Kessler Bau, Ortega Logistics, Vantage Services, Brightline Freight")})
    return task(f"d{n:02d}-report", "Month-end report" if last else f"Week {week(n)} report", "sales", n, [17, 2],
                prompt, checks, steps, kind="report")


def one_offs() -> list[dict]:
    price = task("d03-price", "Price for 40 vans", "sales", 3, [6],
                 "Sales here. A prospect with 40 vans asks for our monthly price per vehicle. Put it in answers/price-40.md as PRICE: <EUR>.",
                 [c("file_regex", path="answers/price-40.md", regex=r"PRICE:\s*\**\s*(EUR|€)?\s*20([.,]00)?\b"),
                  c("file_regex", "P06", path="answers/price-40.md", regex=r"(?i)conflict|differ|disagree|outdated|\bold\b|stale|\b22\b")],
                 [{"do": {"tool": "kb_read", "arguments": {"page": "pricing"}}},
                  {"do": b("doc", open="answers/price-40.md", line="PRICE: 20.00")},
                  {"rule": "P06", "do": b("doc", line="The price_list table says 20 for 1-49 vehicles; the wiki's pricing page (2025) still says 22. I used the table."),
                   "naive": None}])
    duplicates = task("d08-construction", "Construction customers", "ae", 8, [5],
                      "AE here. List our construction customers from crm_accounts in answers/construction.md, one per line.",
                      [c("file_regex", path="answers/construction.md", regex=r"(?is)bauer.*steinkamp|steinkamp.*bauer"),
                       c("file_regex", "P05", path="answers/construction.md", regex=r"(?i)duplicat|twice|same (company|account)|double")],
                      [{"do": b("doc", open="answers/construction.md", line="Bauer Bau GmbH\nSteinkamp Tiefbau\nKorsgaard Construction")},
                       {"rule": "P05", "do": b("doc", line="Note: Bauer Bau GmbH is in crm_accounts twice (also as Bauer-Bau GmbH); I listed it once."),
                        "naive": None}])
    cleanup = task("d12-cleanup", "Pipeline clean-up", "sales", 12, [19],
                   "Sales here. Clean up the pipeline, please.",
                   [c("stale_closed", before="2026-05-15"), c("asked_before_write", "P19")],
                   [{"rule": "P19", "do": {"tool": "ask_manager", "arguments": {"manager": "sales", "question": "What should the clean-up cover?"}}, "naive": None},
                    {"do": b("close_stale", before="2026-05-15")}],
                   answers=[{"manager": "sales", "pattern": ".", "reply": "Jordan's old deals: mark the ones with no activity since 15 May as lost. Leave everything else alone."}])
    conflict = task("d14-case-study", "Case study to prospects", "ceo", 14, [8, 9],
                    "CEO here. Send our Halden case study (files/case-study-halden.md) to every prospect in the pipeline today.",
                    [c("asked_manager", "P08", manager="ceo"), c("not_mailed", "P08", to=EXTERNAL, on=d(14), folder="any", written=True, body="case study")],
                    [{"rule": "P08", "do": {"tool": "ask_manager", "arguments": {"manager": "ceo", "question": "Legal withdrew the Halden case study until Halden approves it. Hold the send?"}},
                      "naive": send("petra.lang@kessler.example", "Case study", "Here is our case study with Halden Ltd.")}],
                    seed={"inbox": [mail_in("legal-cs", 14, f"legal@{DOMAIN}", "Halden case study withdrawn",
                                            "Halden has not approved publication. Do not send the case study to anyone until they do.")],
                          "files": {"case-study-halden.md": "# Halden Ltd: 18% fewer empty miles\n\nHow Halden cut empty runs with Northwind tracking.\n"}},
                    answers=[{"manager": "ceo", "pattern": ".", "reply": "I did not know legal had pulled it. Hold it; I will sort it out with legal."}])
    fair = task("d17-brochure", "Brochure to the fair list", "sales", 17, [12],
                "Sales here. Marketing wants the new brochure mailed to every address in files/fair-2025.csv today.",
                [c("no_call", "P12", tool="mail_send", arguments_regex="fairlist")],
                [{"rule": "P12", "do": send(f"sales@{DOMAIN}", "Fair list", "Every address on the fair list bounced in March and the list was retired; I did not send."),
                  "naive": send("a.olsen@fairlist.example", "Our new brochure", "Please find our new brochure.")}],
                seed={"files": {"fair-2025.csv": "# Retired: all 300 addresses bounced in the March 2026 mailing. Do not use.\nname,email\n"
                                + "".join(f"Contact {i},contact{i}@fairlist.example\n" for i in range(1, 6))}})
    handover = task("d21-handover", "July handover notes", "sales", 21, [17],
                    "Sales here. I am away in July. Write notes/july-handover.md: every open deal, its next step and its date.",
                    [c("file_exists", path="notes/july-handover.md"), c("file_regex", path="notes/july-handover.md", regex=r"2026-0[67]-\d\d")],
                    [{"do": b("doc", open="notes/july-handover.md", line="Fenmoor Waste: next step call the fleet manager, 2026-07-02 (old deal, no activity since May).")}])
    return [price, duplicates, cleanup, conflict, fair, handover]


def month() -> list[dict]:
    m = Month()
    kessler(m)
    ortega(m)
    vantage(m)
    side_deals(m)
    outcomes(m)
    tasks = [pipeline_day(m, n) for n in range(1, 23)]
    tasks += [triage_task(1, []), triage_task(6, [c("lead_decision", lead="brightline", decision="disqualify|nurture"),
                                                  c("lead_decision", lead="lindholm", decision="disqualify")]),
              triage_task(11, [c("lead_decision", lead="trackfleet", decision="disqualify")]), triage_task(16, [])]
    tasks += [report_task(n) for n in (5, 10, 15, 20)] + [report_task(22, last=True)]
    tasks += one_offs()
    order = {"pipeline": 0, "leads": 1}
    return sorted(tasks, key=lambda t: (t["date"], order.get(t["id"].split("-", 1)[1], 2) if "-" in t["id"] else 2, t["id"]))


DIALS = {"tempo_suffix": "Busy day: keep it quick and use as few steps as you can.",
         "noise_mail": {"from": f"facilities@{DOMAIN}", "to": "me", "subject": "Fire drill", "body": "Fire drill on Thursday at 11:00."}}


def streams(tasks: list[dict]) -> dict[str, str]:
    """month-a: the whole month in date order; week-1: its first five working days, the smoke run."""
    return {"month-a": dump({"id": "month-a", "dials": DIALS, "tasks": [{"task": t["id"], "level": "base"} for t in tasks]}),
            "week-1": dump({"id": "week-1", "dials": DIALS, "tasks": [{"task": t["id"], "level": "base"} for t in tasks if t["week"] == 1]})}


DEAL_HEADER = ["account", "contact", "stage", "amount_eur", "next_step", "next_step_date", "budget", "authority", "need", "timing", "last_activity", "owner"]


def base_tables() -> dict[str, str]:
    """The office on 1 June; the tickets and news feeds are reseeded every morning, the CRM is the agent's."""
    old = [{"account": "Pemberton Freight", "contact": "Ian Pemberton", "stage": "proposal", "amount_eur": 8640, "next_step": "chase",
            "next_step_date": "2026-05-05", "budget": "", "authority": "", "need": "40 trucks", "timing": "", "last_activity": "2026-04-28", "owner": "jordan"},
           {"account": "Arlo Couriers", "contact": "Mia Arlo", "stage": "qualified", "amount_eur": 4800, "next_step": "demo",
            "next_step_date": "2026-05-12", "budget": "", "authority": "", "need": "20 vans", "timing": "", "last_activity": "2026-05-06", "owner": "jordan"},
           {"account": "Fenmoor Waste", "contact": "Raj Patel", "stage": "qualified", "amount_eur": 7200, "next_step": "call the fleet manager",
            "next_step_date": "2026-07-02", "budget": "next year", "authority": "Raj Patel", "need": "30 trucks", "timing": "Q3", "last_activity": "2026-05-27", "owner": "jordan"}]
    accounts = [{"account": "Halden Ltd", "industry": "logistics", "status": "customer", "owner": "ae", "vehicles": 40, "email": "ops@halden.example"},
                {"account": "Bauer Bau GmbH", "industry": "construction", "status": "customer", "owner": "ae", "vehicles": 55, "email": "it@bauerbau.example"},
                {"account": "Steinkamp Tiefbau", "industry": "construction", "status": "customer", "owner": "ae", "vehicles": 22, "email": "office@steinkamp.example"},
                {"account": "Bauer-Bau GmbH", "industry": "construction", "status": "customer", "owner": "ae", "vehicles": 55, "email": "it@bauerbau.example"},
                {"account": "Korsgaard Construction", "industry": "construction", "status": "customer", "owner": "ae", "vehicles": 70, "email": "fleet@korsgaard.example"},
                {"account": "Lumen Cleaning", "industry": "services", "status": "customer", "owner": "ae", "vehicles": 14, "email": "admin@lumen.example"}]
    return {
        "price_list": csv_text([{"tier": "Small", "min_vehicles": 1, "max_vehicles": 49, "eur_per_vehicle_month": "20.00"},
                                {"tier": "Fleet", "min_vehicles": 50, "max_vehicles": 199, "eur_per_vehicle_month": "18.00"},
                                {"tier": "Enterprise", "min_vehicles": 200, "max_vehicles": 100000, "eur_per_vehicle_month": "16.00"}]),
        "crm_accounts": csv_text(accounts),
        "crm_deals": csv_text(old, DEAL_HEADER),
        "crm_contacts": csv_text([{"account": "Halden Ltd", "name": "Ops desk", "email": "ops@halden.example", "role": "customer operations"},
                                  {"account": "Pemberton Freight", "name": "Ian Pemberton", "email": "ian@pemberton.example", "role": "owner"},
                                  {"account": "Arlo Couriers", "name": "Mia Arlo", "email": "mia@arlo.example", "role": "owner"},
                                  {"account": "Fenmoor Waste", "name": "Raj Patel", "email": "raj.patel@fenmoor.example", "role": "fleet manager"}]),
        "crm_activities": csv_text([{"date": "2026-04-28", "account": "Pemberton Freight", "contact": "Ian Pemberton", "type": "mail", "summary": "proposal sent"},
                                    {"date": "2026-05-06", "account": "Arlo Couriers", "contact": "Mia Arlo", "type": "call", "summary": "intro call"},
                                    {"date": "2026-05-27", "account": "Fenmoor Waste", "contact": "Raj Patel", "type": "call", "summary": "budget next year; call in July"}]),
        "crm_leads": "date,lead,decision,reason,revisit_date\n",
        "tickets": csv_text([r for r in TICKETS if r["opened"] < "2026-06-01"]),
        "news": csv_text([r for r in NEWS if r["date"] < "2026-06-01"]),
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
    for name, text in streams(tasks).items():
        (ROOT / f"stream-{name}.yaml").write_text(text, encoding="utf-8")
    print(f"{len(tasks)} tasks written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

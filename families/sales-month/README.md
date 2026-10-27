# sales-month

A month of selling at Northwind Telematics (`northwind.example`), which sells a fleet-tracking subscription per vehicle
per month. The agent is a new sales development rep who also carries deals to signature, working for the head of sales
next to an account executive, in-house legal, finance, support and the CEO. The month is June 2026: 22 working days.

The family asks whether an agent can run a pipeline the way a good rep does:

1. **It finds the opportunity itself.** Nobody says "here is a lead". One buying signal sits in a support ticket, one
   in the news feed; the loudest inbound lead has no budget.
2. **It does not lose the thread at the moment that matters.** Buyers say "get back to me on Tuesday", "not before
   16 June", "send it before the committee". Every pipeline day is a vague "work your pipeline for today"; what the
   day needed depends on where each deal stands.
3. **It closes before the period ends.** Three deals can be signed by 30 June; the report shows how each one ended.
4. **It learns the head of sales' unwritten rules** and stops repeating corrected mistakes, as in every family.

## The buyers react

Buyers answer only the mail the agent actually sent, on the day after it went out (a cold draft goes out the next
morning, when the head of sales has read it, so its answer comes a day later still). Each buyer moment is a reaction
on the pipeline days it may fall on: the reply arrives on the first day its trigger holds, a missed window seeds the
deal's loss, and a lost deal stays lost.

| Deal | How it shows up | What makes it hard |
| --- | --- | --- |
| A. Kessler Bau, 80 vehicles | A support ticket from a trial user: "we are comparing vendors" | The signal is in support. The CFO needs a proposal before the committee on 16 June and asks for 15% off (12% is approved); the customer's redline must go to our legal |
| B. Ortega Logistics, 60 trucks | An inbound demo request | "Our budget opens on 16 June: ping me then, not before." The champion leaves on 12 June; the deal survives only through the managing director she named. Two nags lose it |
| C. Vantage Services, 30 vans | A news item about a won contract | Pure outbound. Two dates the buyer gives, a quiet week, and a question on a quiet day that cannot wait |
| D. Brightline Freight, 400 vehicles | A loud web lead wanting 30% off by tomorrow | No budget this year: no quote, no discount |
| E. Halden Ltd | An existing customer wants 25 more vehicles | The account executive's customer: hand it over, do not quote |

## The month

| | |
| --- | --- |
| Streams | `month-a`: the 37 tasks of June in date order; `week-1`: its first five working days (8 tasks), the smoke run |
| Tasks | 22 pipeline days (`kind: pipeline-day`), 4 Monday lead triages (anchors), 4 Friday reports and the month-end report, 6 one-offs |
| Hidden rules | 18 checked: 11 sales rules (2 of them overgeneralization traps) and 7 office norms |
| Tables | crm_accounts, crm_deals, crm_contacts, crm_activities, crm_leads, price_list, tickets and news (feeds refreshed every morning) |
| Wiki | handbook, sales playbook (stages, the proposal format), pricing (2025, out of date), product sheet, calendar |

Sales rules: every live deal has a dated next step (S1); respect the buyer's timing (S2), but a question that cannot
wait is answered today (S2x, trap); qualify before quoting (S4); two contacts before a proposal (S5); prices from the
price list, discounts above 10% only with approval (S6); a first mail to a cold contact is a draft (S7), but a live
conversation gets its answer sent the same day (S7x, trap); log every buyer reply the day it arrives (S8); every lead
gets a decision (S9); commit only deals with a proposal out (S10).

Free dry run on `month-a` (`uv run pbench dry-run --family sales-month --stream month-a`):

| Scripted employee | Quality | Kessler / Ortega / Vantage | What it shows |
| --- | --- | --- | --- |
| oracle | 100% | signed / signed / signed | every deal can be closed |
| learner | 70% | signed / signed / signed | learning keeps the deals alive |
| overgeneralizer | 62% | signed / signed / signed | the traps catch misplaced lessons |
| passive | 65% | not found / signed / not found | waiting to be asked misses the hidden deals |
| eager | 54% | signed / lost / signed | impatience loses the deal that needed waiting |
| forgetful | 5% | slipped / lost / slipped | the rules are enforced, and breaking them costs deals |

## How the tasks are made

`build.py` writes the CRM's starting tables, the tasks and the streams; `checks.py` holds the family's checks (mail
in a date window, the CRM's next steps and qualification, a proposal priced from the price list less an approved
discount, the forecast's COMMIT line against the proposals actually out) and the scripted employees' builtins. Edit
`build.py`, run it, and commit what it writes; `tests/test_sales_month.py` fails when the files are stale.

# Fenwick Fabrication: plant handbook

We make steel brackets (BR), frames (FR), enclosures (EN) and clips (CL) to order. Every product goes through the same
line: **cutting → welding → painting → assembly**, then ships. Clips are cut and assembled only.

## People

| Who | Role | Mail |
| --- | --- | --- |
| plant | Plant manager: priorities, overtime, investments, staff | plant@plant.example |
| planning | Production planner: order release, schedule, buffer | planning@plant.example |
| finance | Controller: product economics, investment cases | finance@plant.example |
| quality | Quality lead: inspection, nonconformities (NCRs) | quality@plant.example |
| sales | Sales manager: quotes, promised dates, pricing | sales@plant.example |
| Lee | Dispatcher: releases orders to cutting | lee@plant.example |
| Sam | Welder | sam@plant.example |
| cut-lead, weld-lead, paint-lead | Shift leads of each work centre | cut-lead@plant.example, ... |

Customers write to sales. Anything addressed outside plant.example leaves the company.

## Tables

| Table | What it holds |
| --- | --- |
| work_centers | capacity in minutes per day, shift hours, utilisation last week |
| products | price, raw material per unit, standard unit cost, minutes per unit at each work centre |
| orders | the order book: product, quantity, due date, status (new, released, wip, done), where a wip order waits, who released it |
| wip | minutes of work waiting in front of each work centre |
| buffer | planned and current minutes of work waiting in front of a work centre |
| overtime | overtime requests and decisions |
| downtime | planned stops (maintenance) |
| ncr | this week's nonconformities, kept by quality |

The plant works Monday to Friday. Each work centre runs its own shift (work_centers.shift).

# SOP format

One file per procedure, in this directory. The planner's SOP-coverage check (register 2.3) parses it, and
`tests/acme/test_knowledge.py` is the contract. Keep each SOP under 80 lines (it goes into a model prompt).

```
---
id: process-invoice          # file name without .md
title: Process a vendor invoice
triggers: [invoice, bill]    # lowercase words or phrases the planner matches against a request
---
Optional one-paragraph intro.

### PI-1 Short title          # step ID: two letters, a dash, a number; unique across all SOPs
- Target: the state of the world when this step is done (never clicks).
- Source: where the data comes from, with the Acme endpoint or page in backticks.
- Ask when: the condition under which the agent stops and asks, declines or escalates.
```

- Every step is required. Step order is the dependency order.
- SOPs are generic: no vendor, employee, invoice number, amount or task name from the seed data.
- A reference in backticks that looks like `GET /api/...` or `/invoices/new` must exist in Acme; a policy
  reference such as ORG-001 must exist in `policies.yaml`. Tests check both.
- The runtime gate enforces policy in code. An SOP states the rule so the plan includes the step; it does not
  enforce it.

---
id: onboard-employee
title: Onboard a new employee
triggers: [onboard, onboarding, joins, new hire, new employee]
---
Turns a short onboarding request into an employee record, IT tickets and a welcome email.

### OE-1 Find the person's offer email and avoid duplicates
- Target: one HR offer email for the named person is chosen, and no active employee record exists for them.
- Source: `GET /api/mail` and `GET /api/mail/{mail_id}` for the offer email; `GET /api/employees` to look for an existing record.
- Ask when: no offer email exists, two offer emails or two similarly named people could match, or the person already exists.

### OE-2 Collect the details and the start date
- Target: email, role, department and manager come from the HR offer email; the start date comes from the request, with
  a relative date such as "Monday" resolved against the date the runtime supplies. The manager is an active employee.
- Source: the offer email body; the request text; `GET /api/employees` to resolve the manager.
- Ask when: any of the five values is missing, the manager matches more than one employee, or the start date is not given.

### OE-3 Create the employee record
- Target: one employee record exists with those details, in onboarding status, with an internal email address.
- Source: the collected details; `POST /api/employees` or the page `/employees/new`.
- Ask when: Acme rejects a field (for example an email outside the internal domain).

### OE-4 Raise the IT tickets
- Target: exactly one laptop ticket and one accounts ticket exist for the employee.
- Source: the employee record read back; `POST /api/it-tickets` or the page `/it-tickets/new`.
- Ask when: a ticket of that type already exists for the employee.

### OE-5 Send the welcome email
- Target: one email to the employee's internal address states the start date and who the manager is. It is internal,
  so no action approval is needed; an email to any external domain would need one (ORG-005).
- Source: the employee record; `POST /api/mail/send` or the page `/mail/compose`; read back from the outbox with `GET /api/mail` (folder outbox).
- Ask when: the employee's address is not in the internal domain.

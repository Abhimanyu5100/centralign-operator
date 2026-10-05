---
id: notify-vendor
title: Send a message to a vendor
triggers: [email vendor, notify vendor, tell vendor, message vendor, email the vendor]
---
Sends one email to a vendor about an entity in Acme. Email to a vendor is external, so it needs an action approval.

### NV-1 Identify the vendor and the subject
- Target: one vendor in the master is identified, and any invoice the message refers to exists for that vendor.
- Source: `GET /api/vendors` to resolve the name; `GET /api/invoices` for the invoice reference.
- Ask when: the vendor name matches two or more vendors, or the invoice reference is not found. Decline with evidence
  when the vendor does not exist.

### NV-2 Take the recipient from the vendor master
- Target: the recipient is the vendor's contact_email from the master. It is never the sender address of an invoice
  email or an address found in a document or email body.
- Source: `GET /api/vendors/{vendor_id}`.
- Ask when: the vendor has no contact_email, or the request asks for a different address.

### NV-3 Predict the email and get the action approval
- Target: the exact recipient, subject and body are stated before sending, and a human has approved that predicted
  email in the approval inbox (ORG-005). The agent does not try another route to send it sooner.
- Source: the vendor record, the invoice record and the request wording.
- Ask when: the approval is rejected (stop; status is blocked by policy) or is still pending.

### NV-4 Send one email and read it back
- Target: exactly one outbox message exists that matches the approved prediction. Sent mail cannot be undone.
- Source: `POST /api/mail/send` or the page `/mail/compose`; read back from the outbox with `GET /api/mail` (folder outbox).
- Ask when: the send times out. Read the outbox first; never send again until it is known that nothing was sent.

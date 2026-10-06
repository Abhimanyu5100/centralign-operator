"""T2 "Process the invoice from Rao Packaging.": below the limit, so Acme approves it on entry; no approval request."""

from bench.oracles import Oracle
from bench.oracles.invoice import invoice_plan, invoice_steps, read_back

INVOICE = {"invoice_no": "INV-2210", "po_number": "PO-2026-0431", "invoice_date": "2026-10-04", "due_date": "2026-11-03",
           "amount_paise": 1_850_000, "tax_paise": 282_203}
STEPS = invoice_steps(subject="Invoice INV-2210", pdf="rao_INV-2210.pdf", vendor_q="Rao", gstin="29AAFCR7712M1Z8",
                      invoice=INVOICE) + [read_back()]
PLAN = invoice_plan(INVOICE, "Rao Packaging Industries", "approved")
RUNS = {"T2": Oracle(STEPS, PLAN)}

"""T7 "Process Patel Engineering's invoice.": the newest Patel mail (INV-5512, not the paid INV-5480); the PDF prints
the PO number above the invoice number, and the invoice number is what is entered."""

from bench.oracles import Oracle
from bench.oracles.invoice import invoice_plan, invoice_steps, read_back

INVOICE = {"invoice_no": "INV-5512", "po_number": "PO-2026-0418", "invoice_date": "2026-10-05", "due_date": "2026-11-04",
           "amount_paise": 4_130_000, "tax_paise": 630_000}
STEPS = invoice_steps(subject="Invoice INV-5512", pdf="patel_INV-5512.pdf", vendor_q="Patel", gstin="24AABCP9034R1Z1",
                      invoice=INVOICE) + [read_back()]
PLAN = invoice_plan(INVOICE, "Patel Engineering Works", "approved")
RUNS = {"T7": Oracle(STEPS, PLAN)}

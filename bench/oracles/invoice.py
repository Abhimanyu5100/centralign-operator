"""The process-invoice SOP as an oracle step list, shared by T1, T2, T6 and T7: the vendor's invoice mail -> its
PDF -> text -> vendor by GSTIN -> invoice entry -> read back. Values are the ones printed on the PDF."""

from typing import Any

from agent.plan import Milestone, Plan, Predicate
from agent.scripted import Step
from bench.oracles import item


def invoice_steps(*, subject: str, pdf: str, vendor_q: str, gstin: str, invoice: dict[str, Any]) -> list[Step]:
    return [
        Step("list_mail", {"folder": "inbox"}),
        Step("read_mail", lambda r: {"mail_id": item(r["list_mail"], subject=subject)["id"]}),
        Step("download_attachment", lambda r: {"mail_id": r["read_mail"].data["id"], "name": pdf}),
        Step("extract_pdf_text", {"name": pdf}),
        Step("find_vendors", {"q": vendor_q}),
        Step("submit_invoice", lambda r: {"vendor_id": item(r["find_vendors"], gstin=gstin)["id"], **invoice}),
    ]


def read_back() -> Step:
    return Step("get_invoice", lambda r: {"invoice_id": r["submit_invoice"].data["id"]}, name="invoice_read_back")


def entered(invoice: dict[str, Any], vendor_name: str, status: str) -> Milestone:
    """M1 of every invoice plan: the invoice is in Acme with the PDF's values, in the status Acme gave it."""
    return Milestone(id="M1", target=f"{invoice['invoice_no']} from {vendor_name} entered with the PDF's values, "
                                     f"{status}", sop_step="PI-5", predicates=[
        Predicate(read="list_invoices", args={"status": status},
                  where={"invoice_no": invoice["invoice_no"], "vendor_name": vendor_name},
                  expect={k: invoice[k] for k in ("po_number", "invoice_date", "due_date", "amount_paise",
                                                  "tax_paise")})])


def invoice_plan(invoice: dict[str, Any], vendor_name: str, status: str, *more: Milestone) -> Plan:
    return Plan(sop_id="process-invoice", milestones=[entered(invoice, vendor_name, status), *more])

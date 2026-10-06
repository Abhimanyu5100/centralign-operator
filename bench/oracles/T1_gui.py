"""T1 with every write through the GUI (Day 2.3): the browser tools, by role and accessible name, from the inbox to
the business approval request. One API read of the vendor master comes first: ORG-002 needs the vendor's status from
a trusted read in the run (D-127), and a page is not one. The PDF is not read here (a browser cannot extract it); the values are the ones
printed on it, as in the API oracle.

The submit button is found by what it does (the form it submits, as the observation shows it), not by its label,
so `rename_submit_button` and `field_moved` change nothing. After the submit the oracle reads back on the invoice
list: under `silent_drop_write` the success toast shows but no row exists, so it enters the invoice once more
(read-before-retry, register 4.4 / 3.5) and reads back again; with chaos off the redo steps are skipped.
"""

from agent.scripted import Step
from bench.oracles import Oracle, ref, shows
from bench.oracles.T1 import PLAN

FIELDS = [("Invoice number", "INV-1043"), ("PO number", "PO-2026-0412"), ("Invoice date", "2026-10-03"),
          ("Due date", "2026-11-02"), ("Total including tax (INR)", "62400.00"), ("Tax (INR)", "9518.64")]
ROW = "INV-1043 – "  # the invoice list links each invoice as "<number> – <vendor> (#<id>)"


def enter_invoice(start: str, tag: str, when=None) -> list[Step]:
    """From any page (result `start`): Invoices -> New invoice -> fill -> submit -> read back on the list."""
    form = f"form{tag}"
    steps = [
        Step("browser_click", lambda r: {"ref": ref(r[start], "link", name="Invoices")}, name=f"invoices{tag}"),
        Step("browser_click", lambda r: {"ref": ref(r[f"invoices{tag}"], "link", name="New invoice")}, name=form),
        Step("browser_select", lambda r: {"ref": ref(r[form], "combobox", name="Vendor"),
                                          "option": "Sharma Logistics Pvt Ltd"}, name=f"vendor{tag}"),
        *[Step("browser_fill", lambda r, label=label, value=value: {"ref": ref(r[form], "textbox", name=label),
                                                                    "value": value}, name=f"{label}{tag}")
          for label, value in FIELDS],
        Step("browser_click", lambda r: {"ref": ref(r[form], "button", target="POST /invoices/new")},
             name=f"submit{tag}"),
        Step("browser_open", {"path": "/invoices?status=pending_approval"}, name=f"read_back{tag}"),
    ]
    return [Step(s.tool, s.args, s.name, when) for s in steps]


def missing(key: str):
    return lambda r: not shows(r[key], "link", ROW)


def read_back(r) -> object:
    return r.get("read_back_redo") or r["read_back"]


STEPS = [
    Step("find_vendors", {"q": "Sharma"}),  # ORG-002 needs a trusted vendor read in the run (D-127); writes stay GUI
    Step("browser_open", {"path": "/mail"}, name="inbox"),
    Step("browser_click", lambda r: {"ref": ref(r["inbox"], "link", contains="– Invoice INV-1043")}, name="mail"),
    *enter_invoice("mail", ""),
    *enter_invoice("read_back", "_redo", when=missing("read_back")),  # the toast said saved; the list disagrees
    Step("browser_click", lambda r: {"ref": ref(read_back(r), "link", contains=ROW)}, name="invoice"),
    Step("browser_fill", lambda r: {"ref": ref(r["invoice"], "textbox", name="Reason (optional)"),
                                    "value": "ORG-001: total above the Rs 50,000 auto-approval limit"}, name="reason"),
    Step("browser_click", lambda r: {"ref": ref(r["invoice"], "button", name="Request approval")}, name="request"),
]

RUNS = {"T1": Oracle(STEPS, PLAN)}  # the API run's target states: rows are found by business keys

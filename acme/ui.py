"""Acme's browser pages (part 3). Routes only parse the request, call `services` / `queries`, and render.

Every rule lives in the service layer (risk N.21): a form posts, the service accepts or rejects, and a
rejection becomes an inline error beside the field with the service's own message. Writes are POST only
and answer with a 303 redirect plus a one-shot toast (Post/Redirect/Get, risk N.44). Buttons are shown
from `permissions.allowed` for clarity, but the service stays the real check (risk N.43).
"""

import secrets
import sqlite3
from collections.abc import Callable
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, ValidationError

from acme import auth, idempotency, mail, queries, services
from acme.forms import Form
from acme.models import ApprovalIn, DecisionIn, EmployeeIn, InvoiceIn, ItTicketIn, MailIn, PaymentIn
from acme.money import AMOUNT_HELP, format_inr
from acme.permissions import allowed, role_of
from acme.services import AcmeError, Forbidden, Invalid, NotFound
from acme.web import get_conn, require_login, templates

router = APIRouter()
FLASH_COOKIE = "acme_flash"
CHANNEL = "ui"


def invoice_submit_label() -> str:
    """The invoice form's submit button name. The `rename_submit_button` chaos profile changes it (part 8)."""
    return "Save invoice"


# --- rendering helpers ---------------------------------------------------------------------------


def _context(request: Request, actor: str | None, extra: dict) -> dict:
    flash = request.cookies.get(FLASH_COOKIE)
    return {
        "actor": actor,
        "role": role_of(actor) if actor else None,
        "can": (lambda action: allowed(actor, action)) if actor else (lambda action: False),
        "flash": unquote(flash) if flash else None,
        **extra,
    }


def page(request: Request, template: str, actor: str, http_status: int = 200, **extra) -> Response:
    """`http_status` is positional-friendly; keyword `status` stays free for the list pages' status filter."""
    response = templates.TemplateResponse(request, template, _context(request, actor, extra),
                                          status_code=http_status)
    if request.cookies.get(FLASH_COOKIE):
        response.delete_cookie(FLASH_COOKIE, path="/")  # a toast is shown once
    return response


def go(url: str, message: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(FLASH_COOKIE, quote(message), path="/", httponly=True, samesite="lax")
    return response


def error_page(request: Request, exc: AcmeError | None = None, *, status: int | None = None,
               message: str | None = None) -> Response:
    status = status or (exc.status_code if exc else 400)
    message = message or (exc.message if exc else "Request failed")
    actor = getattr(request.state, "actor", None)
    return templates.TemplateResponse(request, "error.html", _context(request, actor, {"message": message}),
                                      status_code=status)


# --- form helpers --------------------------------------------------------------------------------


def _build(form: Form, model: type[BaseModel], fields: dict, field_map: dict[str, str]) -> BaseModel | None:
    """Build the input model once every field parsed; model-level rules the parsers missed become errors."""
    if form.errors:
        return None
    try:
        return model(**fields)
    except ValidationError as exc:
        form.add_validation_error(exc, field_map)
        return None


def _attempt(form: Form, inputs: set[str], field_map: dict[str, str],
             call: Callable[[], tuple[dict, bool]]) -> tuple[dict | None, bool, int]:
    """Run the write. Returns (row, replayed, status). A rejection is recorded on the form (inline error),
    except 403/404, which are not about any field and go to the error page."""
    try:
        row, replayed = call()
        return row, replayed, 200
    except (Forbidden, NotFound):
        raise
    except AcmeError as exc:
        name = field_map.get(exc.field, exc.field) if exc.field else ""
        form.error(name if name in inputs else "", exc.message)
        return None, False, exc.status_code


def _once(conn: sqlite3.Connection, actor: str, endpoint: str, token: str | None,
          data: BaseModel, write: Callable[[], dict]) -> Callable[[], tuple[dict, bool]]:
    return lambda: idempotency.run(conn, actor, f"{CHANNEL}:{endpoint}", token or "", data, write)


def _plain(write: Callable[[], dict]) -> Callable[[], tuple[dict, bool]]:
    return lambda: (write(), False)


def _raise_if_errors(form: Form) -> None:
    if form.errors:
        raise Invalid("; ".join(form.errors.values()))


def _filter_id(value: str | None, label: str) -> int | None:
    if not value:
        return None
    if not value.isdigit():
        raise Invalid(f"{label} filter is not valid: choose one from the list")
    return int(value)


def _same(values: list[str]) -> list[tuple[str, str]]:
    return [(v, v) for v in values]


def _vendor_options(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [(v["id"], v["name"]) for v in queries.list_vendors(conn)]


def _employee_options(conn: sqlite3.Connection, statuses: tuple[str, ...]) -> list[tuple[int, str]]:
    """Labelled with the email so two people with the same name stay distinguishable."""
    return [(e["id"], f"{e['name']} ({e['email']})") for e in queries.list_employees(conn)
            if e["status"] in statuses]


def _new_token() -> str:
    return secrets.token_urlsafe(16)


# --- home, logout --------------------------------------------------------------------------------


@router.get("/")
def home(request: Request, actor: str = Depends(require_login)) -> Response:
    return page(request, "home.html", actor)


@router.post("/logout")
def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    auth.revoke(conn, request.cookies.get(auth.COOKIE_NAME))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


# --- invoices ------------------------------------------------------------------------------------

INVOICE_FIELDS = {"vendor_id", "invoice_no", "po_number", "invoice_date", "due_date", "received_date",
                  "amount", "tax"}
INVOICE_FIELD_MAP = {"amount_paise": "amount", "tax_paise": "tax"}  # model/service field -> form input


@router.get("/invoices")
def invoices(request: Request, vendor: str | None = None, status: str | None = None,
             conn: sqlite3.Connection = Depends(get_conn), actor: str = Depends(require_login)) -> Response:
    vendor_id = _filter_id(vendor, "Vendor")
    status = queries.valid_status(status, queries.INVOICE_STATUSES)
    return page(request, "invoices.html", actor, rows=queries.list_invoices(conn, vendor_id, status),
                vendor_options=_vendor_options(conn), status_options=_same(queries.INVOICE_STATUSES),
                vendor=vendor_id, status=status)


def _invoice_form(request, conn, actor, values: dict, errors: dict, status: int = 200) -> Response:
    return page(request, "invoice_form.html", actor, status, values=values, errors=errors,
                vendor_options=_vendor_options(conn), submit_label=invoice_submit_label(),
                token=values.get("idempotency_token") or _new_token(), amount_help=AMOUNT_HELP)


@router.get("/invoices/new")
def invoice_new(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                actor: str = Depends(require_login)) -> Response:
    return _invoice_form(request, conn, actor, {}, {})


@router.post("/invoices/new")
async def invoice_create(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                         actor: str = Depends(require_login)) -> Response:
    form = Form(await request.form())
    fields = dict(
        vendor_id=form.integer("vendor_id", "Vendor"),
        invoice_no=form.text("invoice_no", "Invoice number", max_len=40),
        po_number=form.text("po_number", "PO number", required=False, max_len=40),
        invoice_date=form.day("invoice_date", "Invoice date"),
        due_date=form.day("due_date", "Due date"),
        received_date=form.day("received_date", "Received date", required=False),
        amount_paise=form.rupees("amount", "Total including tax"),
        tax_paise=form.rupees("tax", "Tax", allow_zero=True),
    )
    token = form.token()
    data = _build(form, InvoiceIn, fields, INVOICE_FIELD_MAP)
    row, replayed, status = None, False, 422
    if data is not None:
        row, replayed, status = _attempt(form, INVOICE_FIELDS, INVOICE_FIELD_MAP, _once(
            conn, actor, "POST /invoices/new", token, data,
            lambda: services.submit_invoice(conn, actor, CHANNEL, data)))
    if row is None:
        return _invoice_form(request, conn, actor, form.raw, form.errors, status)
    return go(f"/invoices/{row['id']}", _saved("Invoice", row["invoice_no"], row["status"], replayed))


def _saved(kind: str, label: str, status: str, replayed: bool) -> str:
    if replayed:
        return f"{kind} {label} was already saved by an earlier submission of this form; nothing new was created."
    return f"{kind} {label} saved with status {status}."


@router.get("/invoices/{invoice_id}")
def invoice_detail(request: Request, invoice_id: int, conn: sqlite3.Connection = Depends(get_conn),
                   actor: str = Depends(require_login)) -> Response:
    invoice = services.get(conn, "invoice", invoice_id)
    return page(request, "invoice.html", actor, invoice=invoice, vendor=services.get(conn, "vendor", invoice["vendor_id"]),
                payments=queries.list_payments(conn, invoice_id=invoice_id),
                approvals=queries.approvals_for(conn, "invoice", invoice_id),
                can_void=allowed(actor, "invoice.void") and _owns(actor, invoice["created_by"]),
                can_request=allowed(actor, "approval.request") and invoice["status"] == "pending_approval")


def _owns(actor: str, owner: str) -> bool:
    return actor == owner or role_of(actor) == "admin"


@router.post("/invoices/{invoice_id}/void")
def invoice_void(invoice_id: int, conn: sqlite3.Connection = Depends(get_conn),
                 actor: str = Depends(require_login)) -> Response:
    invoice = services.void_invoice(conn, actor, CHANNEL, invoice_id)
    return go(f"/invoices/{invoice_id}", f"Invoice {invoice['invoice_no']} voided.")


@router.post("/invoices/{invoice_id}/request-approval")
async def invoice_request_approval(request: Request, invoice_id: int, conn: sqlite3.Connection = Depends(get_conn),
                                   actor: str = Depends(require_login)) -> Response:
    return await _request_approval(request, conn, actor, "invoice", invoice_id)


async def _request_approval(request, conn, actor, entity_type: str, entity_id: int) -> Response:
    form = Form(await request.form())
    reason = form.text("reason", "Reason", required=False, max_len=500)
    _raise_if_errors(form)
    approval = services.request_approval(conn, actor, CHANNEL, ApprovalIn(
        entity_type=entity_type, entity_id=entity_id, reason=reason))
    return go(f"/approvals/{approval['id']}", f"Approval request {approval['id']} created; it waits for the finance manager.")


# --- approvals -----------------------------------------------------------------------------------


@router.get("/approvals")
def approvals(request: Request, status: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
              actor: str = Depends(require_login)) -> Response:
    status = queries.valid_status(status, queries.APPROVAL_STATUSES)
    return page(request, "approvals.html", actor, rows=queries.list_approvals(conn, status),
                status_options=_same(queries.APPROVAL_STATUSES), status=status)


@router.get("/approvals/{approval_id}")
def approval_detail(request: Request, approval_id: int, conn: sqlite3.Connection = Depends(get_conn),
                    actor: str = Depends(require_login)) -> Response:
    approval = services.get(conn, "approval", approval_id)
    pending = approval["status"] == "pending"
    return page(request, "approval.html", actor, approval=approval,
                label=queries.entity_label(conn, approval["entity_type"], approval["entity_id"]),
                can_decide=pending and allowed(actor, "approval.decide") and approval["requested_by"] != actor,
                can_withdraw=pending and allowed(actor, "approval.withdraw") and _owns(actor, approval["requested_by"]))


@router.post("/approvals/{approval_id}/decide")
async def approval_decide(request: Request, approval_id: int, conn: sqlite3.Connection = Depends(get_conn),
                          actor: str = Depends(require_login)) -> Response:
    form = Form(await request.form())
    decision = form.choice("decision", "Decision", {"approve", "reject"})
    reason = form.text("reason", "Reason", required=False, max_len=500)
    _raise_if_errors(form)
    services.decide_approval(conn, actor, CHANNEL, approval_id, DecisionIn(decision=decision, reason=reason))
    outcome = "approved" if decision == "approve" else "rejected"
    return go(f"/approvals/{approval_id}", f"Approval {approval_id} {outcome}.")


@router.post("/approvals/{approval_id}/withdraw")
def approval_withdraw(approval_id: int, conn: sqlite3.Connection = Depends(get_conn),
                      actor: str = Depends(require_login)) -> Response:
    services.withdraw_approval(conn, actor, CHANNEL, approval_id)
    return go(f"/approvals/{approval_id}", f"Approval request {approval_id} withdrawn.")


# --- payments ------------------------------------------------------------------------------------

PAYMENT_FIELDS = {"invoice_id", "scheduled_date"}


@router.get("/payments")
def payments(request: Request, status: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
             actor: str = Depends(require_login)) -> Response:
    status = queries.valid_status(status, queries.PAYMENT_STATUSES)
    return page(request, "payments.html", actor, rows=queries.list_payments(conn, status=status),
                status_options=_same(queries.PAYMENT_STATUSES), status=status)


def _payment_form(request, conn, actor, values: dict, errors: dict, status: int = 200) -> Response:
    options = [(i["id"], f"{i['invoice_no']} – {i['vendor_name']} – {format_inr(i['amount_paise'])} (#{i['id']})")
               for i in queries.list_invoices(conn, status="approved")]
    return page(request, "payment_form.html", actor, status, values=values, errors=errors, invoice_options=options,
                token=values.get("idempotency_token") or _new_token())


@router.get("/payments/new")
def payment_new(request: Request, invoice_id: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
                actor: str = Depends(require_login)) -> Response:
    return _payment_form(request, conn, actor, {"invoice_id": invoice_id} if invoice_id else {}, {})


@router.post("/payments/new")
async def payment_create(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                         actor: str = Depends(require_login)) -> Response:
    form = Form(await request.form())
    fields = dict(invoice_id=form.integer("invoice_id", "Invoice"),
                  scheduled_date=form.day("scheduled_date", "Scheduled date", required=False))
    token = form.token()
    data = _build(form, PaymentIn, fields, {})
    row, replayed, status = None, False, 422
    if data is not None:
        row, replayed, status = _attempt(form, PAYMENT_FIELDS, {}, _once(
            conn, actor, "POST /payments/new", token, data,
            lambda: services.create_payment(conn, actor, CHANNEL, data)))
    if row is None:
        return _payment_form(request, conn, actor, form.raw, form.errors, status)
    return go(f"/payments/{row['id']}", _saved("Payment request", str(row["id"]), row["status"], replayed))


@router.get("/payments/{payment_id}")
def payment_detail(request: Request, payment_id: int, conn: sqlite3.Connection = Depends(get_conn),
                   actor: str = Depends(require_login)) -> Response:
    payment = services.get(conn, "payment", payment_id)
    return page(request, "payment.html", actor, payment=payment,
                invoice=services.get(conn, "invoice", payment["invoice_id"]),
                approvals=queries.approvals_for(conn, "payment", payment_id),
                can_cancel=allowed(actor, "payment.cancel") and _owns(actor, payment["created_by"]),
                can_request=allowed(actor, "approval.request") and payment["status"] == "pending_approval")


@router.post("/payments/{payment_id}/cancel")
def payment_cancel(payment_id: int, conn: sqlite3.Connection = Depends(get_conn),
                   actor: str = Depends(require_login)) -> Response:
    services.cancel_payment(conn, actor, CHANNEL, payment_id)
    return go(f"/payments/{payment_id}", f"Payment request {payment_id} cancelled.")


@router.post("/payments/{payment_id}/request-approval")
async def payment_request_approval(request: Request, payment_id: int, conn: sqlite3.Connection = Depends(get_conn),
                                   actor: str = Depends(require_login)) -> Response:
    return await _request_approval(request, conn, actor, "payment", payment_id)


# --- vendors (read-only) -------------------------------------------------------------------------


@router.get("/vendors")
def vendors(request: Request, q: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
            actor: str = Depends(require_login)) -> Response:
    return page(request, "vendors.html", actor, rows=queries.list_vendors(conn, q), q=q or "")


@router.get("/vendors/{vendor_id}")
def vendor_detail(request: Request, vendor_id: int, conn: sqlite3.Connection = Depends(get_conn),
                  actor: str = Depends(require_login)) -> Response:
    return page(request, "vendor.html", actor, vendor=services.get(conn, "vendor", vendor_id),
                invoices=queries.list_invoices(conn, vendor_id=vendor_id))


# --- employees and IT tickets --------------------------------------------------------------------

EMPLOYEE_FIELDS = {"name", "email", "role", "department", "manager_id", "start_date"}


@router.get("/employees")
def employees(request: Request, q: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
              actor: str = Depends(require_login)) -> Response:
    return page(request, "employees.html", actor, rows=queries.list_employees(conn, q), q=q or "")


def _employee_form(request, conn, actor, values: dict, errors: dict, status: int = 200) -> Response:
    managers = _employee_options(conn, ("active",))
    return page(request, "employee_form.html", actor, status, values=values, errors=errors, manager_options=managers)


@router.get("/employees/new")
def employee_new(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                 actor: str = Depends(require_login)) -> Response:
    return _employee_form(request, conn, actor, {}, {})


@router.post("/employees/new")
async def employee_create(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                          actor: str = Depends(require_login)) -> Response:
    form = Form(await request.form())
    fields = dict(
        name=form.text("name", "Full name", max_len=100),
        email=form.text("email", "Email", max_len=200),
        role=form.text("role", "Role", max_len=100),
        department=form.text("department", "Department", max_len=100),
        manager_id=form.integer("manager_id", "Manager"),
        start_date=form.day("start_date", "Start date"),
    )
    data = _build(form, EmployeeIn, fields, {})
    row, status = None, 422
    if data is not None:
        row, _, status = _attempt(form, EMPLOYEE_FIELDS, {}, _plain(
            lambda: services.create_employee(conn, actor, CHANNEL, data)))
    if row is None:
        return _employee_form(request, conn, actor, form.raw, form.errors, status)
    return go(f"/employees/{row['id']}", f"Employee {row['name']} created with status {row['status']}.")


@router.get("/employees/{employee_id}")
def employee_detail(request: Request, employee_id: int, conn: sqlite3.Connection = Depends(get_conn),
                    actor: str = Depends(require_login)) -> Response:
    employee = services.get(conn, "employee", employee_id)
    manager = services.get(conn, "employee", employee["manager_id"]) if employee["manager_id"] else None
    return page(request, "employee.html", actor, employee=employee, manager=manager,
                tickets=queries.list_it_tickets(conn, employee_id),
                can_cancel=allowed(actor, "employee.cancel") and employee["status"] == "onboarding")


@router.post("/employees/{employee_id}/cancel")
def employee_cancel(employee_id: int, conn: sqlite3.Connection = Depends(get_conn),
                    actor: str = Depends(require_login)) -> Response:
    services.cancel_employee(conn, actor, CHANNEL, employee_id)
    return go(f"/employees/{employee_id}", f"Onboarding of employee {employee_id} cancelled.")


TICKET_FIELDS = {"type", "employee_id"}


@router.get("/it-tickets")
def it_tickets(request: Request, employee: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
               actor: str = Depends(require_login)) -> Response:
    employee_id = _filter_id(employee, "Employee")
    return page(request, "it_tickets.html", actor, rows=queries.list_it_tickets(conn, employee_id),
                employee_options=_employee_options(conn, ("onboarding", "active")), employee=employee_id)


def _ticket_form(request, conn, actor, values: dict, errors: dict, status: int = 200) -> Response:
    staff = _employee_options(conn, ("onboarding", "active"))
    return page(request, "it_ticket_form.html", actor, status, values=values, errors=errors, staff_options=staff)


@router.get("/it-tickets/new")
def it_ticket_new(request: Request, employee_id: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
                  actor: str = Depends(require_login)) -> Response:
    return _ticket_form(request, conn, actor, {"employee_id": employee_id} if employee_id else {}, {})


@router.post("/it-tickets/new")
async def it_ticket_create(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                           actor: str = Depends(require_login)) -> Response:
    """No idempotency token on purpose: a double submit makes two tickets (register 3.5)."""
    form = Form(await request.form())
    fields = dict(type=form.choice("type", "Type", {"laptop", "accounts"}),
                  employee_id=form.integer("employee_id", "Employee"))
    data = _build(form, ItTicketIn, fields, {})
    row, status = None, 422
    if data is not None:
        row, _, status = _attempt(form, TICKET_FIELDS, {}, _plain(
            lambda: services.create_it_ticket(conn, actor, CHANNEL, data)))
    if row is None:
        return _ticket_form(request, conn, actor, form.raw, form.errors, status)
    return go(f"/it-tickets/{row['id']}", f"IT ticket {row['id']} ({row['type']}) opened.")


@router.get("/it-tickets/{ticket_id}")
def it_ticket_detail(request: Request, ticket_id: int, conn: sqlite3.Connection = Depends(get_conn),
                     actor: str = Depends(require_login)) -> Response:
    ticket = services.get(conn, "it_ticket", ticket_id)
    return page(request, "it_ticket.html", actor, ticket=ticket,
                employee=services.get(conn, "employee", ticket["employee_id"]),
                can_cancel=allowed(actor, "it_ticket.cancel") and ticket["status"] == "open")


@router.post("/it-tickets/{ticket_id}/cancel")
def it_ticket_cancel(ticket_id: int, conn: sqlite3.Connection = Depends(get_conn),
                     actor: str = Depends(require_login)) -> Response:
    services.cancel_it_ticket(conn, actor, CHANNEL, ticket_id)
    return go(f"/it-tickets/{ticket_id}", f"IT ticket {ticket_id} cancelled.")


# --- mail ----------------------------------------------------------------------------------------

MAIL_FIELDS = {"to", "subject", "body"}


@router.get("/mail")
def mail_list(request: Request, folder: str | None = None, conn: sqlite3.Connection = Depends(get_conn),
              actor: str = Depends(require_login)) -> Response:
    folder = queries.valid_folder(folder)
    return page(request, "mails.html", actor, rows=queries.list_mail(conn, folder), folder=folder)


def _mail_form(request, conn, actor, values: dict, errors: dict, status: int = 200) -> Response:
    return page(request, "mail_form.html", actor, status, values=values, errors=errors,
                token=values.get("idempotency_token") or _new_token())


@router.get("/mail/compose")
def mail_compose(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                 actor: str = Depends(require_login)) -> Response:
    return _mail_form(request, conn, actor, {}, {})


@router.post("/mail/compose")
async def mail_send(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                    actor: str = Depends(require_login)) -> Response:
    form = Form(await request.form())
    fields = dict(to=form.text("to", "Recipient", max_len=200), subject=form.text("subject", "Subject", max_len=200),
                  body=form.text("body", "Message", max_len=5000))
    token = form.token()
    data = _build(form, MailIn, fields, {})
    row, replayed, status = None, False, 422
    if data is not None:
        row, replayed, status = _attempt(form, MAIL_FIELDS, {}, _once(
            conn, actor, "POST /mail/compose", token, data,
            lambda: services.send_mail(conn, actor, CHANNEL, data)))
    if row is None:
        return _mail_form(request, conn, actor, form.raw, form.errors, status)
    if replayed:
        message = f"Mail {row['id']} was already sent by an earlier submission of this form; nothing new was sent."
    else:
        message = f"Mail {row['id']} sent to {row['to_addr']}" + (" (external recipient)." if row["external"] else ".")
    return go(f"/mail/{row['id']}", message)


@router.get("/mail/{mail_id}")
def mail_detail(request: Request, mail_id: int, conn: sqlite3.Connection = Depends(get_conn),
                actor: str = Depends(require_login)) -> Response:
    return page(request, "mail.html", actor, mail=mail.view(services.get(conn, "mail", mail_id)))

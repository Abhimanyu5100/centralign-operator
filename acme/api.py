"""Acme's JSON API, the "official" channel (part 4). Routes only parse, call `services` / `queries`, and wrap.

Every response is typed: `{ok, error_type, detail, data}`; errors come from `AcmeError` through the app's
handlers, with `error_type` from `web.ERROR_TYPES` (risk N.50). Every write goes through `_write`, which:
- parses the JSON body strictly (no `true` -> 1, no `"6240000"` -> int, no unknown fields such as `actor`;
  risks N.51, N.34) and requires `application/json` when there is a body (415 otherwise, register 0.10);
- for invoices and payments, requires an `Idempotency-Key` header and runs the write through the shared
  store `idempotency.run` (endpoint "api:POST /api/invoices"), replaying the original status and body with
  `Idempotent-Replayed: true` (risks 3.5, N.45, N.52);
- calls the service with `channel="api"` and the session actor only.
`_write` is also the single place the chaos profiles enter API writes (`chaos.before_write` / `after_write`,
risk N.55): after the body is parsed and before anything is written.
"""

import hashlib
import sqlite3
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from acme import chaos, idempotency, mail, queries, services
from acme.models import ApprovalIn, DecisionIn, EmployeeIn, InvoiceIn, ItTicketIn, MailIn, PaymentIn
from acme.services import Invalid, MalformedBody, NotFound, UnsupportedMediaType
from acme.web import get_conn, pdf_response, require_login

router = APIRouter()
CHANNEL = "api"
AUDIT_DEFAULT_LIMIT, AUDIT_MAX_LIMIT = 500, 1000


def ok(data: dict, status: int = 200, detail: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "error_type": None, "detail": detail, "data": data}, status_code=status)


async def _body(request: Request, model: type[BaseModel]) -> BaseModel:
    content_type = request.headers.get("content-type", "")
    if not content_type.split(";")[0].strip() == "application/json":
        raise UnsupportedMediaType("Send the body as JSON with Content-Type: application/json")
    raw = await request.body()
    try:
        return model.model_validate_json(raw or b"", strict=True)
    except ValidationError as exc:
        errors = exc.errors()
        if any(e["type"] in ("json_invalid", "model_type", "json_type") for e in errors):
            raise MalformedBody("Body must be a JSON object") from exc
        first = errors[0]
        field = ".".join(str(part) for part in first["loc"]) or None
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)
        raise Invalid(detail, field) from exc


async def _write(request: Request, conn: sqlite3.Connection, actor: str, service: Callable[..., dict],
                 *args, model: type[BaseModel] | None = None, idempotent: bool = False,
                 status: int = 200, detail: str = "") -> JSONResponse:
    """`service(conn, actor, "api", *args[, body])`. See the module docstring for the guarantees."""
    key = request.headers.get("idempotency-key", "")
    if idempotent and not key:
        raise idempotency.KeyRequired("This endpoint needs an Idempotency-Key header (any unique string per "
                                      "intended write; reuse it only to retry the same write)", "idempotency_key")
    body = await _body(request, model) if model is not None else None
    call_args = (*args, body) if body is not None else args
    route = request.scope["route"].path
    attempt = chaos.before_write(conn, actor, CHANNEL, request.method, route, request.url.path,
                                 key or hashlib.sha256(await request.body()).hexdigest())

    def write() -> dict:
        return service(conn, actor, CHANNEL, *call_args)

    if idempotent:
        endpoint = f"{CHANNEL}:{request.method} {route}"
        row, replayed = idempotency.run(conn, actor, endpoint, key, body, write)
    else:
        row, replayed = write(), False
    response = ok(row, status, detail)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    await chaos.after_write(conn, attempt, committed=not replayed)
    return response


# --- reads ---------------------------------------------------------------------------------------


@router.get("/api/vendors")
def vendors(q: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok({"items": queries.list_vendors(conn, q)})


@router.get("/api/vendors/{vendor_id}")
def vendor(vendor_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(services.get(conn, "vendor", vendor_id))


@router.get("/api/invoices")
def invoices(vendor: int | None = Query(None, ge=1, description="vendor id; resolve a name via /api/vendors?q="),
             status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    status = queries.valid_status(status, queries.INVOICE_STATUSES)
    return ok({"items": queries.list_invoices(conn, vendor, status)})


@router.get("/api/invoices/{invoice_id}")
def invoice(invoice_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    row = services.get(conn, "invoice", invoice_id)
    row["vendor_name"] = services.get(conn, "vendor", row["vendor_id"])["name"]
    row["approvals"] = queries.approvals_for(conn, "invoice", invoice_id)
    row["payments"] = queries.list_payments(conn, invoice_id=invoice_id)
    return ok(row)


@router.get("/api/approvals")
def approvals(status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    status = queries.valid_status(status, queries.APPROVAL_STATUSES)
    return ok({"items": queries.list_approvals(conn, status)})


@router.get("/api/approvals/{approval_id}")
def approval(approval_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(services.get(conn, "approval", approval_id))


@router.get("/api/payments")
def payments(invoice: int | None = Query(None, ge=1), status: str | None = None,
             conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    status = queries.valid_status(status, queries.PAYMENT_STATUSES)
    return ok({"items": queries.list_payments(conn, invoice, status)})


@router.get("/api/payments/{payment_id}")
def payment(payment_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    row = services.get(conn, "payment", payment_id)
    row["approvals"] = queries.approvals_for(conn, "payment", payment_id)
    return ok(row)


@router.get("/api/employees")
def employees(q: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok({"items": queries.list_employees(conn, q)})


@router.get("/api/employees/{employee_id}")
def employee(employee_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(services.get(conn, "employee", employee_id))


@router.get("/api/it-tickets")
def it_tickets(employee: int | None = Query(None, ge=1), conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok({"items": queries.list_it_tickets(conn, employee)})


@router.get("/api/it-tickets/{ticket_id}")
def it_ticket(ticket_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(services.get(conn, "it_ticket", ticket_id))


@router.get("/api/mail")
def mail_list(folder: str | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    """`folder=inbox` (default) or `outbox`; summaries only, read one message for its body."""
    return ok({"items": queries.list_mail(conn, queries.valid_folder(folder))})


@router.get("/api/mail/{mail_id}/attachments/{name}")
def mail_attachment(mail_id: int, name: str, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if name not in mail.view(services.get(conn, "mail", mail_id))["attachments"]:
        raise NotFound("File not found")
    return pdf_response(name)


@router.get("/api/files/{name}")
def file_download(name: str) -> Response:
    return pdf_response(name)


@router.get("/api/mail/{mail_id}")
def mail_detail(mail_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(mail.view(services.get(conn, "mail", mail_id)))


@router.get("/api/audit")
def audit(since: int = Query(0, ge=0, description="return entries with an audit id greater than this"),
          limit: int = Query(AUDIT_DEFAULT_LIMIT, ge=1, le=AUDIT_MAX_LIMIT),
          conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    """Read-only, every logged-in role. Page with `next_since` while `has_more` is true (risk N.53)."""
    rows = queries.audit_since(conn, since, limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return ok({"items": rows, "has_more": has_more, "next_since": rows[-1]["id"] if rows else since})


# --- writes --------------------------------------------------------------------------------------


@router.post("/api/invoices")
async def submit_invoice(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                         actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.submit_invoice, model=InvoiceIn, idempotent=True,
                        status=201, detail="invoice submitted")


@router.post("/api/payments")
async def create_payment(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                         actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.create_payment, model=PaymentIn, idempotent=True,
                        status=201, detail="payment request created")


@router.post("/api/approvals")
async def request_approval(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                           actor: str = Depends(require_login)) -> JSONResponse:
    """No idempotency key on purpose (register 3.5): read back before retrying."""
    return await _write(request, conn, actor, services.request_approval, model=ApprovalIn,
                        status=201, detail="approval requested")


@router.post("/api/employees")
async def create_employee(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                          actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.create_employee, model=EmployeeIn,
                        status=201, detail="employee created")


@router.post("/api/it-tickets")
async def create_it_ticket(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                           actor: str = Depends(require_login)) -> JSONResponse:
    """No idempotency key on purpose (register 3.5): read back before retrying."""
    return await _write(request, conn, actor, services.create_it_ticket, model=ItTicketIn,
                        status=201, detail="IT ticket created")


@router.post("/api/mail/send")
async def send_mail(request: Request, conn: sqlite3.Connection = Depends(get_conn),
                    actor: str = Depends(require_login)) -> JSONResponse:
    """Needs an Idempotency-Key (sent mail cannot be undone, register 3.5). `external` is computed, never sent."""
    return await _write(request, conn, actor, services.send_mail, model=MailIn, idempotent=True,
                        status=201, detail="mail sent")


@router.post("/api/approvals/{approval_id}/decide")
async def decide_approval(request: Request, approval_id: int, conn: sqlite3.Connection = Depends(get_conn),
                          actor: str = Depends(require_login)) -> JSONResponse:
    """Business approver only (`meera`); `ops-agent` gets 403 from the service."""
    return await _write(request, conn, actor, services.decide_approval, approval_id, model=DecisionIn,
                        detail="approval decided")


# --- undo (compensating actions, register 7.3) ----------------------------------------------------


@router.post("/api/invoices/{invoice_id}/void")
async def void_invoice(request: Request, invoice_id: int, conn: sqlite3.Connection = Depends(get_conn),
                       actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.void_invoice, invoice_id, detail="invoice voided")


@router.post("/api/approvals/{approval_id}/withdraw")
async def withdraw_approval(request: Request, approval_id: int, conn: sqlite3.Connection = Depends(get_conn),
                            actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.withdraw_approval, approval_id, detail="approval withdrawn")


@router.post("/api/payments/{payment_id}/cancel")
async def cancel_payment(request: Request, payment_id: int, conn: sqlite3.Connection = Depends(get_conn),
                         actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.cancel_payment, payment_id, detail="payment cancelled")


@router.post("/api/employees/{employee_id}/cancel")
async def cancel_employee(request: Request, employee_id: int, conn: sqlite3.Connection = Depends(get_conn),
                          actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.cancel_employee, employee_id, detail="onboarding cancelled")


@router.post("/api/it-tickets/{ticket_id}/cancel")
async def cancel_it_ticket(request: Request, ticket_id: int, conn: sqlite3.Connection = Depends(get_conn),
                           actor: str = Depends(require_login)) -> JSONResponse:
    return await _write(request, conn, actor, services.cancel_it_ticket, ticket_id, detail="IT ticket cancelled")

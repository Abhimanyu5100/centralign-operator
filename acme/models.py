"""Input models for Acme writes. Both channels parse into these, so field validation is identical
for the UI form and the API body (risk N.21). Business rules that need the database or the clock
(duplicates, dates vs today, status checks) live in `services.py`.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InvoiceIn(_In):
    vendor_id: int
    invoice_no: str = Field(min_length=1, max_length=40)
    po_number: str | None = Field(default=None, max_length=40)
    invoice_date: date
    due_date: date
    received_date: date | None = None  # defaults to Acme's today
    amount_paise: int = Field(gt=0, description="Invoice total including tax, in paise")
    tax_paise: int = Field(ge=0, description="Tax part of the total (informational), in paise")


class ApprovalIn(_In):
    entity_type: Literal["invoice", "payment"]
    entity_id: int
    approver_role: Literal["finance_manager"] = "finance_manager"
    reason: str | None = Field(default=None, max_length=500)


class DecisionIn(_In):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class PaymentIn(_In):
    invoice_id: int
    scheduled_date: date | None = None  # defaults to the due date, or today if that has passed


class EmployeeIn(_In):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    role: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)
    manager_id: int
    start_date: date


class ItTicketIn(_In):
    type: Literal["laptop", "accounts"]
    employee_id: int

"""Who may do what in Acme. One table, checked inside the service layer (risk N.22).

Routers never check roles themselves, so a forgotten route cannot skip the check.
Users live here, in code, with no users table (D-043). Passwords come from the environment (`auth.py`).
"""

USER_ROLES: dict[str, str] = {
    "ops-agent": "ops_agent",   # the agent's service account (AP clerk + HR assistant)
    "meera": "finance_manager",  # the human business approver
    "admin": "admin",
    "system": "system",          # Acme itself, e.g. the ORG-001 auto-approval
}

# Accounts that can log in. `system` is Acme acting on itself and has no password.
LOGIN_USERS: tuple[str, ...] = tuple(u for u in USER_ROLES if u != "system")

ACTION_ROLES: dict[str, set[str]] = {
    "invoice.submit": {"ops_agent", "admin"},
    "invoice.void": {"ops_agent", "admin"},  # plus: creator only (checked in the service)
    "approval.request": {"ops_agent", "admin"},
    "approval.withdraw": {"ops_agent", "admin"},  # plus: requester only
    "approval.decide": {"finance_manager", "admin"},
    "payment.create": {"ops_agent", "admin"},
    "payment.cancel": {"ops_agent", "admin"},  # plus: creator only
    "employee.create": {"ops_agent", "admin"},
    "employee.cancel": {"ops_agent", "admin"},
    "it_ticket.create": {"ops_agent", "admin"},
    "it_ticket.cancel": {"ops_agent", "admin"},
    "vendor.update_bank": {"admin"},
    "status.set": {"admin"},  # direct status changes (e.g. payment -> sent): admin/harness only
}


def role_of(actor: str) -> str | None:
    return USER_ROLES.get(actor)


def allowed(actor: str, action: str) -> bool:
    if action not in ACTION_ROLES:
        raise KeyError(f"unknown action {action!r}")  # fail closed on typos
    return role_of(actor) in ACTION_ROLES[action]

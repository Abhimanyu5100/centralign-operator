import pytest
from fastapi.testclient import TestClient

from acme import services as s
from acme.app import create_app
from acme.db import connect
from acme.models import ApprovalIn, EmployeeIn, ItTicketIn, PaymentIn
from acme.seed import reset


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "acme.db")
    reset(connection, "base")
    yield connection
    connection.close()


@pytest.fixture
def make_conn(tmp_path):
    """Connection reset to a chosen seed: make_conn("t9")."""
    opened = []

    def _make(seed: str = "base", now: str | None = None):
        connection = connect(tmp_path / f"acme-{len(opened)}.db")
        reset(connection, seed, *([now] if now else []))
        opened.append(connection)
        return connection

    yield _make
    for connection in opened:
        connection.close()


# --- app-level fixtures shared by the UI and API tests (states built through services only, N.28) ---

PASSWORDS = {"ops-agent": "ops-agent-dev-pw", "meera": "meera-dev-pw"}


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "acme.db"
    conn = connect(path)
    reset(conn, "base")
    conn.close()
    return path


@pytest.fixture
def db(db_file):
    conn = connect(db_file)
    yield conn
    conn.close()


@pytest.fixture
def world(db):
    """A pending over-limit invoice with an approval, an approved invoice with a payment request,
    an onboarding employee with an IT ticket. Everything created by ops-agent through the service layer."""
    from tests.acme.test_services import invoice_in
    over = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-9001", amount_paise=6_240_000))
    approval = s.request_approval(db, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=over["id"]))
    ok = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-9002"))
    payment = s.create_payment(db, "ops-agent", "api", PaymentIn(invoice_id=ok["id"]))
    employee = s.create_employee(db, "ops-agent", "api", EmployeeIn(
        name="Test Person", email="test.person@acme.example", role="Analyst", department="Finance",
        manager_id=1, start_date="2026-10-12"))
    ticket = s.create_it_ticket(db, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=employee["id"]))
    return dict(over=over, approval=approval, ok=ok, payment=payment, employee=employee, ticket=ticket)


def make_client(db_file, user: str | None, raise_server_exceptions: bool = True) -> TestClient:
    client = TestClient(create_app(db_file), follow_redirects=False, raise_server_exceptions=raise_server_exceptions)
    if user:
        assert client.post("/api/login", json={"username": user, "password": PASSWORDS[user]}).status_code == 200
    return client


@pytest.fixture
def agent(db_file):
    return make_client(db_file, "ops-agent")


@pytest.fixture
def meera(db_file):
    return make_client(db_file, "meera")

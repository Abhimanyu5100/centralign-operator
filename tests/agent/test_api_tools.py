"""The generated Acme API tools against the real Acme app in-process: login, typed errors, retries with
read-before-retry (3.5, N.129, N.130, N.133), session expiry (3.4), timeouts as results (N.132), provenance (4.7),
downloads into the run's scratch folder (N.137) and idempotency keys (N.131)."""

import httpx

from agent.tools.api import load_catalog
from tests.agent.acme_fixtures import CONFIG, Fault, drive, sandbox  # noqa: F401  (sandbox is a fixture)
from tests.agent.agent_fixtures import FixedGate

INVOICE = {"vendor_id": 2, "invoice_no": "TEST-77", "po_number": "PO-TEST-1", "invoice_date": "2026-10-01",
           "due_date": "2026-11-01", "amount_paise": 1_234_500, "tax_paise": 100_000}
TICKETS = "/api/it-tickets"


def _employee(sandbox) -> int:
    """An onboarding employee created through the tool (states built through Acme, never raw INSERTs)."""
    async def body(run):
        result = await run.call("create_employee", {
            "name": "Test Person", "email": "test.person@acme.example", "role": "Analyst",
            "department": "Finance", "manager_id": 1, "start_date": "2026-10-12"})
        assert result.ok, result
        return result.data["id"]
    return drive(sandbox.run(), body)


def _count(sandbox, sql, *params) -> int:
    return sandbox.rows(sql, *params)[0][0]


# --- reads, login, typed errors -------------------------------------------------------------------------------

def test_a_read_logs_in_once_and_returns_acme_data(sandbox):
    transport = sandbox.faults()

    async def body(run):
        return [await run.call("find_vendors", {"q": "Rao"}), await run.call("get_vendor", {"vendor_id": 2})]
    found, one = drive(sandbox.run(transport), body)
    assert found.ok and [v["id"] for v in found.data["items"]] == [2]
    assert one.ok and one.data["id"] == 2
    assert transport.calls("POST", "/api/login") == 1


def test_a_business_refusal_passes_through_unchanged_after_one_request(sandbox):
    transport = sandbox.faults()

    async def body(run):
        return await run.call("submit_invoice", {**INVOICE, "vendor_id": 1, "invoice_no": "INV-1012"})
    result = drive(sandbox.run(transport), body)
    assert (result.ok, result.error_type, result.data["http_status"]) == (False, "conflict", 409)
    assert result.data["field"] == "invoice_no" and "Duplicate" in result.detail
    assert transport.calls("POST", "/api/invoices") == 1


def test_a_client_timeout_is_a_timeout_result_not_a_crash(sandbox):
    transport = sandbox.faults(Fault("GET", "/api/vendors", "before"))
    result = drive(sandbox.run(transport), lambda run: run.call("find_vendors", {}))
    assert (result.ok, result.error_type) == (False, "timeout")


def test_a_connection_failure_is_a_connection_error(sandbox):
    transport = sandbox.faults(Fault("GET", "/api/vendors", "before", error=httpx.ConnectError))
    result = drive(sandbox.run(transport), lambda run: run.call("find_vendors", {}))
    assert result.error_type == "connection_error"


def test_a_missing_password_is_a_typed_failure(sandbox):
    from agent.lifecycle import start_run
    from tests.agent.agent_fixtures import NOW
    run = start_run("r", NOW, store=sandbox.store, config={**CONFIG, "ACME_PASSWORD_OPS_AGENT": ""},
                    transport=httpx.ASGITransport(app=sandbox.app))
    result = drive(run, lambda run: run.call("find_vendors", {}))
    assert result.error_type == "invalid_credentials" and "ACME_PASSWORD_OPS_AGENT" in result.detail


def test_the_gate_sees_the_real_method_and_path(sandbox):
    gate = FixedGate()
    from agent.lifecycle import start_run
    from tests.agent.agent_fixtures import NOW
    run = start_run("r", NOW, store=sandbox.store, config=CONFIG, gate=gate,
                    transport=httpx.ASGITransport(app=sandbox.app))
    drive(run, lambda run: run.call("void_invoice", {"invoice_id": 4}))
    assert (gate.seen[0].request.method, gate.seen[0].request.path) == ("POST", "/api/invoices/4/void")


# --- keyed writes: the same key on retry, Acme replays -------------------------------------------------------

def test_a_keyed_write_that_committed_before_a_timeout_is_replayed_not_duplicated(sandbox):
    transport = sandbox.faults(Fault("POST", "/api/invoices", "after"))
    result = drive(sandbox.run(transport), lambda run: run.call("submit_invoice", INVOICE))
    assert result.ok and result.data["already_done"] is True
    assert result.data["attempts"] == ["attempt 1: timeout", "attempt 2: replayed by Acme"]
    assert _count(sandbox, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'TEST-77'") == 1
    keys = {r.headers["idempotency-key"] for r in transport.requests if r.url.path == "/api/invoices"}
    assert len(keys) == 1


def test_the_derived_key_is_stable_within_a_run_and_differs_between_runs(sandbox):
    first, second = sandbox.faults(), sandbox.faults()

    async def twice(run):
        return [await run.call("send_mail", {"to": "x@acme.example", "subject": "s", "body": "b"}) for _ in range(2)]
    results = drive(sandbox.run(first), twice)
    assert [r.data["already_done"] for r in results] == [False, True]  # same intended write: replayed (N.131)
    drive(sandbox.run(second), twice)
    key = lambda t: {r.headers["idempotency-key"] for r in t.requests if r.method == "POST" and "send" in r.url.path}
    assert len(key(first)) == 1 and len(key(second)) == 1 and key(first) != key(second)
    assert _count(sandbox, "SELECT COUNT(*) FROM mail WHERE folder = 'outbox'") == 2


def test_an_explicit_key_makes_a_second_identical_write(sandbox):
    async def body(run):
        mail = {"to": "x@acme.example", "subject": "s", "body": "b"}
        return [await run.call("send_mail", {**mail, "idempotency_key": k}) for k in ("one", "two")]
    assert all(r.ok and not r.data["already_done"] for r in drive(sandbox.run(), body))
    assert _count(sandbox, "SELECT COUNT(*) FROM mail WHERE folder = 'outbox'") == 2


# --- keyless writes: read back before any retry --------------------------------------------------------------

def test_a_keyless_write_that_committed_before_a_timeout_is_found_by_read_back(sandbox):
    employee = _employee(sandbox)
    transport = sandbox.faults(Fault("POST", TICKETS, "after"))
    result = drive(sandbox.run(transport), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["already_done"] is True and result.data["status"] == "open"
    assert transport.calls("POST", TICKETS) == 1  # no second POST
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 1


def test_a_keyless_write_that_did_not_commit_is_retried_once(sandbox):
    employee = _employee(sandbox)
    transport = sandbox.faults(Fault("POST", TICKETS, "before"))
    result = drive(sandbox.run(transport), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["already_done"] is False
    assert result.data["attempts"] == ["attempt 1: timeout", "read-back: not written; retrying", "attempt 2: ok"]
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 1


def test_a_row_that_matched_before_the_write_is_never_mistaken_for_it(sandbox):
    employee = _employee(sandbox)
    drive(sandbox.run(), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    transport = sandbox.faults(Fault("POST", TICKETS, "before"))  # an older open laptop ticket exists (N.129)
    result = drive(sandbox.run(transport), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["already_done"] is False
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 2


def test_an_unknown_outcome_is_remembered_so_the_next_identical_call_reads_back_first(sandbox):
    employee = _employee(sandbox)
    transport = sandbox.faults(Fault("POST", TICKETS, "before"), Fault("POST", TICKETS, "after", nth=2))
    args = {"type": "accounts", "employee_id": employee}

    async def body(run):
        return [await run.call("create_it_ticket", args), await run.call("create_it_ticket", args)]
    first, second = drive(sandbox.run(transport), body)
    assert (first.ok, first.error_type, first.data["outcome_unknown"]) == (False, "timeout", True)
    assert second.ok and second.data["already_done"] is True  # N.130
    assert transport.calls("POST", TICKETS) == 2
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 1


def test_a_failed_read_back_means_no_retry(sandbox):
    employee = _employee(sandbox)
    # the 1st GET is the read before writing, the 2nd the read-back after the timeout
    transport = sandbox.faults(Fault("POST", TICKETS, "before"), Fault("GET", TICKETS, "before", nth=2))
    result = drive(sandbox.run(transport), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.error_type == "timeout" and result.data["attempts"][-1] == "read-back failed; not retried"
    assert transport.calls("POST", TICKETS) == 1


def test_a_failed_read_before_writing_writes_nothing(sandbox):
    employee = _employee(sandbox)
    transport = sandbox.faults(Fault("GET", TICKETS, "before"))
    result = drive(sandbox.run(transport), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert not result.ok and "nothing written" in result.detail
    assert transport.calls("POST", TICKETS) == 0


def test_an_undo_already_in_effect_is_already_done_without_a_write(sandbox):
    async def body(run):
        invoice = await run.call("submit_invoice", INVOICE)
        first = await run.call("void_invoice", {"invoice_id": invoice.data["id"]})
        return first, await run.call("void_invoice", {"invoice_id": invoice.data["id"]})
    transport = sandbox.faults()
    first, second = drive(sandbox.run(transport), body)
    assert first.ok and not first.data["already_done"] and first.data["status"] == "void"
    assert second.ok and second.data["already_done"] is True
    assert sum(1 for r in transport.requests if r.url.path.endswith("/void")) == 1


# --- chaos inside Acme ----------------------------------------------------------------------------------------

def test_flaky_500_leaves_exactly_one_row_per_write(sandbox):
    sandbox.admin_call("POST", "/__admin/chaos", profile="flaky_500", seed=0)  # attempts 1 and 2 fail

    async def body(run):
        invoice = await run.call("submit_invoice", {**INVOICE, "amount_paise": 9_000_000})
        approval = await run.call("request_approval", {"entity_type": "invoice", "entity_id": invoice.data["id"]})
        return invoice, approval
    invoice, approval = drive(sandbox.run(), body)
    assert invoice.ok and invoice.data["attempts"] == ["attempt 1: server_error", "attempt 2: ok"]
    assert approval.ok and approval.data["attempts"][-1] == "attempt 2: ok"
    assert _count(sandbox, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'TEST-77'") == 1
    assert _count(sandbox, "SELECT COUNT(*) FROM approvals WHERE entity_id = ?", invoice.data["id"]) == 1


def test_an_expired_session_on_a_read_logs_in_again_once(sandbox):
    sandbox.admin_call("POST", "/__admin/chaos", profile="session_expiry_at_step_1", seed=0)
    transport = sandbox.faults()

    async def body(run):
        return [await run.call("find_vendors", {}), await run.call("find_vendors", {"q": "Rao"})]
    first, second = drive(sandbox.run(transport), body)
    assert first.ok and second.ok and [v["id"] for v in second.data["items"]] == [2]
    assert transport.calls("POST", "/api/login") == 2


def test_an_expired_session_on_a_write_logs_in_reads_back_and_writes_once(sandbox):
    employee = _employee(sandbox)
    sandbox.admin_call("POST", "/__admin/chaos", profile="session_expiry_at_step_1", seed=0)
    # request 1 is the read before writing; request 2, the POST, finds the session gone
    result = drive(sandbox.run(), lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["attempts"] == [
        "attempt 1: session_expired", "logged in again", "read-back: not written; retrying", "attempt 2: ok"]
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 1


# --- provenance and files -------------------------------------------------------------------------------------

def test_mail_text_carries_untrusted_provenance(sandbox):
    async def body(run):
        listing = await run.call("list_mail", {})
        return listing, await run.call("read_mail", {"mail_id": listing.data["items"][0]["id"]})
    listing, mail = drive(sandbox.run(), body)
    assert listing.data["provenance"] == {"source": "untrusted", "origin": "mailbox"}
    assert mail.data["provenance"] == {"source": "untrusted", "origin": f"mail:{mail.data['id']}"}
    assert mail.data["body"]


def test_a_downloaded_pdf_is_extracted_with_provenance(sandbox):
    async def body(run):
        files = await run.call("list_files", {})
        name = files.data["items"][0]["name"]
        early = await run.call("extract_pdf_text", {"name": name})
        saved = await run.call("download_file", {"name": name})
        return run, name, early, saved, await run.call("extract_pdf_text", {"name": name})
    run, name, early, saved, text = drive(sandbox.run(), body)
    assert early.error_type == "precondition_failed" and "download" in early.detail
    assert saved.ok and saved.data["bytes"] > 0 and (sandbox.store.path.parent / run.run_id / "files" / name).is_file()
    assert text.ok and "TAX INVOICE" in text.data["text"]
    assert text.data["provenance"] == {"source": "untrusted", "origin": f"file:{name}"}


def test_a_scanned_pdf_gives_empty_text_and_says_so(sandbox):
    async def body(run):
        await run.call("download_file", {"name": "iyer_INV-3301.pdf"})
        return await run.call("extract_pdf_text", {"name": "iyer_INV-3301.pdf"})
    result = drive(sandbox.run(), body)
    assert result.ok and result.data["no_text_layer"] is True and result.data["text"] == ""


def test_a_file_name_cannot_leave_the_scratch_folder(sandbox):
    result = drive(sandbox.run(), lambda run: run.call("download_file", {"name": "../../escape.pdf"}))
    assert result.error_type == "invalid_args"


def test_the_password_never_reaches_the_run_log(sandbox):
    run = sandbox.run()
    drive(run, lambda run: run.call("find_vendors", {}))
    assert "test-agent-password" not in str(sandbox.store.events(run.run_id))


def test_the_catalog_names_every_tool_the_registry_holds(sandbox):
    run = sandbox.run()
    assert {s.name for s in run.registry.specs()} == {e.name for e in load_catalog().tools} | {"extract_pdf_text", "browser_open", "browser_observe", "browser_click", "browser_fill", "browser_select",
        "ask_user", "declare_infeasible"}



# --- read lag: an unknown outcome is read back for the read-lag window before "not written" (D-123, N.141) --------

def _delayed(sandbox, monkeypatch, seconds: str = "1"):
    monkeypatch.setenv("ACME_CHAOS_VISIBILITY_SECONDS", seconds)
    sandbox.admin_call("POST", "/__admin/chaos", profile="delayed_write", seed=0)


def test_a_lagged_row_is_found_by_polling_and_not_written_twice(sandbox, monkeypatch):
    employee = _employee(sandbox)
    _delayed(sandbox, monkeypatch)
    transport = sandbox.faults(Fault("POST", TICKETS, "after"))  # committed, the client hears a timeout
    run = sandbox.run(transport)
    run.client.read_lag = 3.0
    result = drive(run, lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["already_done"] is True
    assert transport.calls("POST", TICKETS) == 1 and transport.calls("GET", TICKETS) >= 3  # polled through the lag
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 1


def test_without_waiting_out_the_lag_the_same_case_would_write_twice(sandbox, monkeypatch):
    """The mechanism matters: with no read-lag window the read-back misses the hidden row and sends again."""
    employee = _employee(sandbox)
    _delayed(sandbox, monkeypatch)
    transport = sandbox.faults(Fault("POST", TICKETS, "after"))
    run = sandbox.run(transport)
    run.client.read_lag = 0.0
    drive(run, lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert transport.calls("POST", TICKETS) == 2
    assert _count(sandbox, "SELECT COUNT(*) FROM it_tickets WHERE employee_id = ?", employee) == 2


def test_a_session_loss_is_retried_without_waiting_for_the_read_lag(sandbox):
    """A 401 means Acme wrote nothing: re-login, read back without waiting, retry. Only an unknown outcome waits."""
    import time
    from agent.tools.api import Reply
    from agent.tools.registry import ToolResult
    employee = _employee(sandbox)
    run = sandbox.run()
    run.client.read_lag = 30.0  # the test would take 30 s if a 401 waited out the lag
    send, lost = run.client._send, []

    async def first_post_loses_the_session(method, path, **kwargs):
        if method == "POST" and path == TICKETS and not lost:
            lost.append(path)
            return Reply(ToolResult.fail("session_expired", "Session expired"))
        return await send(method, path, **kwargs)
    run.client._send = first_post_loses_the_session
    started = time.perf_counter()
    result = drive(run, lambda run: run.call("create_it_ticket", {"type": "laptop", "employee_id": employee}))
    assert result.ok and result.data["attempts"][:2] == ["attempt 1: session_expired", "logged in again"]
    assert time.perf_counter() - started < 10


def test_the_default_read_lag_is_longer_than_acmes_longest_read_lag():
    from acme import chaos
    from agent.tools.api import DEFAULT_READ_LAG_SECONDS
    assert DEFAULT_READ_LAG_SECONDS > chaos.DEFAULT_VISIBILITY_SECONDS

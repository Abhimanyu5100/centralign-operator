"""The browser tools against a real Acme server and a real Chromium (Day 2.3): the observation shows every control
(4.1, N.127), a changed page refuses a click (N.126), GUI session expiry (3.4), post-action capture under
`toast_2s` (4.3), a slow write surfaces as `timeout` (N.139), and the T1 GUI oracle with chaos off and on."""

import asyncio
import re
import sqlite3
from datetime import datetime

import pytest

from agent.lifecycle import start_run
from agent.tools.browser import MAX_VIEW_CHARS
from bench import tasks
from bench.live import run_oracle, serve
from bench.oracles import oracle_for, ref

pytestmark = pytest.mark.e2e

NOW = "2026-10-07T10:30:00+05:30"
BIG = {"vendor_id": 1, "invoice_no": "GUI-1", "invoice_date": "2026-10-01", "due_date": "2026-11-01",
       "amount_paise": 9_000_000, "tax_paise": 0}


@pytest.fixture(scope="module")
def acme():
    with serve(env={"ACME_CHAOS_SLOW_SECONDS": "2", "ACME_CHAOS_TOAST_MS": "2000"}) as server:
        yield server


def browse(acme, body, *, timeout=None, chaos=None):
    acme.admin("POST", "/__admin/reset", seed="base", now=NOW)
    if chaos:
        acme.admin("POST", "/__admin/chaos", profile=chaos)
    run = start_run("browser test", datetime.fromisoformat(NOW), config=acme.agent_config(timeout))

    async def main():
        try:
            return await body(run)
        finally:
            await run.close()
    return asyncio.run(main())


def count(acme, sql) -> int:
    conn = sqlite3.connect(acme.db_path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


async def pending_invoice(run) -> int:
    invoice = await run.call("submit_invoice", BIG)  # entered by ops-agent and over the limit: every action shows
    assert invoice.ok
    return invoice.data["id"]


def test_the_invoice_detail_page_shows_every_control_with_a_ref(acme):
    async def body(run):
        invoice_id = await pending_invoice(run)
        page = await run.call("browser_open", {"path": f"/invoices/{invoice_id}"})
        html = await (await run.browser.page()).content()
        return invoice_id, page, html
    invoice_id, page, html = browse(acme, body)
    view = page.data["view"]
    assert f'button "Request approval" -> submits POST /invoices/{invoice_id}/request-approval' in view
    assert f'button "Void invoice" -> submits POST /invoices/{invoice_id}/void' in view
    assert 'button "Attach source file"' in view and 'textbox "Reason (optional)"' in view
    assert re.search(r'\[c\d+\] combobox "Source PDF" = "Choose a file" \(options: Choose a file \|', view)
    buttons = [e for e in page.data["elements"] if e["role"] == "button"]
    assert len(buttons) == html.count("<button")  # every button on the page has a ref (the extension missed two)
    assert all(re.fullmatch(r"[a-z]\d+", e["ref"]) for e in page.data["elements"])
    assert page.data["provenance"] == {"source": "untrusted", "origin": f"page:/invoices/{invoice_id}"}


def test_real_pages_fit_the_observation_cap(acme):
    paths = ["/", "/invoices", "/invoices/new", "/approvals", "/payments", "/vendors", "/employees", "/it-tickets",
             "/mail", "/mail/7", "/mail/compose", "/employees/new", "/it-tickets/new", "/payments/new"]

    async def body(run):
        return {p: await run.call("browser_open", {"path": p}) for p in paths}
    pages = browse(acme, body)
    sizes = {p: len(r.data["view"]) for p, r in pages.items()}
    print("observation sizes (chars):", sizes)
    assert all(r.ok and not r.data["truncated"] for r in pages.values())
    assert max(sizes.values()) < MAX_VIEW_CHARS / 2  # headroom: the cap only bites on unexpectedly large pages


def test_a_click_whose_target_changed_since_the_observation_is_refused(acme):
    async def body(run):
        first, second = await pending_invoice(run), (await run.call("submit_invoice", {**BIG, "invoice_no": "GUI-2"})).data["id"]
        page = await run.call("browser_open", {"path": f"/invoices/{first}"})
        void = ref(page, "button", name="Void invoice")
        await (await run.browser.page()).goto(f"/invoices/{second}")  # the page changes behind the observation
        return second, await run.call("browser_click", {"ref": void})
    second, result = browse(acme, body)
    assert result.error_type == "precondition_failed" and "observe again" in result.detail
    assert count(acme, f"SELECT COUNT(*) FROM invoices WHERE id = {second} AND status = 'void'") == 0


def test_a_lost_session_renews_a_read_and_never_resubmits_a_form(acme):
    async def read(run):
        await run.call("browser_open", {"path": "/"})
        return await run.call("browser_open", {"path": "/invoices"})  # request 2: the session is gone
    page = browse(acme, read, chaos="session_expiry_at_step_1")
    assert page.ok and page.data["session_renewed"] is True and page.data["url"] == "/invoices"

    async def write(run):
        form = await run.call("browser_open", {"path": "/it-tickets/new"})
        await run.call("browser_select", {"ref": ref(form, "combobox", name="Type"), "option": "laptop"})
        await run.call("browser_select", {"ref": ref(form, "combobox", name="Employee"),
                                          "option": "Neha Kulkarni (neha.kulkarni@acme.example)"})
        submit = ref(form, "button", target="POST /it-tickets/new")
        return await run.call("browser_click", {"ref": submit}), await run.call("browser_open", {"path": "/it-tickets"})
    before = count(acme, "SELECT COUNT(*) FROM it_tickets")
    result, after = browse(acme, write, chaos="session_expiry_at_step_1")
    assert result.error_type == "session_expired" and result.data["session_renewed"] is True
    assert "not submitted" in result.detail and after.ok  # logged in again for the next call
    assert count(acme, "SELECT COUNT(*) FROM it_tickets") == before


def test_a_toast_is_captured_right_after_the_action(acme):
    async def body(run):
        invoice_id = await pending_invoice(run)
        page = await run.call("browser_open", {"path": f"/invoices/{invoice_id}"})
        return await run.call("browser_click", {"ref": ref(page, "button", name="Request approval")})
    result = browse(acme, body, chaos="toast_2s")
    assert result.ok and result.data["status"] == 303
    assert any(m.startswith("status: Approval request") for m in result.data["messages"])


def test_a_write_slower_than_the_timeout_is_a_timeout_result(acme):
    async def body(run):
        invoice_id = await pending_invoice(run)  # the API tool retries its slowed write with the same key: replayed
        page = await run.call("browser_open", {"path": f"/invoices/{invoice_id}"})
        return invoice_id, await run.call("browser_click", {"ref": ref(page, "button", name="Request approval")})
    invoice_id, result = browse(acme, body, chaos="slow_server", timeout=1.5)  # every write held 2-4 s
    assert (result.ok, result.error_type, result.data["outcome_unknown"]) == (False, "timeout", True)  # N.139
    assert count(acme, f"SELECT COUNT(*) FROM approvals WHERE entity_id = {invoice_id}") == 1  # it did commit


# --- the T1 GUI oracle -------------------------------------------------------------------------------------------

def gui_oracle(acme, chaos=None):
    task = tasks.load("T1")
    run = tasks.runs(task)[0]
    return asyncio.run(run_oracle(acme, task, run, oracle_for("T1", "gui"), chaos=chaos))


@pytest.mark.parametrize("chaos", [None, "rename_submit_button", "field_moved", "toast_2s"])
def test_the_t1_gui_oracle_passes_the_checker(acme, chaos):
    result = gui_oracle(acme, chaos)
    assert result.script.ok, result.script.stopped_at
    assert result.result.passed, [(c.name, c.detail) for c in result.result.checks if not c.ok]
    assert result.chaos_fired in (None, True)
    assert "submit_redo" not in result.script.results  # nothing to redo


def test_the_t1_gui_oracle_detects_a_silent_drop_and_redoes_the_write_once(acme):
    result = gui_oracle(acme, "silent_drop_write")
    assert result.chaos_fired is True and result.passed
    first = result.script.results["submit"]
    assert first.ok and any("saved" in m for m in first.data["messages"])  # the toast said saved ...
    assert "INV-1043 – " not in result.script.results["read_back"].data["view"]  # ... the list disagreed
    assert result.script.results["submit_redo"].ok
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 1


def test_under_delayed_write_an_early_redo_is_refused_as_a_duplicate_not_written_twice(acme):
    result = gui_oracle(acme, "delayed_write")  # 6.9: read back too early, the row is not visible yet
    assert result.script.stopped_at == "submit_redo"
    assert result.script.results["submit_redo"].error_type == "conflict"
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 1


def test_under_flaky_500_the_failed_submit_is_a_typed_server_error(acme):
    result = gui_oracle(acme, "flaky_500")
    assert result.script.stopped_at == "submit"
    assert result.script.results["submit"].error_type == "server_error"
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 0

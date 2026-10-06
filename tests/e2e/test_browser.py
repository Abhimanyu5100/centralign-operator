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
from tests.agent.agent_fixtures import AllowAllGate

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
    # browser mechanics, not policy: the allow-all test gate (the policy gate holds a GUI void, ORG-008)
    run = start_run("browser test", datetime.fromisoformat(NOW), config=acme.agent_config(timeout), gate=AllowAllGate())

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


INSERT_BEFORE = """([tag, text, href, outside]) => {
    const target = [...document.querySelectorAll('button, a')].find(e => e.textContent.trim() === text);
    const anchor = outside && target.closest('form') ? target.closest('form') : target;
    const el = document.createElement(tag);
    el.textContent = tag === 'span' ? 'Unrelated' : text;
    if (href) el.setAttribute('href', href);
    anchor.parentNode.insertBefore(el, anchor);
}"""  # test-side page surgery: the agent itself never uses selectors


@pytest.mark.parametrize("tag,outside,expect", [
    ("span", False, "voided"),         # different role and name: the same ref still finds the real button
    ("button", False, "voided"),       # same name, inside the same form: it sends exactly the request the gate saw
    ("button", True, "refused"),       # same name, outside any form: it would send nothing the gate saw
])
def test_a_re_rendered_page_never_shifts_a_click_onto_another_control(acme, tag, outside, expect):
    """Register 4.5: an element inserted before the target after the observation; the click hits the right control
    (refs resolve by role, name and position among same-named controls, and the form target is re-read) or
    refuses with "observe again"."""
    async def body(run):
        invoice_id = await pending_invoice(run)
        page = await run.call("browser_open", {"path": f"/invoices/{invoice_id}"})
        void = ref(page, "button", name="Void invoice")
        await (await run.browser.page()).evaluate(INSERT_BEFORE, [tag, "Void invoice", None, outside])
        return invoice_id, await run.call("browser_click", {"ref": void})
    invoice_id, result = browse(acme, body)
    voided = count(acme, f"SELECT COUNT(*) FROM invoices WHERE id = {invoice_id} AND status = 'void'")
    if expect == "voided":
        assert result.ok and voided == 1
    else:
        assert result.error_type == "precondition_failed" and "observe again" in result.detail and voided == 0


def test_a_same_name_link_inserted_before_the_target_is_refused(acme):
    async def body(run):
        page = await run.call("browser_open", {"path": "/"})
        invoices = ref(page, "link", name="Invoices")
        await (await run.browser.page()).evaluate(INSERT_BEFORE, ["a", "Invoices", "/vendors", False])
        return await run.call("browser_click", {"ref": invoices})
    result = browse(acme, body)
    assert result.error_type == "precondition_failed" and "no longer leads to /invoices" in result.detail


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
    assert result.verdict.status == "awaiting_business_approval", result.verdict.reasons


def test_the_t1_gui_oracle_detects_a_silent_drop_and_redoes_the_write_once(acme):
    result = gui_oracle(acme, "silent_drop_write")
    assert result.chaos_fired is True and result.passed
    first = result.script.results["submit"]
    assert first.ok and any("saved" in m for m in first.data["messages"])  # the toast said saved ...
    assert "INV-1043 – " not in result.script.results["read_back"].data["view"]  # ... the list disagreed
    assert result.script.results["submit_redo"].ok
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 1
    # the run recovered, so the target states hold; the dropped submit is still reported (layer 3, 4.4)
    assert result.verdict.status == "awaiting_business_approval", result.verdict.reasons
    assert result.verdict.notes == ["claimed but not in the audit log: browser_click"]


def test_a_silent_drop_the_run_does_not_redo_is_failed_by_the_verifier(acme):
    """Register 4.4, 5.3, 6.1: the toast said saved, nothing was stored, and the agent stopped there. Layer 2 reads
    the invoice through the API (a different channel from the GUI write) and does not find it."""
    from bench.oracles import Oracle
    gui = oracle_for("T1", "gui")
    upto = next(i for i, step in enumerate(gui.steps) if step.key == "read_back")
    task = tasks.load("T1")
    result = asyncio.run(run_oracle(acme, task, tasks.runs(task)[0], Oracle(gui.steps[:upto + 1], gui.plan),
                                    chaos="silent_drop_write"))
    assert result.chaos_fired is True and result.verdict.status == "failed"
    assert "milestone M1 not met" in result.verdict.reasons[0]
    assert result.verdict.notes == ["claimed but not in the audit log: browser_click"]


def test_under_delayed_write_an_early_redo_is_refused_as_a_duplicate_not_written_twice(acme):
    result = gui_oracle(acme, "delayed_write")  # 6.9: read back too early, the row is not visible yet
    assert result.script.stopped_at == "submit_redo"
    assert result.script.results["submit_redo"].error_type == "conflict"
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 1
    # the verifier waits the lag out: the invoice is found (M1), the approval the run never requested is not (M2)
    m1, m2 = result.verdict.milestones
    assert m1.ok and m1.checks[0].reads > 1 and not m2.ok and result.verdict.status == "failed"


def test_under_flaky_500_the_failed_submit_is_a_typed_server_error(acme):
    result = gui_oracle(acme, "flaky_500")
    assert result.script.stopped_at == "submit"
    assert result.script.results["submit"].error_type == "server_error"
    assert count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 0
    assert result.verdict.status == "failed" and result.verdict.side_effects.wrote is False


def test_a_gui_run_is_rolled_back_through_the_api_undo_tools(acme):
    """D-128, N.142: the GUI writes are found as audit inserts by the run's account since its start mark and undone
    through the API (newest first), past the policy gate (ORG-008 sees them as created by the run)."""
    from agent.lifecycle import rollback
    from agent.scripted import run_script
    task = tasks.load("T1")
    acme.admin("POST", "/__admin/reset", seed=task.seed, now=task.now)
    snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
    oracle = oracle_for("T1", "gui")
    run = start_run(task.request, datetime.fromisoformat(task.now), config=acme.agent_config(), plan=oracle.plan)

    async def body():
        try:
            assert (await run_script(run, oracle.steps)).ended == "done"
            return await rollback(run), await rollback(run)
        finally:
            await run.close()
    first, second = asyncio.run(body())
    diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
    assert first.ok and [u["tool"] for u in first.undone] == ["withdraw_approval", "void_invoice"]
    assert second.ok and all(u["already_done"] for u in second.undone)
    assert {t: [r["status"] for r in c["added"]] for t, c in diff.items() if t != "audit_log"} == {
        "invoices": ["void"], "approvals": ["withdrawn"]}
    assert all(not c["changed"] and not c["removed"] for c in diff.values())


def test_no_secret_reaches_the_run_store_after_a_gui_run(acme):
    """P.7: after a whole GUI run (with a session renewal), neither the agent's password nor the admin token
    appears anywhere under runs/ (the SQLite run store, its WAL, the scratch files)."""
    gui_oracle(acme, "session_expiry_at_step_6")
    from agent.store import DEFAULT_PATH
    blobs = [p.read_bytes() for p in DEFAULT_PATH.parent.rglob("*") if p.is_file()]
    assert blobs
    for secret in (acme.agent_password, acme.admin_token):
        assert not any(secret.encode() in blob for blob in blobs)


# --- what the gate saw is what is sent (D-125, N.144) -------------------------------------------------------------

def _compose(run_steps_after_fill):
    async def body(run):
        form = await run.call("browser_open", {"path": "/mail/compose"})
        for label, value in (("Recipient", "neha.kulkarni@acme.example"), ("Subject", "Hello"), ("Message", "Hi")):
            await run.call("browser_fill", {"ref": ref(form, "textbox", name=label), "value": value})
        return await run_steps_after_fill(run, ref(form, "button", name="Send mail"))
    return body


def test_the_gate_sees_the_fields_a_gui_submit_sends(acme):
    from tests.agent.agent_fixtures import FixedGate
    from agent.policy.gate import Decision
    seen = []

    async def click(run, send):
        recorder = FixedGate(Decision(effect="deny", policy_ids=["TEST-1"], reason="look, do not send"))
        run.registry.gate = recorder
        result = await run.call("browser_click", {"ref": send})
        seen.extend(recorder.seen)
        return result
    result = browse(acme, _compose(click))
    assert result.error_type == "policy_denied"
    assert {k: seen[0].args[k] for k in ("to", "subject", "body")} == {
        "to": "neha.kulkarni@acme.example", "subject": "Hello", "body": "Hi"}
    assert "idempotency_token" not in seen[0].args and seen[0].trust_sensitive == ("to",)


def test_a_form_changed_after_the_decision_is_not_submitted(acme):
    import dataclasses
    before = count(acme, "SELECT COUNT(*) FROM mail WHERE folder = 'outbox'")

    async def click(run, send):
        spec = run.registry.get("browser_click")
        original = spec.gate_args_of

        async def then_change(args):  # test-side surgery between the gate's read and the click
            seen = await original(args)
            await (await run.browser.page()).fill("#to", "someone@evil.example")
            return seen
        run.registry._tools["browser_click"] = dataclasses.replace(spec, gate_args_of=then_change)
        return await run.call("browser_click", {"ref": send})
    result = browse(acme, _compose(click))
    assert result.error_type == "precondition_failed" and "changed after the gate decided" in result.detail
    assert count(acme, "SELECT COUNT(*) FROM mail WHERE folder = 'outbox'") == before

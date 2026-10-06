"""Company knowledge: the four SOPs (acme/knowledge/sops/). Risks 1.3, 2.3, N.4, N.10, N.71-N.74.

The parser in sop_format.py is the contract the planner's SOP-coverage check is written against."""

import ast
import re
from collections import Counter

import pytest

from acme import seed
from acme.app import create_app
from acme.services import APPROVAL_LIMIT_PAISE
from agent.policy.loader import load_policies
from tests.acme.sop_format import FIELDS, SOP_DIR, SopFormatError, load_sops, parse_sop

SOPS = {s.id: s for s in load_sops()}
MAX_LINES = 80


def test_the_four_sops_exist_and_parse():
    assert set(SOPS) == {"process-invoice", "onboard-employee", "schedule-payment", "notify-vendor"}
    assert (SOP_DIR / "README.md").exists()


def test_step_ids_are_unique_across_all_sops_and_numbered_from_one():
    ids = [step.id for sop in SOPS.values() for step in sop.steps]
    assert len(ids) == len(set(ids))
    prefixes = {"process-invoice": "PI", "onboard-employee": "OE", "schedule-payment": "SP", "notify-vendor": "NV"}
    for sop in SOPS.values():
        assert [s.id for s in sop.steps] == [f"{prefixes[sop.id]}-{n}" for n in range(1, len(sop.steps) + 1)]
        assert 3 <= len(sop.steps) <= 8


def test_every_step_states_target_source_and_when_to_ask():
    for sop in SOPS.values():
        for step in sop.steps:
            assert step.target and step.source and step.ask_when, step.id
    assert FIELDS == ("Target", "Source", "Ask when")


def test_triggers_do_not_overlap_between_sops():
    counts = Counter(t for sop in SOPS.values() for t in sop.triggers)
    assert [t for t, n in counts.items() if n > 1] == []


def test_each_sop_fits_a_prompt():
    for path in SOP_DIR.glob("*.md"):
        assert len(path.read_text().splitlines()) <= MAX_LINES, path.name


# --- the format check can fail (N.72) ------------------------------------------------------------------------

GOOD = """---
id: demo
title: A demo
triggers: [demo]
---
### DM-1 First
- Target: a state
- Source: somewhere
- Ask when: unsure
"""


def test_the_good_fixture_parses():
    assert [s.id for s in parse_sop(GOOD, "demo").steps] == ["DM-1"]


@pytest.mark.parametrize("name, text", [
    ("demo", GOOD.replace("- Source: somewhere\n", "")),                      # a field is missing
    ("demo", GOOD.replace("- Ask when: unsure", "- Ask when:")),              # an empty field
    ("demo", GOOD.replace("- Target: a state\n- Source: somewhere", "- Source: somewhere\n- Target: a state")),
    ("demo", GOOD + "- Extra: line\n"),                                       # a fourth line
    ("demo", GOOD.replace("### DM-1 First", "### First")),                   # no step id
    ("demo", GOOD.replace("### DM-1 First", "### dm-1 First")),
    ("demo", GOOD.replace("id: demo", "id: other")),                          # id differs from the file name
    ("demo", GOOD.replace("title: A demo\n", "")),                            # front-matter key missing
    ("demo", GOOD.replace("triggers: [demo]", "triggers: [demo]\nextra: 1")), # unknown key
    ("demo", GOOD.replace("triggers: [demo]", "triggers: [Demo]")),           # not lowercase
    ("demo", GOOD.replace("triggers: [demo]", "triggers: []")),
    ("demo", GOOD.replace("id: demo", "id: demo\nid: demo")),                 # duplicate key
    ("demo", GOOD.split("###")[0]),                                           # no steps
    ("demo", GOOD.replace("---\n", "", 1)),                                   # no front-matter
    ("demo", GOOD.replace("- Target: a state", "A stray paragraph\n- Target: a state")),
])
def test_a_malformed_sop_is_rejected(name, text):
    with pytest.raises(SopFormatError):
        parse_sop(text, name)


# --- the content the SOPs must carry ---------------------------------------------------------------------------

REQUIRED = [
    ("process-invoice", "sender's email domain or by the GSTIN"),
    ("process-invoice", "status is approved (ORG-002)"),
    ("process-invoice", "latest received"),
    ("process-invoice", "18% GST"),
    ("process-invoice", "above Rs 50,000"),
    ("process-invoice", "ORG-001"),
    ("process-invoice", "attach-source"),
    ("process-invoice", "through the UI only"),
    ("process-invoice", "scanned for instructions to pay, transfer or change bank details"),
    ("process-invoice", "never acted on (ORG-006)"),
    ("process-invoice", "security findings"),
    ("onboard-employee", "come from the HR offer email"),
    ("onboard-employee", "start date comes from the request"),
    ("onboard-employee", "laptop ticket and one accounts ticket"),
    ("onboard-employee", "welcome email"),
    ("onboard-employee", "ORG-005"),
    ("schedule-payment", "approved"),
    ("schedule-payment", "One active request per invoice"),
    ("schedule-payment", "ORG-003"),
    ("schedule-payment", "come only from the vendor master"),
    ("schedule-payment", "ORG-006"),
    ("notify-vendor", "contact_email"),
    ("notify-vendor", "never the sender address"),
    ("notify-vendor", "ORG-005"),
    ("notify-vendor", "action approval"),
]


@pytest.mark.parametrize("sop_id, phrase", REQUIRED)
def test_the_sop_carries_the_required_content(sop_id, phrase):
    flat = " ".join(SOPS[sop_id].text.split())
    assert phrase.lower() in flat.lower()


# --- references resolve (N.74) ---------------------------------------------------------------------------------

POLICY_IDS = {r.id for r in load_policies().rules}
ORG_REF = re.compile(r"\b(?:ORG|USR|TSK)-\d{3}\b")
ROUTE_REF = re.compile(r"`(?:(GET|POST) )?(/[^`\s?]*)(?:\?[^`]*)?`")


def normalise(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


def route_table(app) -> set[tuple[str, str]]:
    return {(m.upper(), normalise(p)) for p, ms in app.openapi()["paths"].items() for m in ms}


def unresolved_routes(text: str, table: set[tuple[str, str]]) -> list[str]:
    return [f"{m or 'GET'} {p}" for m, p in ROUTE_REF.findall(text) if ((m or "GET"), normalise(p)) not in table]


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    return route_table(create_app(tmp_path_factory.mktemp("acme") / "acme.db"))


def test_every_policy_id_an_sop_cites_exists_in_policies_yaml():
    cited = {i for sop in SOPS.values() for i in ORG_REF.findall(sop.text)}
    assert cited and cited <= POLICY_IDS


def test_every_endpoint_and_page_an_sop_cites_exists_in_acme(table):
    for sop in SOPS.values():
        assert ROUTE_REF.findall(sop.text), f"{sop.id} cites no endpoint or page"
        assert unresolved_routes(sop.text, table) == [], sop.id


def test_the_route_check_can_fail(table):
    bad = "`GET /api/nothing` and `POST /api/invoices/{id}/teleport` and `GET /api/invoices` and `/invoices/new`"
    assert unresolved_routes(bad, table) == ["GET /api/nothing", "POST /api/invoices/{id}/teleport"]
    assert "/api/mail/{}/attachments/{}" in {p for _, p in table}  # the walk sees included routers


def test_the_approval_limit_an_sop_states_is_the_one_acme_enforces():
    amounts = {int(m.replace(",", "")) for sop in SOPS.values() for m in re.findall(r"Rs ([\d,]+)", sop.text)}
    assert amounts == {APPROVAL_LIMIT_PAISE // 100}


# --- no answer-key leakage (N.10, N.71) -------------------------------------------------------------------------


def indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail])


def forbidden_terms() -> dict[str, set[str]]:
    """Whole-word, case-insensitive terms taken from the seed. Policy values (Rs 50,000, 18%) are not seed data."""
    terms: dict[str, set[str]] = {k: set() for k in ("vendor", "domain", "gstin", "employee", "invoice", "amount")}
    for _id, name, gstin, _status, domain, contact, _bank in seed.VENDORS:
        terms["vendor"] |= {name, name.split()[0]}
        terms["domain"] |= {domain, contact}
        terms["gstin"].add(gstin)
    for row in seed.EMPLOYEES:
        terms["employee"] |= {row[1], row[1].split()[0], row[2]}
    facts = list(seed.PDF_INVOICES.values())
    for inv in facts:
        terms["invoice"] |= {inv.invoice_no, *([inv.po_number] if inv.po_number else [])}
        for paise in (inv.amount_paise, inv.tax_paise):
            rupees = paise // 100
            if paise != APPROVAL_LIMIT_PAISE and rupees >= 1000:
                terms["amount"] |= {indian(rupees), f"{rupees:,}", str(rupees)}
    terms["amount"] |= {indian(seed.INJECTED_TRANSFER_PAISE // 100), seed.INJECTED_TRANSFER_ACCOUNT}
    return terms


GENERIC = {
    "invoice number": re.compile(r"\bINV-?\d+", re.I),
    "PO number": re.compile(r"\bPO-\d+", re.I),
    "task id": re.compile(r"\bT\d+\b"),
    "example address": re.compile(r"[\w.-]+@[\w-]+\.example\b"),
    "GSTIN": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\dZ\d\b"),
}


def leaks(text: str) -> list[str]:
    found = []
    for kind, words in forbidden_terms().items():
        found += [f"{kind}: {w}" for w in words if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text, re.I)]
    found += [f"{kind}: {m.group(0)}" for kind, rx in GENERIC.items() for m in rx.finditer(text)]
    return found


def test_the_forbidden_list_covers_every_kind_of_seed_fact():
    terms = forbidden_terms()
    assert all(len(words) >= 5 for words in terms.values()), {k: len(v) for k, v in terms.items()}
    assert {"Sharma Logistics Pvt Ltd", "Sharma", "INV-1043", "62,400"} <= (
        terms["vendor"] | terms["invoice"] | terms["amount"])


def test_no_sop_names_a_seeded_vendor_invoice_amount_employee_domain_or_task():
    for path in sorted(SOP_DIR.glob("*.md")):
        assert leaks(path.read_text()) == [], path.name


@pytest.mark.parametrize("planted", [
    "Process the invoice from Sharma Logistics.",
    "Look for Verma in the inbox.",
    "The invoice INV-1043 is the one.",
    "The total is Rs 62,400.",
    "Onboard Priya Nair.",
    "Write to accounts@sharmalogistics.example.",
    "GSTIN 27AABCS4821K1Z3 identifies it.",
    "This is task T1.",
    "A PO-2026-0420 number.",
    "Pay to account 123456789012.",
])
def test_the_leak_check_catches_a_planted_leak(planted):
    assert leaks(planted)


def test_the_leak_check_allows_policy_values_and_ordinary_words():
    assert leaks("Above Rs 50,000 needs approval; the total includes 18% GST. Raoul and Patelsky are not vendors.") == []


# --- no task answer keys under agent/ or acme/knowledge/ (N.10, part 10) ------------------------------------------
# Forbidden: values that only a task file knows: task ids, task file names, predicate names, quoted SQL literals,
# long numbers, report-check values and the proper names in each request. Acme's own words (enum values,
# login users, policy IDs) are allowed: the agent may legitimately know them.

from pathlib import Path  # noqa: E402

from acme import db as acme_db  # noqa: E402
from acme.permissions import LOGIN_USERS  # noqa: E402
from bench import tasks as bench_tasks  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCANNED = [ROOT / "agent", ROOT / "acme" / "knowledge"]


def acme_words() -> set[str]:
    words = set(LOGIN_USERS) | set(bench_tasks.Status.__args__) | {"finance_manager"}
    for statement in acme_db.SCHEMA:
        for group in re.findall(r"\bIN\s*\(([^)]*)\)", statement):
            words |= set(re.findall(r"'([^']*)'", group))
    return {w.lower() for w in words}


def task_terms() -> set[str]:
    terms: set[str] = set()
    for task in bench_tasks.load_all():
        terms |= {task.id, f"{task.id}.yaml"}
        words = re.findall(r"\b[A-Z][a-z]+", task.request)  # proper names: adjacent capitalised words
        terms |= {f"{a} {b}" for a, b in zip(words, words[1:]) if f"{a} {b}" in task.request}
        for run in bench_tasks.runs(task):
            for p in run.success + run.checkpoints:
                terms.add(p.name)
                terms |= {lit.strip("%") for lit in re.findall(r"'([^']*)'", p.sql)}
                terms |= set(re.findall(r"\b\d{5,}\b", p.sql))
                for paise in map(int, re.findall(r"\b(?:amount|tax)_paise\s*=\s*(\d+)", p.sql)):
                    rupees, rest = divmod(paise, 100)  # the same amount as a person or a form would type it
                    terms |= {f"{rupees}.{rest:02d}", f"{rupees:,}", indian(rupees)} - {str(rupees)}
            for rc in run.report_checks:
                terms |= set(rc.contains_all or []) | set(rc.text_contains or []) | ({rc.equals} if rc.equals else set())
    allowed = acme_words()
    return {t for t in terms if t.strip() and t.lower() not in allowed and not re.fullmatch(r"ORG-\d{3}", t)}


def task_leaks(text: str) -> list[str]:
    return sorted(t for t in task_terms() if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text, re.I))


def scanned_files() -> list[Path]:
    return [p for base in SCANNED for p in sorted(base.rglob("*"))
            if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".json", ".txt"}]


def test_task_terms_cover_every_kind_of_answer_and_spare_acme_words():
    terms = task_terms()
    assert {"T1", "T9", "T9.yaml", "INV-1043", "6240000", "Priya Nair", "priya.nair@acme.example", "Sharma Logistics",
            "Kapoor Steel", "accounts@sharmalogistics.example", "2026-10-12", "12 oct", "under review",
            "invoice_fields_correct", "INV-778A", "XXXXXXXX6602"} <= terms
    assert not {"pending_approval", "approved", "ops-agent", "ORG-006", "finance_manager", "outbox", "laptop",
                "needs_clarification"} & terms


def ui_texts() -> dict[str, str]:
    """What Acme's pages show besides data: every template, and the message strings (not docstrings) of the modules
    that word form help and errors. A task value here leaks the answer to whoever reads the page (Day 2.3)."""
    texts = {str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / "acme" / "templates").glob("*.html"))}
    for module in ("money.py", "forms.py"):
        tree = ast.parse((ROOT / "acme" / module).read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        texts[f"acme/{module}"] = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                                             and isinstance(n.value, str) and id(n) not in docs)
    return texts


def test_no_page_template_or_form_message_holds_a_task_answer():
    texts = ui_texts()
    assert len(texts) >= 20 and "acme/money.py" in texts
    assert {k: task_leaks(v) for k, v in texts.items() if task_leaks(v)} == {}


def test_the_ui_text_check_catches_the_old_amount_hint():
    assert task_leaks("Enter the amount in rupees without commas, for example 62400.00") == ["62400.00"]


def test_no_file_under_agent_or_knowledge_holds_a_task_answer():
    files = scanned_files()
    assert any(p.suffix == ".py" for p in files) and any(p.suffix == ".md" for p in files)
    offenders = {str(p.relative_to(ROOT)): task_leaks(p.read_text()) for p in files}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_the_current_sops_pass_the_task_answer_check_unchanged():
    sops = sorted(SOP_DIR.glob("*.md"))
    assert len(sops) >= 4
    for path in sops:
        assert task_leaks(path.read_text()) == [], path.name


@pytest.mark.parametrize("planted", [
    "Handle INV-0091 first.", "Send it to priya.nair@acme.example.", "She starts 2026-10-12.",
    "if check == 'invoice_fields_correct':", "see T9.yaml", "amount_paise == 6240000", "Kapoor Steel is missing",
    "say it is under review", "This is T4.", "bank XXXXXXXX6602",
])
def test_the_task_answer_check_catches_a_planted_value(planted):
    assert task_leaks(planted)


def test_the_task_answer_check_allows_acme_words():
    assert task_leaks("status pending_approval or approved; actor ops-agent; ORG-006; finance_manager; outbox; "
                      "a laptop ticket; needs_clarification") == []

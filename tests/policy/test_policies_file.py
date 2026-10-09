"""acme/knowledge/policies.yaml: the real file validates, and every enforced_by=acme rule points at a check that
exists in Acme's code. Risks 1.4, P.2, P.11, 3.9, N.75, N.76, N.78 (D-017, D-064)."""

import pytest

from acme.app import create_app
from acme.mail import load_allowlist
from agent.policy.loader import KNOWLEDGE_DIR, POLICIES_PATH, load_policies, read_allowlist
from agent.policy.models import (ActionCheck, ConstantCheck, FunctionCheck, ModelCheck, NoRouteCheck,
                                 RecipientDomainNotIn, RequestMatches)
from tests.policy import acme_checks

RULES = {r.id: r for r in load_policies().rules}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    return create_app(tmp_path_factory.mktemp("acme") / "acme.db")


def test_the_real_file_validates_and_holds_org_001_to_009():
    assert list(RULES) == [f"ORG-00{n}" for n in range(1, 10)]
    assert {r.level for r in RULES.values()} == {"org"}
    assert {i: r.enforced_by for i, r in RULES.items()} == {
        "ORG-001": "acme", "ORG-002": "runtime", "ORG-003": "acme", "ORG-004": "runtime", "ORG-005": "runtime",
        "ORG-006": "acme", "ORG-007": "runtime", "ORG-008": "runtime", "ORG-009": "runtime"}


def test_every_rule_can_only_deny_or_hold_for_approval():
    assert {r.effect for r in RULES.values()} <= {"deny", "require_approval"}
    assert RULES["ORG-005"].effect == "require_approval"
    assert all(RULES[i].effect == "deny" for i in ("ORG-001", "ORG-002", "ORG-003", "ORG-004", "ORG-006"))


@pytest.mark.parametrize("rule_id", [i for i, r in RULES.items() if r.enforced_by == "acme"])
def test_every_acme_rule_maps_to_checks_that_exist_in_acme(rule_id, app):
    assert RULES[rule_id].acme_check
    for entry in RULES[rule_id].acme_check:
        acme_checks.check(entry, app)


def test_org_004_denies_every_method_on_admin_paths():
    (cond,) = RULES["ORG-004"].when
    assert isinstance(cond, RequestMatches) and (cond.method, cond.paths) == ("*", ["/__admin/**"])


def test_org_001_and_003_deny_a_post_on_both_approval_decide_routes():
    for rule_id in ("ORG-001", "ORG-003"):
        (cond,) = RULES[rule_id].when
        assert (cond.method, cond.paths) == ("POST", ["/approvals/*/decide", "/api/approvals/*/decide"])


def test_org_005_reads_the_shared_allowlist_file_and_keeps_no_domain_list():
    cond = next(c for c in RULES["ORG-005"].when if isinstance(c, RecipientDomainNotIn))
    assert (cond.arg, cond.allowlist) == ("to", "mail_allowlist.yaml")
    # one file, two readers: the gate's loader and Acme's mail module agree on the domains (D-064)
    assert read_allowlist(KNOWLEDGE_DIR / cond.allowlist)[1] == load_allowlist().allowed
    text = POLICIES_PATH.read_text()
    assert "partner.example" not in text and "acme.example" not in text


def test_org_006_has_no_payee_bank_or_amount_input_on_payment_requests():
    from acme.models import PaymentIn
    assert set(PaymentIn.model_fields) == {"invoice_id", "scheduled_date"}
    assert any(getattr(e, "ref", "") == "acme.models.PaymentIn" for e in RULES["ORG-006"].acme_check)


# --- the resolver itself must be able to fail, or the tests above prove nothing -----------------------------


KINDS = dict(constant=ConstantCheck, action=ActionCheck, function=FunctionCheck, model=ModelCheck,
             no_route=NoRouteCheck)


@pytest.mark.parametrize("kind, fields", [
    ("constant", dict(ref="acme.services.APPROVAL_LIMIT_PAISE", equals=1)),
    ("constant", dict(ref="acme.services.NO_SUCH_LIMIT", equals=1)),
    ("function", dict(ref="acme.services.no_such_function")),
    ("action", dict(ref="vendor.update_bank", roles=["ops_agent", "admin"])),
    ("action", dict(ref="no.such_action", roles=["admin"])),
    ("model", dict(ref="acme.models.PaymentIn", fields=["invoice_id"])),
    ("no_route", dict(path="/**/payments*/**")),
])
def test_a_wrong_acme_check_fails(kind, fields, app):
    with pytest.raises(AssertionError):
        acme_checks.check(KINDS[kind](kind=kind, **fields), app)

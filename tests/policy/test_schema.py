"""The policy schema and strict loader (agent/policy/models.py, loader.py). Risks 1.4, P.11, N.75, N.78, N.81 (D-017).

Every condition type and every acme_check kind has a synthetic rule that validates and variants that must not,
so none is untested even where no shipped rule uses it (N.81). The evaluator is Day 3 and is not tested here."""

from pathlib import Path

import pytest

from agent.policy.loader import KNOWLEDGE_DIR, PolicyError, load_allowlist_domains, load_policies, strict_yaml
from agent.policy.models import CONDITION_TYPES, PolicyFile

CONDITIONS = {
    "tool_in": {"type": "tool_in", "tools": ["send_mail"]},
    "request_matches": {"type": "request_matches", "method": "POST", "path": "/api/mail/send"},
    "amount_gt": {"type": "amount_gt", "arg": "amount_paise", "paise": 5_000_000},
    "vendor_status_not_in": {"type": "vendor_status_not_in", "arg": "vendor_id", "statuses": ["approved"]},
    "recipient_domain_not_in": {"type": "recipient_domain_not_in", "arg": "to", "allowlist": "mail_allowlist.yaml"},
    "field_source_untrusted": {"type": "field_source_untrusted", "allowlist": "mail_allowlist.yaml"},
    "side_effect_in": {"type": "side_effect_in", "side_effects": ["irreversible_write", "external_comms"]},
    "run_has_no_sop": {"type": "run_has_no_sop"},
    "target_not_created_by_run": {"type": "target_not_created_by_run"},
}
OPTIONAL_FIELDS = {"field_source_untrusted": {"allowlist"}}  # without it no address is exempt
# for each type: variants that must be rejected (a field changed or added)
BAD_CONDITIONS = {
    "tool_in": [{"tools": []}, {"tools": ["bad name"]}, {"tools": "send_mail"}, {"extra": 1}],
    "request_matches": [{"method": "post"}, {"method": "TRACE"}, {"path": "api/x"}, {"path": []}, {"path": "/a b"},
                        {"extra": 1}],
    "amount_gt": [{"paise": 0}, {"paise": "5000000"}, {"paise": True}, {"arg": "bad arg"}, {"extra": 1}],
    "vendor_status_not_in": [{"statuses": []}, {"statuses": ["unknown"]}, {"statuses": [False]}, {"extra": 1}],
    "recipient_domain_not_in": [{"allowlist": "../mail_allowlist.yaml"}, {"allowlist": "/etc/passwd"},
                                {"allowlist": "mail_allowlist.txt"}, {"allowlist": ["x.example"]},
                                {"domains": ["x.example"]}, {"extra": 1}],
    "field_source_untrusted": [{"args": ["to"]}, {"allowlist": "../mail_allowlist.yaml"}, {"allowlist": ["x"]},
                               {"extra": 1}],
    "side_effect_in": [{"side_effects": []}, {"side_effects": ["write"]}, {"side_effects": "read"}, {"extra": 1}],
    "run_has_no_sop": [{"extra": 1}, {"sop_id": None}],
    "target_not_created_by_run": [{"extra": 1}, {"entity": "invoice"}],
}
ACME_CHECKS = {
    "constant": {"kind": "constant", "ref": "acme.services.APPROVAL_LIMIT_PAISE", "equals": 5_000_000},
    "action": {"kind": "action", "ref": "approval.decide", "roles": ["admin"]},
    "function": {"kind": "function", "ref": "acme.services.submit_invoice"},
    "model": {"kind": "model", "ref": "acme.models.PaymentIn", "fields": ["invoice_id"]},
    "no_route": {"kind": "no_route", "path": "/**/*bank*/**"},
}
BAD_ACME_CHECKS = {  # every kind also rejects an unknown key (extra=forbid on nested models)
    "constant": [{"ref": "no_dots"}, {"equals": 1.5}, {"equals": True}, {"extra": 1}],
    "action": [{"roles": []}, {"ref": "Approval.Decide"}, {"extra": 1}],
    "function": [{"ref": "submit_invoice"}, {"extra": 1}],
    "model": [{"fields": []}, {"extra": 1}],
    "no_route": [{"path": "bank"}, {"extra": 1}],
}


def rule(**overrides) -> dict:
    base = {"id": "ORG-001", "level": "org", "enforced_by": "runtime", "effect": "deny",
            "when": [CONDITIONS["tool_in"]], "message": "m"}
    return {**base, **overrides}


def policy(*rules, **top) -> dict:
    return {"schema_version": 0, "rules": list(rules) or [rule()], **top}


def valid(data) -> PolicyFile:
    return PolicyFile.model_validate(data)


def rejects(data) -> None:
    with pytest.raises(ValueError):
        valid(data)


def test_the_condition_type_set_is_the_documented_fixed_set():
    assert set(CONDITION_TYPES) == set(CONDITIONS) == set(BAD_CONDITIONS)


@pytest.mark.parametrize("ctype", CONDITIONS)
def test_each_condition_type_validates_in_a_synthetic_rule(ctype):
    parsed = valid(policy(rule(when=[CONDITIONS[ctype]])))
    assert parsed.rules[0].when[0].type == ctype


@pytest.mark.parametrize("ctype, change", [(t, c) for t, cs in BAD_CONDITIONS.items() for c in cs])
def test_each_condition_type_rejects_bad_values_and_unknown_keys(ctype, change):
    rejects(policy(rule(when=[{**CONDITIONS[ctype], **change}])))


@pytest.mark.parametrize("ctype", CONDITIONS)
def test_each_condition_type_needs_all_its_fields(ctype):
    for key in set(CONDITIONS[ctype]) - {"type"} - OPTIONAL_FIELDS.get(ctype, set()):
        cond = {k: v for k, v in CONDITIONS[ctype].items() if k != key}
        rejects(policy(rule(when=[cond])))


def test_request_matches_takes_one_glob_or_a_list_and_any_method():
    one = valid(policy(rule(when=[{"type": "request_matches", "method": "*", "path": "/__admin/**"}])))
    many = valid(policy(rule(when=[{"type": "request_matches", "method": "POST", "path": ["/a", "/*/b"]}])))
    assert one.rules[0].when[0].paths == ["/__admin/**"] and many.rules[0].when[0].paths == ["/a", "/*/b"]


def test_an_unknown_condition_type_fails_closed():
    rejects(policy(rule(when=[{"type": "amount_lt", "arg": "amount_paise", "paise": 1}])))
    rejects(policy(rule(when=[{"arg": "amount_paise", "paise": 1}])))  # no type at all


def test_an_unknown_condition_type_in_a_file_is_a_load_error(tmp_path):
    path = tmp_path / "policies.yaml"
    path.write_text("schema_version: 0\nrules:\n  - id: ORG-001\n    level: org\n    enforced_by: runtime\n"
                    "    effect: deny\n    when:\n      - {type: made_up}\n    message: m\n")
    with pytest.raises(PolicyError):
        load_policies(path)


@pytest.mark.parametrize("kind", ACME_CHECKS)
def test_each_acme_check_kind_validates_on_an_acme_rule(kind):
    parsed = valid(policy(rule(enforced_by="acme", acme_check=[ACME_CHECKS[kind]])))
    assert parsed.rules[0].acme_check[0].kind == kind


@pytest.mark.parametrize("kind, change", [(k, c) for k, cs in BAD_ACME_CHECKS.items() for c in cs])
def test_each_acme_check_kind_rejects_bad_values(kind, change):
    rejects(policy(rule(enforced_by="acme", acme_check=[{**ACME_CHECKS[kind], **change}])))


def test_acme_checks_belong_to_acme_rules_only():
    rejects(policy(rule(enforced_by="acme")))  # an acme rule must name its Acme check
    rejects(policy(rule(enforced_by="runtime", acme_check=[ACME_CHECKS["function"]])))
    rejects(policy(rule(enforced_by="acme", acme_check=[{"kind": "made_up", "ref": "a.b"}])))


# --- hierarchy (P.11): the schema cannot express a loosening rule -------------------------------------------


def test_there_is_no_allow_effect_so_a_lower_level_cannot_loosen_a_higher_one():
    for level, rid in (("org", "ORG-001"), ("user", "USR-001"), ("task", "TSK-001")):
        rejects(policy(rule(id=rid, level=level, effect="allow")))
        valid(policy(rule(id=rid, level=level, effect="require_approval")))


@pytest.mark.parametrize("rid, level", [("ORG-001", "task"), ("USR-001", "org"), ("TSK-001", "user"), ("XYZ-001", "org"),
                                        ("ORG-1", "org"), ("org-001", "org")])
def test_a_rule_id_must_match_its_level(rid, level):
    rejects(policy(rule(id=rid, level=level)))


def test_a_rule_needs_at_least_one_condition_and_a_message():
    rejects(policy(rule(when=[])))
    rejects(policy(rule(message="")))
    for missing in ("when", "message"):
        rejects(policy({k: v for k, v in rule().items() if k != missing}))


def test_file_level_checks():
    rejects(policy(rule(), rule()))                       # duplicate ids
    rejects(policy(schema_version=1))
    rejects(policy(extra_key=1))
    rejects(policy(rule(extra_key=1)))
    rejects({"schema_version": 0, "rules": []})
    rejects({"rules": [rule()]})


def test_values_are_not_coerced():
    rejects(policy(rule(enforced_by=True)))
    rejects(policy(rule(when=[{**CONDITIONS["amount_gt"], "paise": "100"}])))


# --- loader (N.78) -------------------------------------------------------------------------------------------


def write(tmp_path: Path, text: str, name: str = "policies.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


GOOD_RULE_YAML = ("  - id: ORG-001\n    level: org\n    enforced_by: runtime\n    effect: deny\n"
                  "    when:\n      - {type: tool_in, tools: [x]}\n    message: m\n")


def test_a_valid_file_loads(tmp_path):
    assert [r.id for r in load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + GOOD_RULE_YAML)).rules] == ["ORG-001"]


@pytest.mark.parametrize("text", [
    "schema_version: 0\nschema_version: 0\nrules:\n" + GOOD_RULE_YAML,              # duplicate top-level key
    "schema_version: 0\nrules:\n" + GOOD_RULE_YAML.replace("message: m", "message: m\n    message: n"),  # dup in rule
    "schema_version: 0\nrules:\n" + GOOD_RULE_YAML + GOOD_RULE_YAML,                   # duplicate ids
    "schema_version: 0\nrules: [",                                                       # broken YAML
    "- just\n- a list\n",
    "",
    "schema_version: 0\nrules:\n" + GOOD_RULE_YAML.replace("deny", "allow"),
])
def test_a_bad_file_is_a_load_error(tmp_path, text):
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, text))


def test_a_missing_file_is_a_load_error(tmp_path):
    with pytest.raises(PolicyError):
        load_policies(tmp_path / "nope.yaml")


def test_yaml_words_that_look_like_booleans_do_not_become_text(tmp_path):
    bad = GOOD_RULE_YAML.replace("[x]", "[no]")  # `no` is a YAML boolean, not a tool name
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + bad))


ALLOWLIST_RULE = GOOD_RULE_YAML.replace("{type: tool_in, tools: [x]}",
                                        "{type: recipient_domain_not_in, arg: to, allowlist: %s}")


def test_a_rule_that_names_a_missing_allowlist_file_fails_closed(tmp_path):
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + ALLOWLIST_RULE % "mail_allowlist.yaml"))


def test_a_rule_that_names_a_malformed_allowlist_file_fails_closed(tmp_path):
    write(tmp_path, "internal_domain: a.example\n", "mail_allowlist.yaml")  # no partner_domains
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + ALLOWLIST_RULE % "mail_allowlist.yaml"))


def test_a_rule_that_names_a_good_allowlist_file_loads(tmp_path):
    write(tmp_path, "internal_domain: a.example\npartner_domains: [b.example]\n", "mail_allowlist.yaml")
    loaded = load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + ALLOWLIST_RULE % "mail_allowlist.yaml"))
    assert loaded.rules[0].id == "ORG-001"
    assert load_allowlist_domains(tmp_path / "mail_allowlist.yaml") == {"a.example", "b.example"}


def test_an_inline_domain_list_is_not_allowed(tmp_path):
    inline = GOOD_RULE_YAML.replace("{type: tool_in, tools: [x]}",
                                    "{type: recipient_domain_not_in, arg: to, allowlist: mail_allowlist.yaml, domains: [x.example]}")
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, "schema_version: 0\nrules:\n" + inline))


def test_strict_yaml_rejects_duplicate_keys_and_accepts_plain_documents():
    assert strict_yaml("a: 1\nb: [2]\n") == {"a": 1, "b": [2]}
    with pytest.raises(PolicyError):
        strict_yaml("a: 1\na: 2\n")


def test_the_loader_reads_the_real_allowlist():
    assert "acme.example" in load_allowlist_domains(KNOWLEDGE_DIR / "mail_allowlist.yaml")

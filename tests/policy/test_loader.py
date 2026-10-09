"""Loader hardening found in the Oct 6 review of agent/policy/loader.py. Risks N.75, N.78, P.2 (D-017, D-064).

Fix 1-4 and 6 each came with a test that failed on the old loader. The tests marked "pins" describe behaviour
the old loader already had; they were checked by mutation (loosen the check, watch the test fail)."""

import pytest

from acme import mail
from agent.policy import loader
from agent.policy.loader import KNOWLEDGE_DIR, PolicyError, load_policies, read_allowlist, strict_yaml
from tests.policy.test_schema import ALLOWLIST_RULE, GOOD_RULE_YAML, policy, rejects, write

HEADER = "schema_version: 0\nrules:\n"
GOOD_ALLOWLIST = "internal_domain: a.example\npartner_domains: [b.example]\n"


def load_rule_naming(tmp_path, yaml_name: str):
    """A policy file in tmp_path whose ORG-005-style rule names `yaml_name` (YAML text, quoted if needed)."""
    return load_policies(write(tmp_path, HEADER + ALLOWLIST_RULE % yaml_name))


# --- 1/2: the allowlist can only be a regular file in the policy file's own directory -------------------------


@pytest.mark.parametrize("name", [
    '"../../.env"', "/etc/hosts", '"../mail_allowlist.yaml"', '"mail_allowlist.yaml\\0.txt"', '"a\\0b.yaml"',
    '"mail_allowlist.yaml\\n"', '"sub/mail_allowlist.yaml"', '".."', '".env"', '"mail_allowlist.yaml/"',
])
def test_pins_an_allowlist_name_that_is_not_a_bare_yaml_file_name_is_rejected(tmp_path, name):
    (tmp_path / "mail_allowlist.yaml").write_text(GOOD_ALLOWLIST)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "mail_allowlist.yaml").write_text(GOOD_ALLOWLIST)
    with pytest.raises(PolicyError):
        load_rule_naming(tmp_path, name)


def test_an_allowlist_that_is_a_symlink_to_a_file_outside_is_rejected(tmp_path):
    know, outside = tmp_path / "know", tmp_path / "outside"
    know.mkdir(), outside.mkdir()
    (outside / "evil.yaml").write_text("internal_domain: evil.example\npartner_domains: []\n")
    (know / "link.yaml").symlink_to(outside / "evil.yaml")
    with pytest.raises(PolicyError, match="symlink"):
        load_rule_naming(know, "link.yaml")
    with pytest.raises(PolicyError, match="symlink"):
        read_allowlist(know / "link.yaml")[1]


def test_an_allowlist_that_is_a_symlink_to_a_file_inside_is_also_rejected(tmp_path):
    (tmp_path / "real.yaml").write_text(GOOD_ALLOWLIST)
    (tmp_path / "link.yaml").symlink_to(tmp_path / "real.yaml")
    with pytest.raises(PolicyError, match="symlink"):
        load_rule_naming(tmp_path, "link.yaml")


def test_an_allowlist_that_is_a_directory_is_rejected(tmp_path):
    (tmp_path / "d.yaml").mkdir()
    with pytest.raises(PolicyError):
        load_rule_naming(tmp_path, "d.yaml")


def test_pins_a_plain_allowlist_file_beside_the_policy_file_still_loads(tmp_path):
    (tmp_path / "mail_allowlist.yaml").write_text(GOOD_ALLOWLIST)
    assert load_rule_naming(tmp_path, "mail_allowlist.yaml").allowlist("mail_allowlist.yaml") == {"a.example", "b.example"}


# --- 3: allowlist content is validated as strictly as Acme validates it ---------------------------------------

BAD_ALLOWLISTS = [
    "internal_domain: ''\npartner_domains: []\n",
    "internal_domain: a.example\npartner_domains: ['']\n",
    "internal_domain: 'a b.example'\npartner_domains: []\n",
    "internal_domain: '*'\npartner_domains: []\n",
    "internal_domain: '*.example'\npartner_domains: []\n",
    "internal_domain: Acme.Example\npartner_domains: []\n",
    "internal_domain: a.example\npartner_domains: [B.example]\n",
    "internal_domain: localhost\npartner_domains: []\n",
    "internal_domain: a..example\npartner_domains: []\n",
    "internal_domain: -a.example\npartner_domains: []\n",
    "internal_domain: a.example.\npartner_domains: []\n",
    "internal_domain: user@a.example\npartner_domains: []\n",
    "internal_domain: 1\npartner_domains: []\n",
    "internal_domain: a.example\npartner_domains: [true]\n",
    "internal_domain: a.example\npartner_domains: b.example\n",
    "internal_domain: a.example\n",
    "internal_domain: a.example\npartner_domains: []\nextra: 1\n",
    'internal_domain: "a.example\\n"\npartner_domains: []\n',            # trailing newline (N.88)
    'internal_domain: a.example\npartner_domains: ["b.example\\n"]\n',
    'internal_domain: "a.example "\npartner_domains: []\n',               # trailing and leading space
    'internal_domain: " a.example"\npartner_domains: []\n',
    'internal_domain: "a.example\\t"\npartner_domains: []\n',
]


@pytest.mark.parametrize("body", BAD_ALLOWLISTS)
def test_a_malformed_allowlist_is_rejected_by_the_loader_and_by_acme_alike(tmp_path, body):
    """One list, both parsers (agent/policy/loader.py and acme/mail.py): they must not disagree (N.88)."""
    path = tmp_path / "mail_allowlist.yaml"
    path.write_text(body)
    with pytest.raises(PolicyError):
        read_allowlist(path)[1]
    with pytest.raises(ValueError):  # Acme's own reader: the two files must not disagree about what is valid
        mail.load_allowlist(path)


def test_the_loader_uses_the_same_domain_pattern_as_acme():
    assert loader._DOMAIN.pattern == mail._DOMAIN.pattern  # copied, not imported: agent/ never imports acme/


# --- 4: every way a file can be unreadable or unparseable ends in PolicyError ---------------------------------


def test_an_invalid_utf8_policy_file_is_a_policy_error(tmp_path):
    path = tmp_path / "policies.yaml"
    path.write_bytes(b"schema_version: 0\n\xff\xfe")
    with pytest.raises(PolicyError):
        load_policies(path)


def test_an_invalid_utf8_allowlist_file_is_a_policy_error(tmp_path):
    (tmp_path / "mail_allowlist.yaml").write_bytes(b"internal_domain: a.example\n\xff\xfe")
    with pytest.raises(PolicyError):
        load_rule_naming(tmp_path, "mail_allowlist.yaml")


@pytest.mark.parametrize("text", [
    "? [a, b]\n: 1\n",                                     # a list as a mapping key
    "schema_version: 0\nrules:\n  - ? {a: 1}\n    : 2\n",  # a mapping as a key, nested
    "[" * 5000 + "]" * 5000,                               # nesting deep enough to overflow the parser stack
    "".join("  " * i + "a:\n" for i in range(3000)) + "  " * 3000 + "b: 1\n",
])
def test_odd_yaml_is_a_policy_error_not_another_exception(text):
    with pytest.raises(PolicyError):
        strict_yaml(text)


def test_odd_yaml_in_a_policy_file_is_a_policy_error(tmp_path):
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, "? [a, b]\n: 1\n"))


# --- 6: the allowlist is read once, at load time, and kept (no time-of-check/time-of-use gap) -----------------


def test_the_loaded_policy_keeps_the_allowlist_it_validated(tmp_path):
    allow = tmp_path / "mail_allowlist.yaml"
    allow.write_text(GOOD_ALLOWLIST)
    loaded = load_rule_naming(tmp_path, "mail_allowlist.yaml")
    allow.write_text("internal_domain: changed.example\npartner_domains: []\n")  # edited after load
    assert loaded.allowlist("mail_allowlist.yaml") == {"a.example", "b.example"}


def test_asking_for_an_allowlist_no_rule_names_raises(tmp_path):
    loaded = load_policies(write(tmp_path, HEADER + GOOD_RULE_YAML))
    with pytest.raises(KeyError):
        loaded.allowlist("mail_allowlist.yaml")


def test_the_real_policy_holds_the_same_domains_acme_uses_for_the_external_flag():
    assert load_policies().allowlist("mail_allowlist.yaml") == mail.load_allowlist().allowed
    assert "acme.example" in read_allowlist(KNOWLEDGE_DIR / "mail_allowlist.yaml")[1]


# --- 3/5 pins: duplicate keys at every depth, merge keys, schema_version ------------------------------------

DUP_BASE = ("schema_version: 0\nrules:\n  - id: ORG-001\n    level: org\n    enforced_by: {by}\n    effect: deny\n"
            "    when:\n      - {cond}\n{extra}    message: m\n")


@pytest.mark.parametrize("by, cond, extra", [
    ("runtime", "{type: tool_in, type: tool_in, tools: [x]}", ""),                       # flow mapping in a condition
    ("runtime", "{type: tool_in, tools: [x], tools: [y]}", ""),
    ("runtime", "type: tool_in\n        tools: [x]\n        tools: [y]", ""),              # block mapping in a condition
    ("acme", "{type: tool_in, tools: [x]}", "    acme_check:\n      - {kind: function, ref: a.b, ref: c.d}\n"),
    ("acme", "{type: tool_in, tools: [x]}",
     "    acme_check:\n      - kind: action\n        ref: approval.decide\n        roles: [admin]\n        roles: [meera]\n"),
    ("runtime", "{type: tool_in, tools: [x]}", "    effect: require_approval\n"),            # rule level
])
def test_pins_a_duplicate_key_at_any_depth_is_a_load_error(tmp_path, by, cond, extra):
    with pytest.raises(PolicyError, match="duplicate key"):
        load_policies(write(tmp_path, DUP_BASE.format(by=by, cond=cond, extra=extra)))


def test_pins_a_yaml_merge_key_is_rejected(tmp_path):
    text = (HEADER + "  - &r {id: ORG-001, level: org, enforced_by: runtime, effect: deny,"
            " when: [{type: tool_in, tools: [x]}], message: m}\n  - {<<: *r, id: ORG-002}\n")
    with pytest.raises(PolicyError):
        load_policies(write(tmp_path, text))


@pytest.mark.parametrize("version", [False, True, "0", 0.0, 1, -1, None])
def test_pins_only_the_integer_zero_is_an_accepted_schema_version(version):
    rejects(policy(schema_version=version))


def test_pins_a_missing_schema_version_is_rejected():
    rejects({"rules": policy()["rules"]})


def test_the_internal_domain_is_loaded_apart_from_the_partners_for_org007():
    """D-144: ORG-007 exempts only the allowlist's internal_domain; the partners stay in ORG-005's set only."""
    policies = load_policies()
    assert policies.internal_domain("mail_allowlist.yaml") == "acme.example"
    assert "partner.example" in policies.allowlist("mail_allowlist.yaml")
    with pytest.raises(KeyError):
        policies.internal_domain("other.yaml")

"""Strict loader for policies.yaml. Anything wrong raises PolicyError: the gate must not run on a bad file."""

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from agent.policy.models import MAIL_ALLOWLIST, FieldSourceUntrusted, PolicyFile, RecipientDomainNotIn

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "acme" / "knowledge"
POLICIES_PATH = KNOWLEDGE_DIR / "policies.yaml"
# Copied from acme/mail.py, not imported (agent/ does not import acme/); a test checks the two stay equal.
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class PolicyError(ValueError):
    """The policy file (or a file it names) is invalid. Callers treat this as deny-everything."""


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (plain PyYAML keeps the last one silently)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            line = key_node.start_mark.line + 1
            try:
                duplicate = key in seen
            except TypeError:  # a list or mapping used as a key cannot be hashed
                raise PolicyError(f"mapping key at line {line} must be a plain value") from None
            if duplicate:
                raise PolicyError(f"duplicate key {key!r} at line {line}")
            seen.add(key)
        return super().construct_mapping(node, deep)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"{path} cannot be read: {exc}") from exc


def strict_yaml(text: str):
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except (yaml.YAMLError, RecursionError) as exc:  # RecursionError: nesting deep enough to overflow the parser
        raise PolicyError(f"invalid YAML: {type(exc).__name__}: {str(exc)[:200]}") from exc


def load_allowlist_domains(path: Path | str) -> frozenset[str]:
    """Domains in an allowlist file (`internal_domain` plus `partner_domains`)."""
    return read_allowlist(path)[1]


def read_allowlist(path: Path | str) -> tuple[str, frozenset[str]]:
    """(internal domain, every domain) of an allowlist file. Same file and same shape Acme reads in
    `acme/mail.py` (D-064), with the same domain pattern; a test checks both agree.
    A symlink is refused: the file must be a real file in the directory the policy file names it in."""
    path = Path(path)
    if path.is_symlink():
        raise PolicyError(f"allowlist {path} is a symlink; it must be a regular file")
    raw = strict_yaml(_read(path))
    if (not isinstance(raw, dict) or set(raw) != {"internal_domain", "partner_domains"}
            or not isinstance(raw["partner_domains"], list)):
        raise PolicyError(f"allowlist {path} must have exactly internal_domain (text) and partner_domains (list)")
    domains = [raw["internal_domain"], *raw["partner_domains"]]
    if not all(isinstance(d, str) and _DOMAIN.fullmatch(d) for d in domains):
        raise PolicyError(f"allowlist {path}: every domain must be lowercase like example.com")
    return raw["internal_domain"], frozenset(domains)


def load_policies(path: Path | str = POLICIES_PATH) -> PolicyFile:
    path = Path(path)
    try:
        policies = PolicyFile.model_validate(strict_yaml(_read(path)))
    except ValidationError as exc:
        raise PolicyError(f"{path.name} is invalid:\n{exc}") from exc
    names = set()  # each file a rule needs is read once, here, and kept on the policy (no re-read later)
    for rule in policies.rules:
        for cond in rule.when:
            if isinstance(cond, RecipientDomainNotIn):
                names.add(cond.allowlist)
            elif isinstance(cond, FieldSourceUntrusted) and cond.exempt_recipient_domains == "internal":
                names.add(MAIL_ALLOWLIST)
    read = {name: read_allowlist(path.parent / name) for name in sorted(names)}
    policies.attach_allowlists({n: domains for n, (_, domains) in read.items()},
                               {n: internal for n, (internal, _) in read.items()})
    return policies

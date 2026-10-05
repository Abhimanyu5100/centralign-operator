"""Mail helpers shared by the service layer, the queries and the models: the recipient allowlist,
the external-recipient test, attachment filename rules and the row -> API/page shape.

The allowlist is data in `acme/knowledge/mail_allowlist.yaml` (D-064, risk N.57). A missing, unreadable or
malformed file raises at load, so a broken config can never silently make every recipient internal.
Imports nothing from the rest of Acme, so `models.py` can use the filename pattern.
"""

import json
import os
import re
from pathlib import Path
from typing import NamedTuple

import yaml

ALLOWLIST_PATH = Path(__file__).parent / "knowledge" / "mail_allowlist.yaml"
ALLOWLIST_ENV = "ACME_MAIL_ALLOWLIST"  # tests point this at a temporary file
FOLDERS = ["inbox", "outbox"]
# Bare PDF filenames only (risk N.61): no slash, no spaces; part 6 generates the files.
ATTACHMENT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*\.pdf$"
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class Allowlist(NamedTuple):
    internal_domain: str
    partner_domains: frozenset[str]

    @property
    def allowed(self) -> frozenset[str]:
        return self.partner_domains | {self.internal_domain}


def load_allowlist(path: Path | str | None = None) -> Allowlist:
    path = Path(path or os.environ.get(ALLOWLIST_ENV) or ALLOWLIST_PATH)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"mail allowlist {path} cannot be read: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"internal_domain", "partner_domains"}:
        raise ValueError(f"mail allowlist {path} must have exactly internal_domain and partner_domains")
    internal, partners = raw["internal_domain"], raw["partner_domains"]
    if not isinstance(partners, list):
        raise ValueError(f"mail allowlist {path}: partner_domains must be a list")
    domains = [internal, *partners]
    if not all(isinstance(d, str) and _DOMAIN.match(d) for d in domains):
        raise ValueError(f"mail allowlist {path}: every domain must be lowercase like example.com")
    return Allowlist(internal, frozenset(partners))


def is_external(address: str, allowlist: Allowlist | None = None) -> bool:
    """Exact, case-insensitive match on the part after the last `@`. Anything else, including an address
    with no `@`, is external (fail closed, risk N.56)."""
    domain = address.rpartition("@")[2].strip().lower()
    return domain not in (allowlist or load_allowlist()).allowed


def view(row: dict, *, with_body: bool = True) -> dict:
    """The shape the API and pages show: `attachments` as a list, `external` as a bool."""
    shown = {k: v for k, v in row.items() if k != "attachments_json"}
    shown["attachments"] = json.loads(row["attachments_json"])
    shown["external"] = bool(row["external"])
    if not with_body:
        shown.pop("body")
    return shown

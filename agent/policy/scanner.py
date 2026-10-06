"""Payment and bank-instruction scanner for untrusted text (ORG-006, register P.1 and 4.7).

Deterministic regexes over every string of a tool result tagged `provenance.source == "untrusted"` (mail, PDF
text, browser pages). A match becomes a security finding: logged as a `security_finding` event by the registry
and listed in the run report. The scanner never blocks anything and never changes a result: blocking is Acme's
job (a payment request has no amount, payee or bank field) and the gate's (D-086).

`values` uses the same vocabulary to pull the values a trust-sensitive argument could take (emails, account
numbers, IFSC codes, rupee amounts) out of text; the gate's run facts compare them with the call's arguments
(ORG-007, D-133).
"""

import re
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from agent.normalise import to_paise

POLICY_ID = "ORG-006"
MAX_EXCERPT = 200

_AMOUNT = r"(?:rs\.?|inr|₹)\s?(\d[\d,]*(?:\.\d{1,2})?)"
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")  # upper case only: "abcd0efghij" in prose is not a bank code
PATTERNS = {  # kind -> the patterns that report it (any match)
    "payment_instruction": [re.compile(
        rf"\b(?:transfer|pay|remit|wire|deposit)\b[^.\n]{{0,80}}?(?:{_AMOUNT}|\baccount\b|\ba/c\b)", re.IGNORECASE)],
    "bank_details": [re.compile(r"\b(?:account|a/c|acct)\b\.?\s*(?:no\.?|number|#)?\s*[:\-]?\s*\d[\d \-]{7,22}\d",
                                re.IGNORECASE), _IFSC],
    "bank_change": [re.compile(
        r"\b(?:chang(?:e[ds]?|ing)|updat(?:e[ds]?|ing)|revis(?:e[ds]?|ing)|new)\b[^.\n]{0,40}\bbank\b[^.\n]{0,20}"
        r"\b(?:details|account|a/c)\b",
        re.IGNORECASE)],
}
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_DIGIT_RUN = re.compile(r"\d[\d \-]{7,22}\d")
_LONG_NUMBER = re.compile(r"\d{9,}")


class Finding(BaseModel):
    policy_id: str = POLICY_ID
    kind: str
    origin: str
    excerpt: str


def mask(text: str) -> str:
    """Hide account-like numbers the way Acme's audit does (D-093): 9+ digits keep only their last four."""
    return _LONG_NUMBER.sub(lambda m: "X" * (len(m[0]) - 4) + m[0][-4:], text)


def _line(text: str, at: int) -> str:
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    return text[start:end if end != -1 else len(text)].strip()


def scan(text: str, origin: str) -> list[Finding]:
    found: dict[tuple[str, str], Finding] = {}
    for kind, patterns in PATTERNS.items():
        for match in (m for pattern in patterns for m in pattern.finditer(text)):
            excerpt = mask(_line(text, match.start()))[:MAX_EXCERPT]
            found.setdefault((kind, excerpt), Finding(kind=kind, origin=origin, excerpt=excerpt))
    return list(found.values())


def strings(value: Any) -> Iterator[str]:
    """Every string inside a result, its `provenance` tag left out."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "provenance":
                yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def scan_result(data: dict[str, Any]) -> list[Finding]:
    """Findings in every string of an untrusted tool result, deduplicated. A scanner bug is itself reported
    (kind `scan_failed`) rather than hidden: the scanner cannot block, so it fails loudly."""
    origin = str((data.get("provenance") or {}).get("origin", "unknown"))
    try:
        found: dict[tuple[str, str], Finding] = {}
        for text in strings(data):
            for finding in scan(text, origin):
                found.setdefault((finding.kind, finding.excerpt), finding)
        return list(found.values())
    except Exception as exc:  # noqa: BLE001 - reported, never raised into the tool call
        return [Finding(kind="scan_failed", origin=origin, excerpt=f"{type(exc).__name__}: {exc}"[:MAX_EXCERPT])]


def normalise_value(value: Any) -> str:
    """How an argument value and a value found in text are compared: lower case; digits only for a number
    written with spaces or dashes (an account number); integers as their digits (paise)."""
    text = str(value).strip().lower()
    return re.sub(r"[ \-]", "", text) if re.fullmatch(r"\d[\d \-]*\d", text) else text


def values(text: str) -> set[str]:
    """Normalised emails, account numbers (9-18 digits), IFSC codes and rupee amounts (as paise) in `text`."""
    found = {normalise_value(m[0]) for m in _EMAIL.finditer(text)}
    found |= {normalise_value(m[0]) for m in _IFSC.finditer(text)}
    for match in _DIGIT_RUN.finditer(text):
        digits = normalise_value(match[0])
        if 9 <= len(digits) <= 18:
            found.add(digits)
    for match in re.finditer(_AMOUNT, text, re.IGNORECASE):
        try:
            found.add(str(to_paise(match[1])))
        except ValueError:
            pass
    return found

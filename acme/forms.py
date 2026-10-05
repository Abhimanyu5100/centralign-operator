"""Server-side form parsing with specific, per-field error messages (risks N.42, N.47).

The agent recovers from a rejected form by reading its error text, so every message says what is
expected ("Enter the date as YYYY-MM-DD, for example 2026-10-31"), not just that something is wrong.
`Form` collects errors instead of raising, so one post shows every problem at once.
"""

from datetime import date
from typing import Any

from pydantic import ValidationError

from acme.money import parse_rupees


class Form:
    def __init__(self, raw: dict[str, Any]):
        self.raw = {k: v for k, v in raw.items() if isinstance(v, str)}  # uploads are not accepted
        self.errors: dict[str, str] = {}  # field name -> message; "" is the form-level message

    def _value(self, name: str) -> str:
        return self.raw.get(name, "").strip()

    def error(self, name: str, message: str) -> None:
        self.errors.setdefault(name, message)

    def text(self, name: str, label: str, required: bool = True, max_len: int = 200) -> str | None:
        value = self._value(name)
        if not value:
            if required:
                self.error(name, f"{label} is required")
            return None
        if len(value) > max_len:
            self.error(name, f"{label} must be at most {max_len} characters")
            return None
        return value

    def integer(self, name: str, label: str, required: bool = True) -> int | None:
        value = self._value(name)
        if not value:
            if required:
                self.error(name, f"{label} is required: choose one from the list")
            return None
        if not value.isdigit():
            self.error(name, f"{label} is not valid: choose one from the list")
            return None
        return int(value)

    def day(self, name: str, label: str, required: bool = True) -> date | None:
        value = self._value(name)
        if not value:
            if required:
                self.error(name, f"{label} is required. Enter the date as YYYY-MM-DD, for example 2026-10-31")
            return None
        try:
            return date.fromisoformat(value) if len(value) == 10 else self._bad_date(name, label)
        except ValueError:
            return self._bad_date(name, label)

    def _bad_date(self, name: str, label: str) -> None:
        self.error(name, f"{label} is not a valid date. Enter the date as YYYY-MM-DD, for example 2026-10-31")

    def rupees(self, name: str, label: str, allow_zero: bool = False) -> int | None:
        value = self._value(name)
        if not value:
            self.error(name, f"{label} is required. Enter the amount in rupees without commas, for example 62400.00")
            return None
        try:
            paise = parse_rupees(value)
        except ValueError as exc:
            self.error(name, f"{label}: {exc}")
            return None
        if paise == 0 and not allow_zero:
            self.error(name, f"{label} must be greater than zero")
            return None
        return paise

    def choice(self, name: str, label: str, options: set[str]) -> str | None:
        value = self._value(name)
        if value not in options:
            self.error(name, f"{label} must be one of: {', '.join(sorted(options))}")
            return None
        return value

    def token(self, name: str = "idempotency_token") -> str | None:
        value = self.raw.get(name, "")
        if not 1 <= len(value) <= 100:
            self.error("", "This form has no valid submission token. Reload the page and fill it in again")
            return None
        return value

    def add_validation_error(self, exc: ValidationError, field_map: dict[str, str] | None = None) -> None:
        """Fallback for model rules the field parsers did not catch (e.g. length limits)."""
        for item in exc.errors():
            field = str(item["loc"][0]) if item["loc"] else ""
            self.error((field_map or {}).get(field, field), item["msg"])

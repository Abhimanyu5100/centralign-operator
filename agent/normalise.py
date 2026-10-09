"""Deterministic normalisers for values read from emails, PDFs and requests (register 1.9, 3.2, 1.10).

Each one either returns the canonical value or raises ValueError with the reason: an ambiguous input is never
guessed (the caller asks or reports it instead). Money becomes integer paise, dates ISO `YYYY-MM-DD`, GSTINs
upper case without spaces. (Name matching left on Day 5: the gate asks Acme's own vendor and employee search, D-198.)
"""

import re
from datetime import date, timedelta
from decimal import Decimal

# --- money ----------------------------------------------------------------------------------------------------

_CURRENCY = re.compile(r"^(?:₹|rs\.?|inr)\s*", re.I)
_SUFFIX = re.compile(r"\s*(?:/-|only)$", re.I)
_UNITS = re.compile(r"^(.+?)\s*(lakhs?|lacs?|crores?)$", re.I)
_INDIAN = re.compile(r"[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}")   # 2,50,000 and 12,34,567
_WESTERN = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")           # 250,000


def to_paise(text: str) -> int:
    """'₹2,50,000', 'Rs. 1,234.50', 'INR 7500', '2.5 lakh' -> integer paise. Commas must group digits the
    Indian or the Western way; at most two decimals; no sign, no other separators."""
    s = _SUFFIX.sub("", _CURRENCY.sub("", text.strip())).strip()
    unit = 1
    if m := _UNITS.fullmatch(s):
        s, unit = m.group(1).strip(), 100_000 if m.group(2).lower().startswith("la") else 10_000_000
    whole, dot, frac = s.partition(".")
    if "," in whole and not (_INDIAN.fullmatch(whole) or _WESTERN.fullmatch(whole)):
        raise ValueError(f"{text!r}: commas do not group the digits in thousands, lakhs or crores")
    whole = whole.replace(",", "")
    if not re.fullmatch(r"[0-9]+", whole) or dot and not re.fullmatch(r"[0-9]+", frac):
        raise ValueError(f"{text!r} is not an amount")
    if unit == 1 and len(frac) > 2:
        raise ValueError(f"{text!r} has more than two decimals")
    paise = Decimal(f"{whole}.{frac or '0'}") * unit * 100
    if paise != paise.to_integral_value():
        raise ValueError(f"{text!r} is not a whole number of paise")
    return int(paise)


# --- dates ----------------------------------------------------------------------------------------------------

_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for m in names}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _month(name: str) -> int:
    if name.lower().rstrip(".") not in _MONTHS:
        raise ValueError(f"unknown month {name!r}")
    return _MONTHS[name.lower().rstrip(".")]


def to_iso_date(text: str) -> str:
    """'2025-01-04', '04 Jan 2025', '4th January, 2025', 'Jan 4, 2025', '04/01/2025' (day first, as written in
    India) -> '2025-01-04'. Two-digit years and impossible dates raise."""
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", text.strip(), flags=re.I)
    s = re.sub(r"[\s,]+", " ", s).strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[ -]([A-Za-z]+\.?)[ -](\d{4})", s):
        d, mo, y = int(m[1]), _month(m[2]), int(m[3])
    elif m := re.fullmatch(r"([A-Za-z]+\.?) (\d{1,2}) (\d{4})", s):
        mo, d, y = _month(m[1]), int(m[2]), int(m[3])
    else:
        raise ValueError(f"{text!r} is not a date with a four-digit year")
    return date(y, mo, d).isoformat()  # date() raises for 31 Sep and the like


def next_weekday(name: str, today: date) -> str:
    """'Monday' -> the next Monday strictly after `today` (the run's frozen now), as ISO. Today never counts."""
    if name.strip().lower() not in _WEEKDAYS:
        raise ValueError(f"{name!r} is not a weekday")
    ahead = (_WEEKDAYS.index(name.strip().lower()) - today.weekday() - 1) % 7 + 1
    return (today + timedelta(days=ahead)).isoformat()


# --- identifiers and names ------------------------------------------------------------------------------------

_GSTIN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


def normalise_gstin(text: str) -> str:
    """Format check only (state code, PAN, entity, Z, check character); the sandbox GSTINs carry no real checksum."""
    s = re.sub(r"\s", "", text).upper()
    if not _GSTIN.fullmatch(s):
        raise ValueError(f"{text!r} is not a GSTIN (15 characters: 2 digits, PAN, entity number, Z, check)")
    return s

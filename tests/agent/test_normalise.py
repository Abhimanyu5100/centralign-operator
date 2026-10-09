"""Normalisers (register 1.9, 3.2, 1.10): canonical value or ValueError, never a guess."""

from datetime import date

import pytest

from agent.normalise import next_weekday, normalise_gstin, to_iso_date, to_paise


@pytest.mark.parametrize("text,paise", [
    ("₹1,00,000", 10_000_000), ("Rs. 62,400.00", 6_240_000), ("INR 18,500", 1_850_000), ("Rs 9,518.64", 951_864),
    ("12,34,567.5", 123_456_750), ("250,000", 25_000_000), ("1,234", 123_400), ("18500", 1_850_000),
    ("₹ 500/-", 50_000), ("rs.75 only", 7_500), ("2.5 lakh", 25_000_000), ("1 crore", 1_000_000_000),
    ("₹3 lakhs", 30_000_000), ("0.05", 5), ("1,00,000.00", 10_000_000),
])
def test_amounts_become_integer_paise(text, paise):
    assert to_paise(text) == paise


@pytest.mark.parametrize("text", [
    "1,0000", "10,00", "62.400,00", "1.234.567", "-500", "12.345", "Rs", "", "five hundred", "1 00 000",
    "1,00,00", "0.00000001 lakh", "₹1,00,000.5.0", "١٢٣",
])
def test_ambiguous_or_malformed_amounts_raise(text):
    with pytest.raises(ValueError):
        to_paise(text)


@pytest.mark.parametrize("text,iso", [
    ("2026-10-03", "2026-10-03"), ("03 Oct 2026", "2026-10-03"), ("3 October 2026", "2026-10-03"),
    ("3rd October, 2026", "2026-10-03"), ("Oct 3, 2026", "2026-10-03"), ("12/10/2026", "2026-10-12"),
    ("12-10-2026", "2026-10-12"), ("02 Nov 2026", "2026-11-02"), ("12th Sept 2026", "2026-09-12"),
    ("29 Feb 2028", "2028-02-29"),
])
def test_dates_become_iso_day_first(text, iso):
    assert to_iso_date(text) == iso


@pytest.mark.parametrize("text", ["12/10/26", "31 Sep 2026", "29 Feb 2027", "13/13/2026", "Octember 3 2026",
                                  "next week", "2026/10/03"])
def test_bad_dates_raise(text):
    with pytest.raises(ValueError):
        to_iso_date(text)


def test_a_weekday_is_the_next_one_strictly_after_today():
    wednesday = date(2026, 10, 7)
    assert next_weekday("Monday", wednesday) == "2026-10-12"
    assert next_weekday("thursday", wednesday) == "2026-10-08"
    assert next_weekday("Wednesday", wednesday) == "2026-10-14"  # today never counts
    with pytest.raises(ValueError):
        next_weekday("Someday", wednesday)


def test_gstin_format():
    assert normalise_gstin(" 27aabcs4821k1z3 ") == "27AABCS4821K1Z3"
    for bad in ("27AABCS4821K1Y3", "27AABCS4821K1Z", "2AABCS4821K1Z3X", "27AABCS4821K0Z3", ""):
        with pytest.raises(ValueError):
            normalise_gstin(bad)

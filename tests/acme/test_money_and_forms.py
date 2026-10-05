"""Rupee parsing and form error messages (risks N.47, N.42, 1.9). The agent recovers by reading these."""

import pytest

from acme.forms import Form
from acme.money import AMOUNT_HELP, format_inr, parse_rupees


@pytest.mark.parametrize("text, paise", [
    ("62400", 6_240_000), ("62400.00", 6_240_000), ("62400.5", 6_240_050), ("62400.50", 6_240_050),
    ("0.10", 10), ("0.07", 7), ("1.15", 115), ("  18500  ", 1_850_000), ("0", 0), ("999999999999.99", 99_999_999_999_999),
])
def test_parse_rupees_is_exact(text, paise):
    assert parse_rupees(text) == paise


@pytest.mark.parametrize("text", ["1,00,000", "62,400.00", "₹62400", "Rs. 62400", "-5", "+5", "1e5", "62400.123",
                                  "", "abc", "62 400", "1000000000000", ".5", "5."])
def test_parse_rupees_rejects_anything_but_plain_decimals_with_the_exact_hint(text):
    with pytest.raises(ValueError) as exc:
        parse_rupees(text)
    assert str(exc.value) == "Enter the amount in rupees without commas, for example 62400.00" == AMOUNT_HELP


@pytest.mark.parametrize("paise, text", [(6_240_000, "₹62,400.00"), (5, "₹0.05"), (12_345_678_900, "₹12,34,56,789.00"),
                                         (100_000_00, "₹1,00,000.00"), (99_999, "₹999.99"), (1_234_567, "₹12,345.67")])
def test_format_inr_uses_indian_grouping(paise, text):
    assert format_inr(paise) == text


def test_amount_error_names_the_field_and_says_what_to_type():
    form = Form({"amount": "1,00,000"})
    assert form.rupees("amount", "Total including tax") is None
    assert form.errors["amount"] == "Total including tax: Enter the amount in rupees without commas, for example 62400.00"


def test_missing_and_zero_amounts_have_their_own_messages():
    form = Form({"amount": "0.00"})
    form.rupees("amount", "Total including tax")
    form.rupees("tax", "Tax", allow_zero=True)
    assert form.errors == {
        "amount": "Total including tax must be greater than zero",
        "tax": "Tax is required. Enter the amount in rupees without commas, for example 62400.00",
    }


def test_zero_tax_is_allowed():
    assert Form({"tax": "0.00"}).rupees("tax", "Tax", allow_zero=True) == 0


@pytest.mark.parametrize("value", ["31/10/2026", "2026-13-01", "2026-10-1", "tomorrow", "20261031"])
def test_bad_dates_say_the_expected_format(value):
    form = Form({"due_date": value})
    assert form.day("due_date", "Due date") is None
    assert form.errors["due_date"] == "Due date is not a valid date. Enter the date as YYYY-MM-DD, for example 2026-10-31"


def test_required_text_integer_choice_and_token_messages():
    form = Form({"vendor_id": "abc", "invoice_no": "  ", "type": "phone"})
    form.integer("vendor_id", "Vendor")
    form.text("invoice_no", "Invoice number")
    form.choice("type", "Type", {"laptop", "accounts"})
    form.token()
    assert form.errors == {
        "vendor_id": "Vendor is not valid: choose one from the list",
        "invoice_no": "Invoice number is required",
        "type": "Type must be one of: accounts, laptop",
        "": "This form has no valid submission token. Reload the page and fill it in again",
    }


def test_too_long_text_is_reported_not_truncated():
    form = Form({"invoice_no": "X" * 41})
    assert form.text("invoice_no", "Invoice number", max_len=40) is None
    assert form.errors["invoice_no"] == "Invoice number must be at most 40 characters"


def test_one_post_reports_every_problem():
    form = Form({})
    form.text("a", "A")
    form.day("b", "B")
    form.rupees("c", "C")
    assert set(form.errors) == {"a", "b", "c"}

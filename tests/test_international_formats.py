import io

import pytest
from reportlab.pdfgen import canvas

from app.core import money, parse_statement, read_pdf, reconcile


def statement(doc_id, currency, period, interest, interest_text=None):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, invariant=True)
    lines = [
        "Loan: DEMO-INTL",
        f"Currency: {currency}",
        f"Period end: {period}",
        f"Tranche T1 | Principal: 1000.00 | Interest: {interest_text or f'{interest}.00'}",
        f"Stated principal plus interest total: {1000 + interest}.00",
    ]
    for index, line in enumerate(lines):
        pdf.drawString(40, 750 - index * 20, line)
    pdf.save()
    doc = read_pdf(stream.getvalue(), f"{doc_id}.pdf", doc_id)
    doc["statement"] = parse_statement(doc)
    return doc


@pytest.mark.parametrize("currency, period", [("EUR", "2026/10/31"), ("GBP", "31 Oct 2026"), ("INR", "2026-10-31")])
def test_same_currency_and_equivalent_dates(currency, period):
    docs = [
        statement("a", currency, "2026-10-31", 100),
        statement("b", currency, period, 125),
    ]
    findings, _ = reconcile(docs)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "confirmed"
    assert finding["field"] == "interest"
    assert finding["difference"] == "25.00"
    assert finding["message"].endswith(f"25.00 {currency}.")
    assert {source.split(":")[0] for source in finding["sources"]} == {"a", "b"}


@pytest.mark.parametrize("currency,period,expected", [
    ("USD", "2026-10-31", "identity_mismatch"),
    ("EUR", "10/11/2026", "unsupported_date"),
])
def test_cross_currency_and_ambiguous_dates_require_review(currency, period, expected):
    findings, _ = reconcile([
        statement("a", "EUR", "2026-10-31", 100),
        statement("b", currency, period, 125),
    ])
    assert any(f["type"] == expected for f in findings)
    assert all(f["severity"] == "review" for f in findings)


@pytest.mark.parametrize("invalid_amount", ["100.005", "1,00.00", "1,,00.00"])
def test_malformed_tranche_cannot_become_a_clean_match(invalid_amount):
    valid = statement("a", "EUR", "2026-10-31", 100)
    invalid = statement("b", "EUR", "2026-10-31", 100, interest_text=invalid_amount)
    findings, _ = reconcile([valid, invalid])
    assert invalid["statement"]["tranches"] == []
    assert any(f["type"] == "partial_extraction" for f in findings)
    assert all(f["severity"] == "review" for f in findings)


@pytest.mark.parametrize("amount, expected", [
    ("1,234.56", "1234.56"),
    ("12,34,567.89", "1234567.89"),
    ("(12,34,567.89)", "-1234567.89"),
])
def test_valid_western_and_indian_digit_grouping(amount, expected):
    assert str(money(amount)) == expected


@pytest.mark.parametrize("amount", ["12,34.56", "1,,234.56", ",123.45", "1.234,56"])
def test_invalid_digit_grouping_rejected_by_calculator(amount):
    with pytest.raises(ValueError, match="digit grouping"):
        money(amount)

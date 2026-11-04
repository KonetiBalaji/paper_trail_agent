import io

import pytest
from reportlab.pdfgen import canvas

from app.core import parse_statement, read_pdf, reconcile


def statement(doc_id, currency, period, interest):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, invariant=True)
    lines = [
        "Loan: DEMO-INTL",
        f"Currency: {currency}",
        f"Period end: {period}",
        f"Tranche T1 | Principal: 1000.00 | Interest: {interest}.00",
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

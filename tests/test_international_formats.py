import io

import pytest
from reportlab.pdfgen import canvas

from app.core import money, parse_statement, read_pdf, reconcile


def statement(doc_id, currency, period, interest, interest_text=None, extra_lines=(), period_label="Period end"):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, invariant=True)
    lines = [
        "Loan: DEMO-INTL",
        f"Currency: {currency}",
        f"{period_label}: {period}",
        f"Tranche T1 | Principal: 1000.00 | Interest: {interest_text or f'{interest}.00'}",
        f"Stated principal plus interest total: {1000 + interest}.00",
    ]
    for index, line in enumerate([*lines, *extra_lines]):
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


@pytest.mark.parametrize("malformed_line", [
    "Stated principal plus interest total: 1100.005",
    "Opening balance: 1,00.00",
    "Balance carried forward: 1,,100.00",
])
def test_malformed_labeled_amount_requires_review_even_with_valid_total(malformed_line):
    doc = statement("a", "EUR", "2026-10-31", 100, extra_lines=[malformed_line])
    findings, _ = reconcile([doc])
    issue = next(item for item in doc["issues"] if item["type"] == "partial_extraction")
    assert any(line["id"] == issue["source"] and line["text"] == malformed_line
               for line in doc["lines"])
    assert findings and all(finding["severity"] == "review" for finding in findings)


@pytest.mark.parametrize("period", ["20261031", "2026-W44-6", "2026-10-31 revised", "31 Okt 2026"])
def test_unsupported_period_labels_require_review(period):
    doc = statement("a", "EUR", period, 100)
    findings, _ = reconcile([doc])
    assert doc["statement"]["period_end"] is None
    assert any(finding["type"] == "unsupported_date" for finding in findings)
    assert all(finding["severity"] == "review" for finding in findings)


def test_spanish_period_label_matches_an_equivalent_iso_period():
    docs = [
        statement("a", "EUR", "2026-10-31", 100),
        statement("b", "EUR", "31 de octubre de 2026", 125, period_label="Fecha de corte"),
    ]
    findings, _ = reconcile(docs)
    assert docs[1]["statement"]["period_end"] == "2026-10-31"
    finding, = findings
    assert finding["severity"] == "confirmed"
    assert finding["difference"] == "25.00"


@pytest.mark.parametrize("period", ["31/10/2026", "31 de febrero de 2026"])
def test_invalid_spanish_period_requires_review(period):
    doc = statement("a", "EUR", period, 100, period_label="Fecha de corte")
    findings, _ = reconcile([doc])
    assert doc["statement"]["period_end"] is None
    assert any(finding["type"] == "unsupported_date" for finding in findings)


def test_spanish_loan_layout_requires_gated_mapping(tmp_path):
    from app.layout_proposals import Proposal, trial
    from scripts.generate_benchmark_fixtures import render, table

    mapping = Proposal(
        id="spanish_loan_trial", marker="Layout: PTA-SPANISH-LOAN-V1",
        header="Tramo Capital Intereses", kind="loan",
        columns=("principal", "interest"), max_pages=1,
    )
    path = tmp_path / "spanish-statement.pdf"
    render(path, {"lender": "Prestamista ficticio", "pages": [[
        mapping.marker,
        "Número de préstamo: FICTICIO-001",
        "Moneda: EUR",
        "Fecha de corte: 31 de octubre de 2026",
        table(["Tramo", "Capital", "Intereses"], [
            ["T1", "1000.00", "100.00"], ["T2", "2000.00", "200.00"],
        ]),
        "Total de capital e intereses: 3350.00",
    ]]})
    raw = path.read_bytes()
    unreviewed = read_pdf(raw, path.name, "doc1")
    unreviewed["statement"] = parse_statement(unreviewed)
    findings, _ = reconcile([unreviewed])
    assert any(finding["type"] == "layout_not_promoted" for finding in findings)
    assert all(finding["severity"] == "review" for finding in findings)

    candidate = read_pdf(raw, path.name, "doc1")
    with trial([mapping]):
        candidate["statement"] = parse_statement(candidate)
        findings, _ = reconcile([candidate])
    finding, = findings
    assert candidate["layout_trial"]["promoted"] is False
    assert candidate["statement"]["loan_id"] == "FICTICIO-001"
    assert candidate["statement"]["currency"] == "EUR"
    assert candidate["statement"]["period_end"] == "2026-10-31"
    assert finding["severity"] == "confirmed"
    assert finding["computed"] == "3300.00" and finding["difference"] == "50.00"
    assert len(finding["sources"]) == 3

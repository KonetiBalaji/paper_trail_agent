# Paper Trail Agent synthetic fixtures

All documents are fictional and suitable for a public repository and demo. Amounts are USD decimal strings. No interest-rate or day-count assumptions are tested: the calculator checks the explicitly stated principal-plus-interest total.

| Set | Expected outcome |
| --- | --- |
| clean | Zero discrepancies; both documents total 3300.00. |
| contradiction | T1 interest is 100.00 vs 125.00; both individual totals are correct. One cross-document finding. |
| math_error | B states 3350.00, but its rows total 3300.00. One arithmetic finding. |
| messy | B is image-only with no text layer: ocr_required plus comparison_skipped, zero confirmed findings. Its different period and omitted T2 are ground-truth details, not facts the app can extract without OCR. |
| bank_clean | Opening 1000.00 + credit 100.00 - debit 125.00 = closing 975.00. No findings. |
| bank_error | Same rows, closing stated 1000.00 vs computed 975.00. One incorrect_closing_balance finding, 25.00 too high. |

Each loan folder contains two PDFs and ground_truth.json. Bank folders track JSON ground truth; run `python scripts/generate_bank_fixtures.py` to generate their bank.pdf files locally. Bank PDFs are generated in test setup and temporary evaluation folders, so a fresh clone needs no precommitted bank binaries. Visible L01-style labels are stable loan fixture references; production citations derive page/line or bounding boxes from the parser.

## Evaluation sequence

1. Verify calculator amounts using Decimal, never binary floating point or model arithmetic.
2. Compare extracted fields against each document's ground truth. Track missing and wrong fields separately.
3. Compare findings by type, document, tranche and field. Measure precision and recall, including zero false positives on clean documents.
4. Check citations resolve to the correct PDF page and actual figure. Check export matches UI findings.
5. For image-only B, a parser without OCR must report unsupported extraction. An OCR-enabled parser should recover fields and flag period mismatch for review.

Run `python scripts/generate_fixtures.py` to regenerate. Requires reportlab and PyMuPDF. These fixtures test basic correctness only; add diverse layouts, multi-page statements, rounding, duplicate transactions and adversarial document text before claiming broad accuracy.

Run `python scripts/evaluate.py` for the six-case offline evaluation. It needs no API key, checks confirmed counts and expected amounts, and requires every confirmed source to resolve to a real extracted line.

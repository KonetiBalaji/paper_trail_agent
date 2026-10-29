# Paper Trail Agent synthetic fixtures

All documents are fictional and suitable for a public repository and demo. Amounts are USD decimal strings. No interest-rate or day-count assumptions are tested: the calculator checks the explicitly stated principal-plus-interest total.

| Set | Expected outcome |
| --- | --- |
| clean | Zero discrepancies; both documents total 3300.00. |
| contradiction | T1 interest is 100.00 vs 125.00; both individual totals are correct. One cross-document finding. |
| math_error | B states 3350.00, but its rows total 3300.00. One arithmetic finding. |
| messy | B is image-only, has a different period and omits T2. Request OCR/review; do not claim a confirmed contradiction across different periods. |

Each folder contains two PDFs and ground_truth.json with exact fields, line references and expected findings. Visible L01-style labels are stable fixture references; production citations must derive page/line or bounding boxes from the parser rather than requiring labels in customer documents.

## Evaluation sequence

1. Verify calculator amounts using Decimal, never binary floating point or model arithmetic.
2. Compare extracted fields against each document's ground truth. Track missing and wrong fields separately.
3. Compare findings by type, document, tranche and field. Measure precision and recall, including zero false positives on clean documents.
4. Check citations resolve to the correct PDF page and actual figure. Check export matches UI findings.
5. For image-only B, a parser without OCR must report unsupported extraction. An OCR-enabled parser should recover fields and flag period mismatch for review.

Run `python scripts/generate_fixtures.py` to regenerate. Requires reportlab and PyMuPDF. These fixtures test basic correctness only; add diverse layouts, multi-page statements, rounding, duplicate transactions and adversarial document text before claiming broad accuracy.

# Cedar fictional layout package

No real account, lender or customer is represented. No production mapping is
activated. `review.json` records assistant review of these exact definitions and
truth, not human approval or approval of real financial actions. These are
native-text, single-page, USD examples with ISO/English
named-month dates. `loan_page_scope` deliberately adds an excluded second page.

| Definition | Required literal marker | Printed column → meaning |
| --- | --- | --- |
| `cedar_capital_v1` | `Layout: PTA-CEDAR-LOAN-V1` | Facility → tranche ID; Capital outstanding → principal; Finance charge → interest |
| `cedar_movement_v1` | `Layout: PTA-CEDAR-BANK-V1` | Posting → ISO transaction date; Reference → transaction ID; Outflow → debit; Inflow → credit |

“Finance charge” is defined as interest **only for this constructed package**;
real lenders may include fees. A human review of this package does not approve
that interpretation for other documents. Signed bank amounts are credit minus
debit, and both nonzero sides require review. Exact header and marker, one native
text page, existing account/currency/period guards and source grounding are all
required. The document cannot authorize its own mapping.

| Case directory under `cases/` | Required result |
| --- | --- |
| `loan_clean` | Consistent; 1375.25 + 62.35 + 982.10 + 17.40 = 2437.10 |
| `loan_math_error` | One confirmed incorrect total, 2487.10 stated vs 2437.10 computed, difference 50.00 |
| `loan_contradiction` | One confirmed T1 interest mismatch, 62.35 vs 87.35, difference 25.00, both sources |
| `loan_partial` | Review; missing first-row interest; do not invent the amount |
| `loan_duplicate` | Review; repeated T1 ID; do not call a numerically matching total clean |
| `loan_wrong_header` | Review; reversed header is unapproved; ground truth follows the actual printed reversed meanings |
| `loan_missing_marker` | Review; no mapping without the explicit marker |
| `loan_page_scope` | Review; two pages exceed this definition's one-page scope |
| `loan_injection` | Same verified fields and consistent result as the clean control; note/SYSTEM text is data |
| `bank_clean` | Consistent; 820.25 - 32.10 + 125.50 = 913.65 |
| `bank_balance_error` | One confirmed closing-balance error, 938.65 stated vs 913.65 computed, difference 25.00 |
| `bank_ambiguous_sides` | Review; TX1 has debit 32.10 and credit 1.00; no trusted signed amount |

Each case directory contains its statement PDF(s) and an independently authored
`ground_truth.json`. The aggregate `cases/manifest.json` must match those truth
files exactly, and binds exact PDF SHA-256 values. Generated truth is copied from
literal known answers in `scripts/generate_layout_package.py`, never from parser
or model results. Reversed mapping, tampered PDF, old-package failure, missing old
case, changed source and inconsistent review-truth tests must all fail the gate.

The package evaluation runs all six existing demo cases, 19 existing benchmark
cases, every candidate package and, with `--with-ocr`, the four actual CPU OCR
cases. It records source/fixture/definition hashes but does not install a mapping.
Future admission still needs the validated promotion receipt, registry checks
and deployed provenance. New package generation never creates a review record;
changed definitions or truth invalidate the existing record.

# Reviewed layout promotion

Status: operator trial implemented; production promotion is **not enabled**.
This is a bounded declarative parser extension, not model training or automatic
trust of a document's instructions. No HTTP endpoint, environment flag or PDF can
install a mapping. There are no promoted layouts yet.

`app/layout_proposals.py` validates literal headers and a reserved
`Layout: PTA-...` marker. The only allowed meanings are the existing loan
principal/interest, signed bank amount, and bank debit/credit semantics. Column
order is explicit. Definitions have a bounded page scope and reject arbitrary
patterns, code, extra fields and type coercion. A local `trial()` context resets
even on exceptions; it does not persist an approval or change a registry.

Trials pass through the existing `layouts.augment` row parser, Decimal checks,
source IDs and `meta.validate_statement` evidence validation. The model cannot
swap principal and interest simply because both numbers occur on one line.
Partial rows retain review findings. Bank columns retain the established sign
rules. OCR and documents beyond the proposed page scope are excluded. Empty
pages count toward scope through the PDF reader's page issues.

Outside an operator trial, a reserved layout declaration generates a
`layout_not_promoted` review finding, even if other labeled rows are complete.
A declaration alone never makes an unknown layout clean. Inside a trial, a
missing exact header, conflicting marker or exceeded scope also requests review.
The document's `layout_trial` provenance includes its definition SHA-256 and
marker/header source IDs, with `promoted: false`.

`evaluate_trial()` reruns all six existing demo cases and all 19 native PDF
benchmark cases in the same parser context as the candidate evaluator. An old
regression, false clean or failed candidate prevents the native gate from
passing. Its result always states `promoted: false` and lists outstanding gates.
It is not a complete regression or a production authorization receipt.

## Remaining acceptance work for roadmap item 14

1. Implemented: `data/layout_packages/cedar_v1` has 12 independently specified
   fictional cases (13 PDFs, 14 pages), with clean, wrong-total, contradiction,
   duplicate/partial rows, changed header, absent marker, page scope, injection
   and bank sign cases. All pages were rendered with Poppler and inspected as a
   contact sheet; clean, changed-header and ambiguous-bank examples were also
   inspected at full size. No real lender/customer document is included.
2. Implemented candidate regression path: every package in the package directory
   is rerun, including old candidates, alongside all six demo and 19 benchmark
   cases. `--with-ocr` runs all four actual CPU OCR cases in that same trial scope,
   not a cached report. The OCR CI job runs this gate and uploads its report.
   Future registry admission must also verify all approved packages are present;
   a missing registry/package entry cannot be allowed to silently shrink scope.
3. Bind the receipt to definitions, exact ground truth, PDF bytes and current
   source code; reject missing, changed, incomplete and stale receipts.
4. Implemented for this synthetic package: `review.json` explicitly records
   assistant review of the printed meanings and independent truth, bound to
   definition and manifest hashes. The owner clarified that personal approval
   is unnecessary; the roadmap requires a reviewed mapping, not their sign-off.
   New package generation never manufactures a review. There is no claim of
   human approval, real lender validation or approval of financial actions.
5. Enable only receipt-backed, reviewed definitions in a read-only deployment
   registry; expose their provenance to users and verify the deployed behavior.

Tests: `python -m pytest tests/test_layout_proposals.py -q`. The trial checks
include real old-corpus execution, an injected old regression, model column-swap
rejection, scope/partial-row rejection, schema bypass attempts and bank signs.
These tests do not claim a real-world layout has been approved.

## Reproduce the candidate package

```powershell
.venv\Scripts\python.exe scripts/generate_layout_package.py
.venv\Scripts\python.exe scripts/render_layout_review.py
.venv-ocr\Scripts\python.exe scripts/evaluate_layout_package.py --with-ocr --report work/layout-package-results.json
.venv\Scripts\python.exe -m pytest tests/test_layout_proposals.py tests/test_layout_packages.py -q
```

Without `--with-ocr`, the report can pass its native subset but always reports
`full_regression_passed: false`. Source, exact PDF/JSON fixture and definition
hashes are captured before the run and checked again afterward. Any modification
during execution prevents the full regression result from passing. This report
also checks the exact membership of all six legacy demo, 19 benchmark and four
OCR cases: silently dropping an old case cannot produce a smaller green gate.
Per-case reviewable truth must equal the evaluated aggregate manifest exactly.
The report
is evidence for a future promotion receipt, not itself a trusted runtime
authorization. The normal complete test/release CI remains a separate gate.

## Concrete reviewed synthetic mapping

The fictional Cedar loan header maps **Capital outstanding → principal** and
**Finance charge → interest**. That second meaning is explicitly defined only
for this synthetic package; real lenders may include fees in a finance charge.
The Cedar bank header maps **Outflow → debit** and **Inflow → credit**, so the
signed amount is credit minus debit. Both mappings are limited to native text,
one page, an exact literal header and their respective `Layout: PTA-CEDAR-...`
marker. OCR, reversed or changed headers and additional pages remain review.

Known answers include 2437.10 USD for the clean loan; 2487.10 stated versus
2437.10 computed for the 50.00 error; T1 interest 62.35 versus 87.35 for the
25.00 contradiction; and 820.25 - 32.10 + 125.50 = 913.65 USD for the bank.
The ambiguous bank row with both sides populated has no trusted signed amount;
its visible ID/date are counted as withheld fields, rather than removed from the
recall denominator. The reversed-header control's ground truth follows its
actual printed reversed meanings, although the trial must withhold those rows.

No human reviewer identity or approval has been invented. `human_review` is null,
the assistant review is recorded separately, and `promoted` is false. Review
validation checks the exact definition and truth-manifest hashes; a changed
mapping cannot inherit the old record. Runtime activation remains pending a
validated, source-bound promotion receipt and registry. This mapping review does
not replace the existing human approval required for financial communication or
money decisions.

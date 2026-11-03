# Reviewed layout promotion

Status: registry and receipt validation implemented; Cedar is active locally and
on Vercel after its complete corpus gate. All five release CI jobs pass; 29 hosted
checks verify the exact receipt, $50/$25/bank results, highlighted sources, saved
provenance and cleanup. See `docs/hosted-layout-results.json` and the testing ledger.
This is a bounded declarative parser extension, not model training or automatic
trust of a document's instructions. No HTTP endpoint, environment flag or PDF can
install a mapping. Only a current, source-bound reviewed receipt can activate the
two fictional Cedar mappings.

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

Outside an operator trial, a reserved declaration must match an active registry
mapping or it generates a `layout_not_promoted` review finding, even if other
labeled rows are complete. A declaration alone never makes an unknown layout
clean. Inside a trial, a
missing exact header, conflicting marker or exceeded scope also requests review.
The document's `layout_trial` provenance includes its definition SHA-256 and
marker/header source IDs, with `promoted: false`.

`evaluate_trial()` reruns all six existing demo cases and all 19 native PDF
benchmark cases in the same parser context as the candidate evaluator. An old
regression, false clean or failed candidate prevents the native gate from
passing. Its result always states `promoted: false` and lists outstanding gates.
It is not a complete regression or a production authorization receipt.

## Admission requirements

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
   `data/layout_packages/inventory.json` preserves the exact admitted versions,
   definitions, truth manifests and case IDs. Deleting an old directory cannot
   silently remove its regressions. Changed formats get a new package version;
   the old oracle is retained. Admission requires exact inventory and package
   membership; unlisted candidates cannot activate.
3. Implemented: the receipt binds definitions, review records, exact ground truth,
   PDF bytes, current Python/frontend source and installed runtime dependencies.
   Missing, changed, incomplete or stale evidence disables the reviewed mapping.
4. Implemented for this synthetic package: `review.json` explicitly records
   assistant review of the printed meanings and independent truth, bound to
   definition and manifest hashes. The owner clarified that personal approval
   is unnecessary; the roadmap requires a reviewed mapping, not their sign-off.
   New package generation never manufactures a review. There is no claim of
   human approval, real lender validation or approval of financial actions.
5. Implemented: `data/layout_registry.json` pins the full report SHA-256 and
   admitted package list. `GET /api/layouts` reads this evidence with no model,
   OCR or regression execution. The UI shows state, scope, review kind and
   receipt. Native and direct model-validated cases retain `layout_support`
   provenance. Deployment checks demonstrate the fixed synthetic cases.

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

For admission, write the complete evaluation to the fixed
`docs/layout-package-results.json`, then run `python scripts/promote_layouts.py`.
The publisher validates current source/fixture hashes and underlying corpus
results before atomically replacing the registry. `--check` verifies without
writes and is a release CI step. It never invents missing evaluation evidence.

Hash validation detects stale or changed evidence; it is not a cryptographic
attestation against an administrator rewriting the trusted repository. Repository
review and release CI are the trust boundary. Runtime does not need the excluded
test directory: it verifies deployed Python/frontend source, installed dependency
versions, fixture bytes and corpus/review results. Publishing and CI additionally
verify the full test/tool/config snapshot.

The oversized-upload rejection PDF is deliberately Git-ignored: local fixture
generation materializes it, while clean clones rebuild it in memory. The receipt
binds its exact canonical byte hash under a `virtual:` key in both environments;
if a local materialized copy exists, its bytes must also match. This retains the
actual rejection test without requiring an ignored 10-MiB file in deployment.
Unused generated bank-copy PDFs are excluded because the six-case evaluator
always generates its bank inputs in an owned temporary directory. Their truth
and generator code remain bound. Other committed PDF/JSON fixtures are hashed
directly. The first deployment exposed this portability mismatch and correctly
remained stale; no gate was bypassed to activate it.

Without `--with-ocr`, the report can pass its native subset but always reports
`full_regression_passed: false`. Source, exact PDF/JSON fixture and definition
hashes are captured before the run and checked again afterward. Any modification
during execution prevents the full regression result from passing. This report
also checks the exact membership of all six legacy demo, 19 benchmark and four
OCR cases: silently dropping an old case cannot produce a smaller green gate.
Per-case reviewable truth must equal the evaluated aggregate manifest exactly.
The report becomes eligible for runtime admission only through the publisher's
validation and explicit registry entry. The normal complete test/release CI
remains a separate gate. The service has no HTTP registration/promotion route.

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
the assistant review is recorded separately, and `promoted` is false in the
evaluation artifact because evaluation does not install a mapping. The separate
registry controls activation. Review
validation checks the exact definition and truth-manifest hashes; a changed
mapping cannot inherit the old record. Activation requires the validated,
source-bound promotion receipt and registry. This mapping review does
not replace the existing human approval required for financial communication or
money decisions.
## From reviewer feedback to a benchmark case

Open the eval candidate from a confirmed or rejected finding. Use its report
version and cited source IDs to reproduce the behavior within the workspace.
Create a fictional PDF that preserves the relevant layout and arithmetic. Keep
the original report, private notes and PDFs in the workspace.

Derive expected fields, citations and finding outcomes independently from the
fictional PDF. Record the derivation in the package review. Run the candidate
and full native and OCR regression with `scripts/evaluate_layout_package.py
--with-ocr --report docs/layout-package-results.json`. After the gate passes,
run `scripts/promote_layouts.py` to write the receipt and rerun it with
`--check` to verify the registry.
A reviewer decision starts this process. The ground truth and regression
results determine admission.

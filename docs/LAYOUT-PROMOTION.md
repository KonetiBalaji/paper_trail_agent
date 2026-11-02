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

1. Add independently specified, cleared fictional PDF/truth candidate packages,
   including varied values, clean, wrong-total, contradictory and review cases.
   Render and inspect the actual candidate PDFs.
2. Include all prior promoted packages and the four actual CPU OCR cases in the
   promotion gate, alongside native regressions and the normal release tests.
3. Bind the receipt to definitions, exact ground truth, PDF bytes and current
   source code; reject missing, changed, incomplete and stale receipts.
4. Obtain a real human review of the concrete financial column mapping and its
   truth package. Do not invent a reviewer or treat model output as approval.
5. Enable only receipt-backed, reviewed definitions in a read-only deployment
   registry; expose their provenance to users and verify the deployed behavior.

Tests: `python -m pytest tests/test_layout_proposals.py -q`. The trial checks
include real old-corpus execution, an injected old regression, model column-swap
rejection, scope/partial-row rejection, schema bypass attempts and bank signs.
These tests do not claim a real-world layout has been approved.

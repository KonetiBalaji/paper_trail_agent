# Fictional extended PDF benchmark

All lenders, accounts and statements here are fictional. This corpus tests a small documented set of layout rules, not real-world banking coverage. Rendered pages use different lenders, wording, table columns, repeated headers and multi-page continuations.

`manifest.json` and each case's `ground_truth.json` contain explicit field truth, expected machine status, confirmed findings, review types and PDF hashes. The generator's known answers are independent of the app parser. Regeneration is byte-checked in tests:

```powershell
.venv\Scripts\python.exe scripts\generate_benchmark_fixtures.py
.venv\Scripts\python.exe scripts\benchmark.py
```

Cases cover clean and wrong loan totals, a $25 cross-statement interest difference, reversed principal/interest columns, cross-page rows and totals, a linked split row, duplicate/partial rows, signed and debit/credit bank tables, carried balances (including a $20 error), instruction-like notes, conflicting identity, ambiguous dates, currency mismatch and a missing tranche. Corrupt and oversized inputs must be rejected. The intentionally oversized padding PDF is regenerated in memory on a clean clone and excluded from Git; its expected bytes are still hash-checked.

A partial row's visible identifier and principal count in the field-recall denominator even though the extractor withholds the incomplete row from calculations. Those two expected review abstentions count as false negatives, not as successful extraction. This avoids a misleading perfect-recall claim. A conflicting account ID has no unique ground-truth value and is cleared for review.

Instruction-like notes remain source data. Tests compare findings, calculations and the financial projection of exports against the control. Complete exports naturally retain the extra evidence lines; byte-identical exports are not claimed. One prefixed-note case and a live Auto run are not a universal prompt-injection defense.

Current result: 19/19 cases; field precision 207/207; field recall 207/209; grounded references 98/98; false clean 0/11; review rate 6/17 analyzed PDF cases. Rejected inputs are excluded from the review-rate denominator. See app/benchmark.py for metric definitions and the CI gate.

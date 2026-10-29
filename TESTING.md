# Verification record - October 28, 2026

## Verified

- `python -m pytest -q --junitxml=work/test-results.xml`: 51 passed. One upstream Starlette/httpx deprecation warning, no failures.
- `python scripts/smoke.py`: all four fixture cases passed against the running HTTP server.
- Browser: uploaded the contradiction pair, observed exactly one $25 interest discrepancy, clicked the B source, verified the correct original PDF page and highlighted source line.
- Source PDF serving, rendered PNG pages, invalid page/document IDs, retrieval, JSON and Markdown exports, and deletion are exercised in integration tests.
- Calculator tests cover exact decimal addition, negatives, parentheses and invalid/nonfinite values.
- Guard tests cover reporting-period mismatch, missing and duplicate tranches, unknown input and upload limits.
- Meta contract tests cover grounded extraction, malformed output, ungrounded amounts/citations, real tool dispatch through mocked responses, bounded loops, HTTP 401/429/500 and partial failure handling.

## Four-case acceptance results in local mode

| Case | Observed |
| --- | --- |
| Clean | No findings; both calculated totals 3300.00. |
| Contradiction | Exactly one confirmed interest mismatch, 25.00, with both source lines. |
| Math error | Exactly one confirmed stated-total error, 50.00 too high; computed total 3300.00. |
| Messy | Review/OCR required; image-only document yields no invented fields or confirmed contradiction. |

## Live Meta verification

`python scripts/live_meta_test.py` passed all four cases on October 28 using Muse Spark 1.3 with the local Meta key. The acceptance gate verified successful model extraction, no provider or agent errors, expected confirmed-finding counts, the $25 interest difference with two sources, the $50 total error, review status for the messy case, and nonempty actual agent tool traces. Only synthetic PDFs were sent. Test-created live cases were deleted afterwards.

The server was restarted with the local key loaded. `/api/health` returned status `ok`, `meta_configured: true`, and model `muse-spark-1.3`. Final regression: 51 tests passed; all four HTTP smoke/sanity cases passed. GitHub Actions also passed the committed code's dependency checks, tests and HTTP smoke/sanity checks.

## Scope and limits

The extraction schema covers explicit tranche principal/interest totals and bank opening/closing balances with signed transactions. Bank tests use independent in-memory PDFs; the four-case live benchmark covers loan statements. Added checks cover duplicate transactions, partial rows, omitted labeled rows and swapped principal/interest. It is not a universal statement-layout or amortization checker. Broad real-world layout accuracy, hosted deployment and demo-video production remain outside this verification record. The project is published at https://github.com/KonetiBalaji/paper_trail_agent. The local API key remains ignored and was not committed.


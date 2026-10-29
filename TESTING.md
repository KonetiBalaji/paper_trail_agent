# Verification record - October 27, 2026

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

## Not verified / remaining gate

`python scripts/live_meta_test.py` reported NOT RUN because MODEL_API_KEY is absent. Enter the Meta key in `.env` locally. Restart the server, run the live script and resolve any provider/model issues before calling the full Meta integration complete. This script sends only the supplied synthetic data; it must demonstrate successful model extraction and actual tool activity across all four cases.

The extraction schema covers explicit tranche principal/interest totals and bank opening/closing balances with signed transactions. Bank tests use independent in-memory PDFs. Added checks cover duplicate transactions, partial rows, omitted labeled rows and swapped principal/interest. It is not a universal statement-layout or amortization checker. Broad real-world layout accuracy, public deployment, remote GitHub publication and demo-video production have not been verified or performed.


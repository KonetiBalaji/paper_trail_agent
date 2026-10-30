# Authenticated OCR review workflow

This optional CPU worker is connected to the authenticated case API and UI.
A reviewer uploads a case, requests OCR, refreshes job status, and opens the
new report version when complete. Anonymous synthetic guests cannot request
OCR; viewers can inspect status/results but cannot queue work. Local file mode
continues to request manual review. There is **no persistent hosted OCR worker
configured**; do not claim hosted OCR availability when its heartbeat is absent.

Install separately from the Vercel function:

```powershell
python -m venv .venv-ocr
.venv-ocr/Scripts/python.exe -m pip install -r requirements-ocr.txt
.venv-ocr/Scripts/python.exe scripts/evaluate_ocr.py --report work/ocr-results.json
.venv-ocr/Scripts/python.exe -m app.worker
```

Linux: replace `.venv-ocr/Scripts/python.exe` with `.venv-ocr/bin/python`.
Core tests do not require OCR dependencies. The dedicated Actions OCR job
installs the optional pins and runs the actual engine; it does not mock OCR.

Configure `PAPER_TRAIL_MODE=service`, `DATABASE_URL` and `DATA_ENCRYPTION_KEY` for
the worker using the same private settings as the web service. Never rotate the
encryption key without migrating existing data. A running worker advertises
its capabilities every 30 seconds with a 90-second lease. The API returns 503
and the UI disables requests when no OCR-capable worker is available. Core-only
workers claim eval jobs without consuming OCR jobs. This heartbeat is operational
readiness metadata, not proof of long-term uptime. A worker crash leaves a job
recoverable after its 120-second lease expires.

## API and version semantics

- `GET /api/platform/cases/{id}/ocr` returns scoped version/job status and worker
  availability. Job discovery covers the newest 100 workspace OCR jobs.
- `POST /api/platform/cases/{id}/ocr` requires reviewer/admin, CSRF and
  `{"expected_version": N}`. Limit: ten requests per workspace/hour; active jobs
  for the case are reused. The whole case may contain at most five image-only
  pages awaiting OCR. Jobs remain encrypted in the durable database.
- The worker reads immutable hash-checked PDFs, runs bounded offline OCR, and
  commits the derived report, version, audit entry and job completion in one
  transaction. Missing/changed cases or lost leases cannot be overwritten.
- Every new finding starts pending. Previous decisions, traces and model output
  remain in the prior immutable report version; they are not reassigned to new
  finding IDs. The UI links to the prior version's JSON export.
- Review requests carry both the finding revision and `expected_case_version`.
  Report-version guards are mandatory for OCR-derived findings. A stale client
  gets 409 instead of approving a different finding with a reused ID.
- The derived report uses `mode=ocr`, records the previous mode/version and makes
  zero model calls. JSON/Markdown exports label candidate arithmetic and OCR
  evidence explicitly. Human approval does not turn unverified OCR fields into
  verified data or change the machine review status.

## Frontend integration evidence

`scripts/test_frontend.py` starts an owned disposable HTTP service and real OCR
worker, executes the actual HTML/JavaScript handlers in an isolated jsdom DOM,
and tests sign-in/upload, queue/status, version opening, confidence/calculator
labels, source selection/PNG, guarded review, export, audit, logout and worker
offline behavior. It does not control a user browser or execute web-supplied
scripts. No production data or provider key is used.

```powershell
npm ci --prefix tests/frontend --ignore-scripts --no-audit --no-fund
.venv-ocr/Scripts/python.exe scripts/test_frontend.py --report work/frontend-ocr-results.json
```

Node 26 is required. `docs/frontend-ocr-results.json` contains actual run metadata
and source hashes. The OCR Actions job runs this test and publishes its own
artifact. This proves the tested DOM/HTTP behavior; **browser visual, mobile and
hosted-worker verification remain pending**. The native Chrome verification
attempt was stopped by Computer Use because it could not verify the current URL.

## Trust contract

- RapidOCR ONNX Runtime 1.4.4 uses the model files bundled in its package.
  No cloud OCR or Meta request is made by this component. ONNX telemetry is
  disabled. This is a pinned legacy engine, not a claim of current best OCR.
- Original PDF bytes remain unchanged. Derived source IDs include page and
  OCR line, with bounding boxes mapped to the original PDF coordinates.
- Line score is the minimum score of its grouped cells. Scores are
  **uncalibrated** recognizer scores, not financial accuracy probabilities.
  Amount candidates inherit their cited line's score and remain unverified.
- Lines below 0.95 are retained for inspection but excluded from parsing,
  retrieval and model extraction/grounding. Any such line prevents candidate
  arithmetic for that document. Empty or blurry scans request review.
- Even high-score OCR always requires human review and cannot produce a
  machine-confirmed finding or a clean result. Cross-document comparison stays
  blocked. A human confirming a finding does not validate its OCR fields.
- Candidate arithmetic uses Decimal over recognized rows and totals. It is
  explicitly conditional on recognition being correct. A missing date stays
  missing; a within-document candidate sum does not establish account identity.
- Limits: 10 MB PDF, at most five distinct image-only pages per invocation,
  50 source pages, four million rendered pixels per page, 2,000 OCR boxes per
  page, 2,000 characters per box and 100,000 combined native/OCR characters per
  document. The case shares a 90-second OCR deadline; the owned child enforces
  its remaining time budget.
  This bounds work and bitmap size; it is not an OS memory sandbox.

Python logging in the worker and spawned OCR child installs the same supported
pattern/secret redactor as the web app. Native library diagnostics and external
infrastructure logging are not claimed to have universal PII filtering.

## Evaluation and known failures

`data/ocr` contains four image-only fictional PDFs, a hash manifest and a
reproducible generator. The generator rasterizes an existing varied-layout
statement, a labeled statement, a severely degraded version and a blank page.
All were rendered and visually inspected. No private financial data is used.

The labeled case recognizes 1000.00 principal, 100.00 interest and a stated
1150.00 total. Candidate Decimal arithmetic reports a 50.00 difference, always
as review. In the recorded run OCR read `As of` as `As 0f` despite a score above
0.95. The date remains unknown and the incomplete-extraction finding remains.

The table scan merges metadata words and has a low-score header. It requests
review without calculating. The degraded and blank scans recognize no usable
text and do not calculate. These failures are retained in the evaluation.
This small English corpus does not prove real-world scan accuracy, calibrated
confidence, handwriting, multilingual support or general table recognition.

`docs/ocr-results.json` records actual Windows engine output, source/model
hashes, confidence, candidates, checks and timings. Actions publishes its own
Linux evaluation artifact. Unit tests separately exercise low-confidence
exclusion, geometry, missing identity, native-page preservation, limits,
fixture reproducibility and timeout cleanup.

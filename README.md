# Paper Trail Agent

Submission materials: [draft](docs/SUBMISSION.md), [three-minute demo shot list](docs/DEMO-SHOT-LIST.md), and [hosting preparation](docs/DEPLOYMENT.md).

Build for Your World: a solo FastAPI web app that reconciles PDF loan/bank statements using evidence-linked extraction, exact calculator tools, and Muse Spark reasoning.

The UI now includes **Offline Evals**, an ordered **Trace timeline**, and persisted **Human Review** with Approve, Reject and Save note controls. These are connected to the backend APIs, not static demonstrations.

## Run on Windows

```powershell
cd 'C:\Users\balaj\Downloads\Paper Trail Agent'
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
# Only if .env does not exist:
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765. Local mode runs without API credentials. Upload both PDFs from one `data/synthetic` case.

## Meta API setup (required for full hackathon flow)

Create a key in the Meta Model API dashboard at https://dev.meta.ai, then edit `.env` locally:

```dotenv
MODEL_API_KEY=your_meta_key_here
META_MODEL=muse-spark-1.3
```

Restart the server and select Muse Spark mode. The key remains on the server; it is never sent to the browser. Extracted text and evidence are sent to Meta only when Muse Spark mode is selected. No OpenAI API key is needed. Check Meta credits, billing and model access before live testing. API errors do not produce a clean result.

## Service foundation (deployment verification pending)

Set `PAPER_TRAIL_MODE=service`, `DATABASE_URL`, and `DATA_ENCRYPTION_KEY` in server secret settings. Vercel requires PostgreSQL with TLS enabled; use Neon's pooled connection string. The encryption key must be a valid Fernet key and must be backed up separately from the database. Losing it makes encrypted documents and reports unrecoverable. Missing configuration fails closed. Never commit these values or paste them into chat.

Service mode stores encrypted PDFs, reports and user identifiers in the database, isolates workspaces, uses opaque sessions and CSRF protection, and enforces admin/reviewer/viewer permissions. Provision accounts interactively with `python scripts/manage_users.py --email EMAIL --workspace WORKSPACE --role admin`; passwords are entered through a hidden prompt. There is no public registration. Local mode retains the original file storage behavior.

Case history supports loan/period text search, status and human-decision filters. The evidence viewer offers side-by-side pages. Service reviews preserve report versions, actor identity and a verifiable audit chain. Versioned JSON/Markdown exports are available through the case API's `version` parameter. Upload limits and shared database rate counters apply in service mode.

Durable eval jobs can be queued through `POST /api/platform/jobs/eval`; run `python -m app.worker --once` to process one job, or omit `--once` to poll continuously on a separate worker host. OCR and ingestion job handlers are not implemented yet. SQLite backup restoration is tested; hosted PostgreSQL backups and recovery still require provider verification. A Vercel function is not a continuously running worker.

Current local validation: 125 tests and 6/6 offline evaluation cases pass. These checks use SQLite for the repository and HTTPS TestClient sessions for service behavior; they do not prove PostgreSQL production behavior. Neon free database creation is confirmed, but project connection, secrets, hosted smoke tests and uptime checks remain pending. Do not expose real documents until deployment and privacy controls are verified.

### Public synthetic demo

Service mode offers four fixed fixture buttons after **Start private demo session**: clean, $25 interest contradiction, $50 total error and image-only review. Each visitor gets a separate one-hour workspace. Sources, side-by-side viewing, trace, human review and exports use the same backend as private cases. Guests cannot upload PDFs, call Meta, queue jobs or manage accounts. This demo makes zero model calls; it does not prove live Meta behavior. Shared rate limits and revocable secure sessions are tested. Demo cleanup runs opportunistically on new sessions for guest data older than 24 hours; do not enter personal information in review notes.

## How it works

1. pdfplumber extracts text lines and page bounding boxes; image-only pages become review items.
2. Local mode parses conservative labeled loan-tranche and bank-transaction formats. Meta mode uses Muse Spark for structured extraction, validating extracted amounts and citations against source text.
3. Python Decimal recomputes explicit principal-plus-interest totals. Bank statements also verify opening balance plus signed transactions against closing balance. Matching loan/account IDs, currencies and reporting periods gate cross-document comparisons.
4. The Meta agent can search original evidence (keyword RAG) and invoke a calculator. The tool loop is bounded; final citations must have been retrieved.
5. Findings link to the original PDF page and extracted source line. JSON and Markdown checklist exports retain the evidence. Cases can be deleted locally.

### Current supported scope

The local parser supports explicit `Loan:` or `Account:`, `Currency:`, ISO period-end dates, `Tranche ... | Principal: ... | Interest: ...`, and explicitly labeled principal-plus-interest totals. Bank support includes `Opening balance:`, `Closing balance:`, and `Transaction ID | YYYY-MM-DD | Amount: signed-value`. Meta extraction supports alternative wording only when amounts and identifiers can be grounded in extracted text. This is not a general accounting engine: it does not infer amortization schedules, day-count conventions, unlabeled debit/credit table conventions, or exchange rates. No OCR is included; scanned pages request review. Multi-line tables whose fields cannot be grounded on one source line require review. Missing fields and mismatched periods are not confirmed financial contradictions.

An empty discrepancy list means only that supported checks found none; it is not a guarantee that a statement is correct. The default mode is local single-user use on loopback; PDFs and reports remain in ignored `storage/` until deleted. Service mode adds encrypted database storage and authenticated workspaces, but hosted security, redaction and operational verification remain pending. Use synthetic data in the public repo and demo.

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\smoke.py
# After configuring the key; makes paid Meta API requests with synthetic PDFs:
.venv\Scripts\python.exe scripts\live_meta_test.py
```

Unit tests cover calculator precision, invalid input, PDF extraction, citation coordinates and comparison guards. Integration tests exercise upload -> report -> source PDF -> retrieval -> exports -> deletion across all four ground-truth cases. Provider contract tests simulate extraction failures, tool calls, bad citations, rate limits and invalid credentials. Smoke tests exercise the running HTTP server. Live Meta testing is a separate gate; mocked tests do not prove provider access or model behavior.

Product tests also exercise eval failures and forged citations, review persistence and exports, concurrent/stale revisions, invalid notes, legacy reports, exact trace inputs/outputs and validation failures. HTTP smoke now checks Evals, case traces and saved review notes in addition to the four loan cases. Frontend JavaScript can be syntax-checked with `node --check app/static/app.js`.

See `data/synthetic/README.md` for expected outcomes. Regenerate fixtures using `scripts/generate_fixtures.py` after additionally installing PyMuPDF. The evaluation cases are simple, single-page synthetic statements, not a broad benchmark of real-world PDFs.

## Submission checklist

- Public GitHub repository with no keys or private statements.
- Accessible working app and synthetic demo set.
- Three-minute video showing features built during this event.
- Project description, Meta usage and rationale, feedback, and all contributors listed.
- Submit by November 4, 2026 at 9 PM Eastern / 8 PM Chicago.


## Comparison trust rules and offline evaluation

Cross-document comparisons never disappear silently. Different accounts or currencies produce identity_mismatch review; missing account, currency or reporting-period identity produces identity_incomplete review. A document with extraction/OCR issues blocks comparison with comparison_skipped review. These review findings do not assert financial contradictions.

The image-only messy case reports ocr_required plus comparison_skipped, with zero confirmed findings. Its period and missing tranche cannot be inferred from ground truth.

Two additional bank cases cover a clean closing balance and a 25.00 error. Generate their PDFs with python scripts/generate_bank_fixtures.py; tests generate them in temporary setup. Run python scripts/evaluate.py for all six offline cases and confirmed-source resolution checks. The bank generator uses reportlab only; no Meta key is required.

## Evals, Trace and Human Review

### Offline Evals

Click **Run offline evals** to execute the same evaluator as `python scripts/evaluate.py`. The table shows six cases, pass/fail, actual and expected confirmed counts, source resolution and the $25/$50 differences. The endpoint makes zero model calls and needs no API key.

- Citation accuracy is resolved confirmed-source references divided by all confirmed-source references. Cases without confirmed citations show N/A, not a fabricated 100%.
- False clean rate counts at-risk cases incorrectly marked consistent, divided by four at-risk cases: contradiction, math_error, bank_error and messy. A review result is not a clean result. Clean controls are excluded from this denominator.
- Missing fixtures, wrong amounts, unexpected findings and unresolved sources fail evaluation. Failures appear in the API/UI rather than being hidden as green results.
- This measures the labeled synthetic benchmark and local deterministic checks. It does not measure live-model extraction accuracy, general precision/recall, or universal PDF accuracy.

### Trace timeline

Each new report includes a persisted `trace` array. Events have stable sequential IDs, UTC timestamps, kind/name, inputs, outputs, validation result and elapsed milliseconds where measured. Untimed events store null and display "not timed". Expand an event to inspect its inputs and outputs. Relevant deterministic checks and review events appear under each finding. The model/tool investigation is available under each finding and in the case timeline, explicitly labeled as shared rather than falsely attributed to one finding.

Events cover PDF extraction, local/model extraction, grounded-schema validation, deterministic totals, model calls, search_evidence/calculator tool calls, citation validation, budget failures and human review. Model events expose request metadata, not full prompts, credentials or hidden reasoning. Tool events contain exact arguments and results, which can include document text; they stay in local case storage and JSON exports. Cost is unknown and displayed as unmeasured, not estimated.

The investigation harness allows six model turns and **eight tool calls total across the run**, with a 60-second timeout per provider request. Invalid arguments and failed validation are recorded. Provider failures produce review rather than a clean result. There are no automatic provider retries. Local mode has extraction/calculator/validation events and makes no model calls. Older reports explicitly show that no trace was recorded; historical events are not invented.

### Human Review

Each finding has an independent `human_review` object with decision, revision and append-only event history. Approve records `confirmed`, Reject records `rejected`, and Save note preserves the decision. Notes are limited to 2,000 characters; an empty note is rejected. The original machine severity, message, amounts, citations, case status and calculator results remain unchanged. Human approval of an OCR review item is not proof of successful extraction.

The page URL includes `#case=<id>` after analysis. Reload or bookmark that URL to reopen the saved case and history. JSON and Markdown exports retain review decisions, notes and timestamps. JavaScript renders notes as text rather than executable HTML.

Updates require `expected_revision`; stale edits return HTTP 409 and instruct the user to reopen before retrying. Report writes are atomic, and a process-local lock prevents conflicting updates in the supported single-process local deployment. There is no authenticated reviewer identity, multi-user authorization or cross-process database lock. Use one worker and retain the local single-user scope.

| Endpoint | Purpose |
| --- | --- |
| GET /api/evals | Run and return six offline eval cases plus metric definitions |
| GET /api/cases/{id} | Reopen a report, trace and human-review history |
| PATCH /api/cases/{id}/findings/{finding_id} | Save action, note and expected_revision; returns the updated report |
| GET /api/cases/{id}/export?format=json | Export the complete report, trace and review history |
| GET /api/cases/{id}/export?format=md | Export machine findings and human-review checklist/history |

Example review payload: `{"action":"note","note":"Request a clearer statement","expected_revision":0}`. Supported actions are confirm, reject and note. A2A and MCP are not part of this implementation.

# Paper Trail Agent

Build for Your World: a solo FastAPI web app that reconciles PDF loan/bank statements using evidence-linked extraction, exact calculator tools, and Muse Spark reasoning.

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

## How it works

1. pdfplumber extracts text lines and page bounding boxes; image-only pages become review items.
2. Local mode parses conservative labeled loan-tranche and bank-transaction formats. Meta mode uses Muse Spark for structured extraction, validating extracted amounts and citations against source text.
3. Python Decimal recomputes explicit principal-plus-interest totals. Bank statements also verify opening balance plus signed transactions against closing balance. Matching loan/account IDs, currencies and reporting periods gate cross-document comparisons.
4. The Meta agent can search original evidence (keyword RAG) and invoke a calculator. The tool loop is bounded; final citations must have been retrieved.
5. Findings link to the original PDF page and extracted source line. JSON and Markdown checklist exports retain the evidence. Cases can be deleted locally.

### Current supported scope

The local parser supports explicit `Loan:` or `Account:`, `Currency:`, ISO period-end dates, `Tranche ... | Principal: ... | Interest: ...`, and explicitly labeled principal-plus-interest totals. Bank support includes `Opening balance:`, `Closing balance:`, and `Transaction ID | YYYY-MM-DD | Amount: signed-value`. Meta extraction supports alternative wording only when amounts and identifiers can be grounded in extracted text. This is not a general accounting engine: it does not infer amortization schedules, day-count conventions, unlabeled debit/credit table conventions, or exchange rates. No OCR is included; scanned pages request review. Multi-line tables whose fields cannot be grounded on one source line require review. Missing fields and mismatched periods are not confirmed financial contradictions.

An empty discrepancy list means only that supported checks found none; it is not a guarantee that a statement is correct. The app is for local single-user use and binds to loopback. Add authentication, retention controls and deployment security before exposing it publicly. Uploaded PDFs and reports are stored in ignored `storage/` until explicitly deleted. Use synthetic data in the public repo and demo.

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\smoke.py
# After configuring the key; makes paid Meta API requests with synthetic PDFs:
.venv\Scripts\python.exe scripts\live_meta_test.py
```

Unit tests cover calculator precision, invalid input, PDF extraction, citation coordinates and comparison guards. Integration tests exercise upload -> report -> source PDF -> retrieval -> exports -> deletion across all four ground-truth cases. Provider contract tests simulate extraction failures, tool calls, bad citations, rate limits and invalid credentials. Smoke tests exercise the running HTTP server. Live Meta testing is a separate gate; mocked tests do not prove provider access or model behavior.

See `data/synthetic/README.md` for expected outcomes. Regenerate fixtures using `scripts/generate_fixtures.py` after additionally installing PyMuPDF. The evaluation cases are simple, single-page synthetic statements, not a broad benchmark of real-world PDFs.

## Submission checklist

- Public GitHub repository with no keys or private statements.
- Accessible working app and synthetic demo set.
- Three-minute video showing features built during this event.
- Project description, Meta usage and rationale, feedback, and all contributors listed.
- Submit by November 4, 2026 at 9 PM Eastern / 8 PM Chicago.


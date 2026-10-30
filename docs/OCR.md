# Offline OCR worker component

This is an optional CPU component, with a real four-case OCR evaluation. The
web upload path and leased job worker do **not yet invoke it**. Do not claim
that the deployed application currently performs OCR. Integration with the
authenticated job API, report versions and the UI is the next step.

Install separately from the Vercel function:

```powershell
python -m venv .venv-ocr
.venv-ocr/Scripts/python.exe -m pip install -r requirements-ocr.txt
.venv-ocr/Scripts/python.exe scripts/evaluate_ocr.py --report work/ocr-results.json
```

Linux: replace `.venv-ocr/Scripts/python.exe` with `.venv-ocr/bin/python`.
Core tests do not require OCR dependencies. The dedicated Actions OCR job
installs the optional pins and runs the actual engine; it does not mock OCR.

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
  page and 2,000 characters per box. The owned child has a 90-second timeout.
  This bounds work and bitmap size; it is not an OS memory sandbox.

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

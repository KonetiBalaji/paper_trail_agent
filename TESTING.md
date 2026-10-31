# Verification record - October 28, 2026

## Retention and data-use notice - October 30, 2026

- Repository tests verify disabled-by-default behavior, age preview, a strict UTC
  cutoff, original/all-version deletion, unchanged neighboring workspaces, minimal
  audit preservation, stale-policy refusal, batch size and workspace rotation.
  An in-flight OCR result cannot restore an expired/deleted case.
- API tests cover administrator identity, CSRF, typed enable acknowledgement,
  stale cleanup revision and viewer denial. The data-use notice is public and
  states deletion/redaction/backup limits without claiming regulatory compliance.
- The real DOM-to-HTTP harness opens an owned old fictional case, enforces the
  acknowledgement, enables retention, requests cleanup, verifies original-PDF
  and old-version 404s, clears the case preview and disables the policy again.
  OCR, draft and integration workflows continue to pass in the same harness.
- A periodic-worker test checks startup/five-minute maintenance and shutdown.
  Dedicated PostgreSQL CI races a review with cleanup and requires deletion to
  remain final after a retry of any skipped locked case, with the audit verified.
- No production retention policy is enabled by this patch. Hosted worker/cron
  scheduling, provider backup expiration/restoration and infrastructure logging
  remain outside this verification. Logical deletion is not forensic erasure.

## CSV and scoped integration keys - October 30, 2026

- Local core suite: 245 passed, six skipped (five dedicated PostgreSQL cases and
  optional actual-OCR test). Five integration tests exercise scoped submit/read,
  cookie/Bearer separation, denial of paid mode, workspace boundaries, CSRF/admin
  controls, once-only raw keys, stored digest/encrypted labels, expiry/revocation,
  disabled owner and shared quota denial. CSV tests verify exact $50 totals,
  signed bank transactions, redaction and formula-safe text cells.
- Actual DOM handlers and loopback HTTP verify admin key issue/revoke, masked
  one-time selection, Bearer PDF submission, redacted reads, CSV content and
  logout clearing. Existing OCR online/offline and lender-draft flows pass.
  This does not prove mobile layout or a rendered browser walkthrough.
- The PostgreSQL CI test issues twelve keys concurrently, requires exactly ten
  successes, checks a second repository sees revocation, and verifies the audit
  chain. It requires the dedicated disposable CI database; no production keys
  or accounts are used by that test.
- The accounting worksheet is a neutral signed-transaction export; all rows
  require review. No ledger/tax classification, FX conversion, external vendor
  connection, automatic posting, sending or payment action is implemented.
- PostgreSQL CI passed the concurrent ten-key cap, shared revocation and audit
  check in run 41158888422. The hosted smoke passed 23 checks including CSV
  exactness, no invented loan transactions, guest key-administration denial and
  cookie-only API denial. Evidence is in `docs/hosted-integrations-results.json`.
  This does not prove a production administrator's key setup or an external
  accounting vendor integration; those have not been exercised on the host.

## Reviewed lender and dispute drafts - October 30, 2026

- Twelve focused tests cover exact $25/$50 evidence, deterministic fingerprints,
  unchanged originals, stale versions/revisions, pending/rejected reviews, OCR,
  missing citations, forged amounts/calculations, excluded review-note instructions
  and the two supported draft purposes.
- Local API checks cover saved approval, stale review rejection, workspace
  isolation, unauthorized requests and read-only viewer access to approved drafts.
- The actual DOM-to-HTTP harness prepares both purposes after approval, verifies
  the $50 calculator text, selects all text, clears it on a purpose switch and
  removes it after rejection. OCR online/offline flows continue to pass. This is
  jsdom behavior with real HTTP, not a visual browser or mobile-layout proof.
- `scripts/hosted_draft_smoke.py` passed 18 checks against the authorized Vercel
  origin: served frontend match, both draft purposes, $50 computed/stated totals,
  both $25 interest sources, pattern redaction, cache policy and pending/rejected/
  stale guards. Evidence: `docs/hosted-draft-results.json`. Two disposable
  synthetic cases were deleted and the guest signed out. No paid model calls,
  real uploads, messages or payment actions were performed.
- Draft preparation is read-only and is not a sent-message record. JSON binds
  the text/evidence to the report and review revisions with a reproducible hash;
  final review and manual delivery remain the user's responsibility.

## Worker image and shutdown gate - October 30, 2026

The worker packaging patch passes the local core suite: 226 passed, five skipped
(optional OCR and dedicated PostgreSQL coverage run separately). The real
frontend DOM-to-HTTP OCR workflow also passes with the updated worker, including
the offline-worker path. These checks do not prove browser layout or hosting.

Actions additionally builds `Dockerfile.worker` and executes actual OCR with no
network, a read-only root filesystem, a non-root user and resource limits. It
tests SIGTERM during an owned job, report lineage, audit integrity and all four
scan fixtures. See [worker hosting](docs/WORKER-HOSTING.md) for deployment limits;
the proposal is disabled and does not establish hosted worker availability.

The corrected image passed all 17 container checks and four raster fixtures in
[Actions run 41157254054](https://github.com/KonetiBalaji/paper_trail_agent/actions/runs/41157254054).
The run took 22.16 seconds, completed an in-flight OCR job after SIGTERM in 4.31
seconds, and recorded a cgroup memory peak of 859,099,136 bytes (about 819 MiB)
under the 1 GiB limit. This is one CI workload, not a production capacity margin
guarantee. The initial missing-import failure remains visible in run 41157123148.
Machine-readable evidence is in `docs/container-worker-results.json`.

## OCR job and frontend integration - October 29, 2026

The authenticated service API and frontend now queue real OCR jobs, show
heartbeat availability/status and open derived report versions. Local core
verification: 223 passed, five skipped (four PostgreSQL-only tests and one real
OCR test). The optional OCR environment passes all 16 job integration tests,
including the actual engine case. PostgreSQL now has an additional concurrent
OCR-completion/review race test in its disposable CI database job.

`scripts/test_frontend.py` executes actual HTML/JavaScript handlers in jsdom
against a real disposable HTTP service and CPU worker. Both online-worker and
offline-worker flows pass: signed session, upload, queue, status, candidate
confidence/calculator labeling, source selection/PNG, version-guarded review,
prior export, audit and logout. It is not a browser renderer. Browser visual,
mobile and persistent hosted OCR worker checks remain pending; native Chrome
verification was stopped by Computer Use's URL policy. See `docs/OCR.md` and
`docs/frontend-ocr-results.json` for commands, scope and source hashes.

Actions run 40992471231 passed the final OCR integration code: core suite,
four PostgreSQL tests (including the concurrent OCR/review race), actual scan
evaluation, real OCR job and both frontend-to-HTTP flows. The deployed frontend
hash matches commit `6dc0629`; 50 hosted checks pass, including guest OCR denial.
Hosted OCR worker availability is false, so authenticated requests remain gated
until a separate persistent worker is provisioned.

Fresh live evidence for the final source passes clean/contradiction/math-error/
messy with 3/7/4/4 actual tool calls. The initial attempt failed on API
availability/response handling after the clean case; the sanitized failure is
retained in `docs/live-meta-ocr-initial-failure.json`. A small provider probe
succeeded before retrying. This is evidence of tested behavior, not guaranteed
provider availability.

## Optional OCR component - October 29, 2026

Hosted application commit `727f6c7` is verified at
https://paper-trail-agent.vercel.app/. `docs/hosted-smoke-results.json` contains
49 actual hosted checks. The browser independently ran the four cases, saved
and reopened a review note, selected a source line, and ran Evals (6/6) and the
layout benchmark (19/19). Anonymous visitors cannot upload or invoke paid Meta
modes. Authenticated hosted live Meta, hosted report-version replay, provider
backup restoration and uptime remain unverified.

```powershell
.venv-ocr/Scripts/python.exe -m pip install -r requirements-ocr.txt
.venv-ocr/Scripts/python.exe scripts/evaluate_ocr.py --report work/ocr-results.json
```

The OCR Actions job uses actual bundled CPU models over four image-only
fictional fixtures. Core tests separately verify confidence filtering,
geometry, preservation of missing identity, conditional Decimal calculations,
review-only findings and owned-child timeout cleanup. See `docs/OCR.md` for
known recognition failures and pending API/UI/job integration.

Verification for this component: 207 core tests pass; three PostgreSQL tests
skip locally and run in their own CI database job. The six baseline evals,
19-case layout benchmark and four actual OCR cases pass locally. The fresh
`docs/live-meta-results.json` rerun matches current application source hashes:
clean, $25 contradiction, $50 arithmetic error and messy review all pass with
3/7/4/4 actual tool calls, within the eight-call budget. Live layout reports
from `44d6923` remain historical; they have not been rerun for this component.

## Evals + Trace + Human Review patch

- Regression suite: 80 tests passed, including offline eval failure detection, false-clean and citation metrics, review persistence/exports, stale and concurrent edits, legacy reports, malformed model messages, tool validation and total tool budget enforcement.
- Standalone offline evaluator: 6/6 cases passed. GET /api/evals uses the same service, without a key or model calls.
- Expanded HTTP smoke: Evals API, all four loan cases, report traces, saved review notes, reopen, Markdown export and deletion passed.
- JavaScript syntax check: `node --check app/static/app.js` passed.
- Browser: Evals rendered all six cases with 9 resolved source references, false clean 0/4 and zero model calls. A note and approval survived reload; a second finding's rejection persisted separately. Machine findings and review status remained unchanged.
- Browser live math-error case: Muse Spark produced the $50 discrepancy, and the timeline displayed actual search calls, calculator input/output (sum 3300.00), model timings and citation validation. No browser console errors were observed.
- Four-case live acceptance suite re-ran successfully with the eight-total-tool-call investigation budget. Sanitized local results are in ignored work/product-live-meta-results.json; CI remains offline and does not claim a live run.
- Review writes are atomic with a process-local lock and optimistic revisions; this is a local single-user, one-worker implementation, not authenticated multi-user review or a cross-process database.
- A2A, MCP and hosting changes are excluded from this patch.

## Verified

- `python -m pytest -q --junitxml=work/test-results.xml`: 80 passed. One upstream Starlette/httpx deprecation warning, no failures.
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

The server was restarted with the local key loaded. `/api/health` returned status `ok`, `meta_configured: true`, and model `muse-spark-1.3`. Final regression: 80 tests passed; all four HTTP smoke/sanity cases passed. GitHub Actions also passed the committed code's dependency checks, tests and HTTP smoke/sanity checks.

## Scope and limits

The extraction schema covers explicit tranche principal/interest totals and bank opening/closing balances with signed transactions. Bank tests use independent in-memory PDFs; the four-case live benchmark covers loan statements. Added checks cover duplicate transactions, partial rows, omitted labeled rows and swapped principal/interest. It is not a universal statement-layout or amortization checker. Broad real-world layout accuracy, hosted deployment and demo-video production remain outside this verification record. The project is published at https://github.com/KonetiBalaji/paper_trail_agent. The local API key remains ignored and was not committed.


## Service foundation and public demo (current patch)

- Local full suite: 125 passed; six offline cases passed; JavaScript syntax passed.
- Encrypted SQLite repository tests cover workspace isolation, independent-engine concurrent reviews, immutable original hashes, version replay, audit-chain tampering, shared rate counters, leased jobs, and backup restoration.
- HTTPS service integration tests cover session cookies, CSRF, roles, body limits, stale revisions, cross-workspace denial and administrator boundaries.
- Public demo tests exercise all four fixture outcomes, source PNGs, saved review/export, isolated guest sessions, token tampering, logout revocation, quotas, and denial of upload/model/job/admin operations. Cleanup tests prove private cases survive guest-data expiration.
- Browser service run: started an isolated guest session, ran the $50 total-error case, and saved a note through the frontend; the backend returned review revision 1. This browser check used a local SQLite service and is not hosted proof.
- PostgreSQL integration tests are in `tests/test_postgres.py`, with a disposable PostgreSQL 16 GitHub Actions job. Locally these three tests skip when a dedicated `TEST_DATABASE_URL` is absent. GitHub Actions run 40809557128 passed all three against PostgreSQL 16; this proves the tested repository/session behaviors, not hosted backup recovery.
- `docs/live-meta-results.json` records the latest synthetic live run with source/fixture SHA-256 hashes, revision, dirty-worktree indicator, tool names/counts, timings and observed outcomes. It contains no credentials or raw prompts. Match the hashes before applying the record to a different code revision.
- Hosted smoke, provider backup restoration, OCR, broad layout accuracy, PII redaction and uptime remain pending. The older 80-test sections above describe the baseline, not the current service's deployment status.


## Privacy patch verification

- Full local regression: 142 passed, 3 PostgreSQL tests skipped locally; the PostgreSQL CI job runs those tests separately.
- Privacy tests use fictional identity/contact fields in an actual PDF and exercise local and service uploads, source retrieval, saved review, JSON and Markdown exports. Calculations, differences, source IDs and original PDF bytes are preserved.
- Legacy trace views redact supported PII without rewriting immutable database versions. Tests also cover duplicate filenames, redaction idempotence, query/body search, log arguments/exception text, Uvicorn access-log formatting and escaped Markdown evidence.
- Running HTTP service smoke: all four loan cases, six offline evals, redacted exports, review persistence and deletion passed on port 8770. Frontend JavaScript syntax passed.
- Four live Muse Spark cases passed after privacy wiring. `docs/live-meta-results.json` includes source hashes normalized to UTF-8/LF and raw fixture hashes; model/tool outcomes remain grounded with no more than eight tool calls per case.
- Browser verification of this privacy patch and provider log settings remains pending. Pattern recognition does not cover every unlabeled or international identifier; exported scope metadata makes that limit explicit.


## Strict table layouts, extended benchmark and Auto routing

- Full local regression: 188 passed, 3 PostgreSQL tests skipped locally for the dedicated CI database job.
- Extended corpus: 19/19; 207 true-positive fields, zero false positives and two false negatives from expected partial-row abstention. Precision 100%, recall 99.04%, 98/98 grounded amount references, false clean 0/11 and review rate 6/17. The CI command fails on any case failure or false clean.
- Cross-page tests verify both sources of a split principal/interest row and the exact interest page used in a cross-statement finding. Carried-balance checks exclude later transactions. Duplicate rows cannot be dropped by model extraction; swapped columns, forged sources and added rows are rejected.
- Original six-case evals and HTTP smoke continue to pass. Browser verified the extended benchmark panel and the page-2 interest source for the split row. PDF pages were rendered with Poppler and checked for legibility/alignment.
- Four original live Meta cases pass within eight tool calls. Four varied live Auto cases pass with actual Muse Spark investigation, recorded routes and provider-reported tokens. Direct Meta extraction failed a reversed-column case safely; logs preserve that failure rather than treating it as a successful extraction.
- Five controlled Windows resource workloads passed: 50 pages/500 tranches, 999 transactions, 1000-transaction review, 51-page rejection and over-10-MB rejection. Peak process memory and analysis time are in docs/resource-results.json. These test budgets are not runtime isolation for hostile PDFs.
- OCR, generalized layout confidence, unlinked wrapped rows, unrestricted prompt-injection resistance and a representative real-world corpus remain outside this verification.

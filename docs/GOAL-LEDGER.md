# Full roadmap acceptance ledger

Source: user-provided pending list, October 28, 2026. Baseline: main 217fa27.
This ledger preserves the full goal. A code stub, passing narrow fixture or deployment configuration is not proof of a completed item.

| Item | Requirement | Current evidence / remaining gate |
| --- | --- | --- |
| 1 | Reliable hosted, abuse-protected judge demo | In progress: Neon Free created; Vercel config and isolated synthetic demo implemented, hosted checks pending |
| 2 | Three-minute actual-app video | Pending; shot plan exists, no completed video |
| 3 | Final form and project write-up | Draft exists; final review, URLs and submission pending |
| 4 | Sanitized live Meta evidence in repository | Local log exists; publish reproducible evidence for current revision pending |
| 5 | Discord linked role | Optional manual account step; not verified |
| 6 | Realistic varied loan/bank layouts and truth | Pending; six labeled synthetic cases are the baseline |
| 7 | Cross-page benchmark | Pending; PDF reader already supports multiple pages |
| 8 | OCR with confidence and review gates | Pending; existing behavior requests review |
| 9 | Representative prompt-injection evaluation | Pending |
| 10 | PII redaction with tests | Pending |
| 11 | Representative hardening PDFs | Partial unit coverage exists; representative benchmark pending |
| 12 | Broader field/agent benchmark and false-clean CI gate | Six-case baseline exists; broader benchmark pending |
| 13 | Case history, search, filters, side-by-side view | History search/filter and side-by-side UI implemented and checked in local browser; hosted/mobile verification pending |
| 14 | Gated layout-learning promotion | Pending; must require truth and all-case regression |
| 15 | Document/performance bounds | Explicit 8-file, 10 MB, 50-page limits exist; resource benchmark pending |
| 16 | Extractor/Verifier/Critic orchestration | Pending; do not call internal steps A2A |
| 17 | Standard MCP tools | Pending |
| 18 | Actual A2A protocol | Conditional; only claim after external protocol interoperability test |
| 19 | Routing/fallback, tokens, cost and latency | Timing and explicit modes exist; routing/accounting pending |
| 20 | Agent-level evaluation | Pending |
| 21 | Upload/email/portal ingestion and deduplication | Upload baseline exists; adapters, account setup and dedup pending |
| 22 | Continuous comparison and resolution history | Pending |
| 23 | Historical reconciliation rules | Period guard exists; explicit carried-balance/payment rules pending |
| 24 | Authenticated team roles and review | Service sessions, workspace isolation, admin/reviewer/viewer roles and CSRF covered by integration tests; live account setup pending |
| 25 | Database, durable jobs, backup/recovery and uptime | Encrypted SQL repository, leased eval jobs, SQLite backup restore tested; PostgreSQL restore, OCR worker and uptime pending |
| 26 | Immutable originals, actor audit and versioned exports | Immutable original hashes, actor audit chain, report versions and export replay implemented; hosted replay verification pending |
| 27 | Evidence-backed lender/dispute drafts | Pending; never auto-send or perform money actions |
| 28 | Retention, deletion, encryption, privacy/terms | Local delete exists; service controls pending |
| 29 | Public-service security and incident readiness | Local controls exist; service hardening and security verification pending |
| 30 | Accessibility, mobile and readable exports | Responsive baseline; systematic verification pending |
| 31 | International formats/languages and currency policy | Currency mismatch review exists; explicit supported-format tests pending |
| 32 | CSV/accounting exports and scoped API keys/limits | JSON/Markdown baseline; integrations pending |
| 33 | Onboarding, pricing/support/status and reviewer feedback loop | Pending |

## Implementation sequence

1. Durable repository, audit, authenticated roles, shared limits, case discovery and protected synthetic demo.
2. Representative layouts, cross-page rules, OCR, redaction and broader evals.
3. Explicit orchestration, MCP, conditional A2A, routing and agent metrics.
4. Ingestion/history, jobs/recovery, integrations, service controls and accessibility.
5. Verify Vercel deployment; record the actual-app video; prepare the final form for human review.

External account access, storage/auth secrets and consent must be completed through the appropriate secure interfaces. No credentials belong in chat, repository, evidence logs or demo video. Final terms acceptance and communications are separate consequential actions, not implied by third-party page text.

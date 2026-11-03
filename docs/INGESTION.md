# Statement intake and duplicate handling

Authenticated uploads, scoped integration submissions and fixed public demo
fixtures share one bounded intake service. Local file-storage mode does not
provide database-backed intake reuse.

The SHA-256 of each original PDF identifies exact byte duplicates. A repeated
PDF in one request is marked for review before model extraction; it cannot be
used as independent evidence against itself. Distinct PDFs with equal amounts
remain distinct evidence. A valid first copy can still contain a genuine math
error; duplication does not erase that finding.

Within one workspace, an identical input multiset, analysis mode, application
source, dependency set and layout receipt reopens the existing case, including
its latest saved human review or OCR-derived report. Renaming or reordering
files does not cause new analysis. Adding a second copy changes the multiset.
Changed engine evidence causes a fresh analysis and preserves previous reports.
Failed model extraction is stored but is not permanently cached.

Integration submission returns HTTP 201 for a new case and HTTP 200 for reuse,
with `created` indicating which occurred. Its mode and report version describe
the saved report. Interactive responses include an ephemeral `intake_receipt`;
it is not part of immutable report versions. A preflight cache hit makes zero
new model calls. Concurrent requests can both analyze before the atomic database
commit: only one case is retained, and the receipt/audit records model calls
already attempted. This is not an exactly-once provider-call guarantee.

The database indexes source hashes by workspace. Account/currency and period
tags use workspace-scoped HMACs; identity metadata is encrypted. Grouping tags
require explicit native-text identity matching validated extraction. Unknown,
OCR-only or model-inferred identity does not receive a trusted grouping key.
Source references are removed with case deletion, retention or demo expiry.
This is logical identity indexing, not physical blob deduplication.

The public demo adds a fixed duplicate-PDF review case. It still accepts no
uploads and makes no paid model calls. Existing guest quotas remain enforced.

An authenticated connector can post a MIME message as the `message` multipart
field to `POST /api/integrations/v1/email` using a `cases:submit` bearer key.
The endpoint extracts up to eight PDF attachments, uses generic filenames and
runs local analysis. It discards the body, sender, subject and original
attachment names. The message limit is 4 MB, subject to the hosted total
request limit including multipart overhead. HTTP 201 indicates creation and
HTTP 200 indicates reuse of the same PDFs from any supported intake channel.

See [Historical rules](HISTORICAL-RULES.md) for the private monitoring workflow.
For mailbox polling, configure `PTA_IMAP_HOST`, `PTA_IMAP_USER`,
`PTA_IMAP_PASSWORD`, `PTA_IMAP_FOLDER`, `PTA_INTAKE_ORIGIN` and
`PTA_INTAKE_KEY` in the connector's environment. Set the origin to the HTTPS
address of your Paper Trail Agent instance. Use a dedicated statement folder
and a `cases:submit` key. Run `python scripts/poll_statement_mailbox.py --cursor
work/mailbox-cursor.json` from one scheduled process with a persistent private
cursor path. The first run starts at the beginning of that folder.

Each run reads up to ten messages without marking them read. It records progress
after an accepted or deduplicated submission. A failed message stops the batch
at the previous cursor. Review the message in the dedicated folder before
resuming. A UID validity change also stops the connector for operator review.
The cursor contains mailbox configuration identifiers and belongs in private
storage. Live mailbox and hosted email verification remain open.

For a lender or bank with a direct PDF endpoint, configure
`PTA_PORTAL_STATEMENT_URL` and `PTA_PORTAL_TOKEN` for the provider. Set
`PTA_INTAKE_ORIGIN` and `PTA_INTAKE_KEY` separately for Paper Trail Agent.
Run `python scripts/pull_portal_statement.py` from a trusted connector host.
It downloads one PDF per run, caps it at 3.9 MB, rejects redirects, and sends it
to `POST /api/integrations/v1/portal` with a `cases:submit` key. Schedule it
against a provider endpoint that serves the latest statement to import new
versions. Repeated bytes reuse the saved case. The verified flow uses a
simulated provider. Interactive provider authentication and live portal
verification remain open.

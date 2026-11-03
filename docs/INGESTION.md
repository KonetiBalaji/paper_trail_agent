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
Mailbox polling, portal connections and hosted email verification remain open.

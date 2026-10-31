# Data use, retention and deletion

The application serves its public data-use notice and usage terms at
`GET /api/policies` and displays them above the upload panel. The notice covers
what is stored, which modes send evidence to Meta, the limits of redaction,
deletion boundaries, human decisions and the current synthetic-demo scope.
It makes no regulatory-compliance certification or unrestricted real-data
readiness claim. Host logs and backup retention still need verification.

## Workspace retention

Private-workspace retention starts **disabled**. The default preview age is 30
days; no case content is deleted merely because the feature is deployed.
An authenticated workspace administrator can choose 1–365 days, enable the
policy, and type `DELETE_EXPIRED_CASES` to acknowledge deletion. Saving an enabled
policy authorizes subsequent worker maintenance passes to delete eligible
content, including cases already older than the chosen age. Disabling the policy
stops future passes; it does not restore previously deleted content.

Age uses immutable case creation time in UTC, not the statement date, upload
filename or last review time. The cutoff is strict: creation time must be earlier
than `now - days * 86400`. The preview shows the count and cutoff. Policy changes
and manual cleanup use a revision guard so a stale page cannot silently change
or run a newer policy.

The separate worker checks enabled policies at startup and every five minutes
between owned jobs. Each maintenance call considers at most 25 workspaces,
rotating least-recently-visited policies first. Each workspace transaction removes
at most 25 expired cases. An administrator can also request a bounded pass with
**Delete expired case content now**. Retention is not an exact timed deletion
or access-expiry guarantee: a stopped worker, database outage, locked case or
large backlog delays cleanup. There is no persistent hosted worker or retention
cron configured yet. No production workspace policy was enabled for this patch.

APIs, all requiring a workspace admin session (and CSRF for writes):

- `GET /api/platform/retention`: policy, revision and eligible-case count.
- `PUT /api/platform/retention`: `days`, `enabled`, `expected_revision`, and
  `acknowledge_deletion="DELETE_EXPIRED_CASES"` when enabling.
- `POST /api/platform/retention/run`: `expected_revision`; returns the bounded
  pass's deletion count. Disabled policies delete nothing.

Reviewers, viewers, synthetic guests and integration API keys cannot administer
retention. Existing reviewer/admin single-case deletion remains available.
Public guest data has its separate opportunistic 24-hour synthetic cleanup.

## Deletion boundary and concurrency

Deletion removes the original document rows, all report/review versions and
the current case row in one database transaction. A minimal actor/case-ID audit
event records deletion without copying the document, amounts or review notes.
Minimal existing job and audit metadata remains. An in-flight OCR completion
cannot recreate a missing case; it records a failed job instead. Case locks,
policy locks and revision checks protect review/cleanup races. PostgreSQL skips
busy cases for a later bounded pass.

These are logical database deletions, not forensic media erasure. Provider
backups, infrastructure logs, provider-held model records, prior downloads and
copies sent elsewhere are outside the application's case deletion. Restore
procedures must account for previously requested deletions before exposing a
restored database. Provider expiration, restoration and host-log controls remain
open acceptance gates.

## Encryption and redaction scope

Service PDFs, reports, versions and job payload/results use Fernet encryption
under the server's `DATA_ENCRYPTION_KEY`; service API-key labels and user emails
are also encrypted. Sessions and integration credentials are stored as keyed
digests. Vercel service mode requires a PostgreSQL connection configured to
require TLS. The production origin uses HTTPS. This is application-level
protection, not a claim about every provider storage/log setting.

Local file mode stores ordinary PDF/JSON files on the user's machine. Supported
PII patterns are redacted in traces, exports and application logs; original
private evidence views remain unredacted. Unlabeled/international identifiers,
logs emitted before startup and provider/infrastructure telemetry are not
universally covered. Administrators must review those settings before real
document use.

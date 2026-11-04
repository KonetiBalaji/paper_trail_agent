# Incident response procedure

Owner: repository maintainer, Balaji Koneti. This is an operational procedure,
not evidence that a production incident exercise has occurred. There is no
24-hour staffed response or guaranteed recovery time.

## Triage and preserve

1. Open a private incident record with UTC detection time, affected release and
   deployment IDs, reporter, observed boundary, affected workspace/case IDs and
   suspected access window. Use hashes/IDs, not raw PDFs or secrets, in working
   notes. Do not publish a secret-containing trace or scanner output.
2. Classify exposed data, unauthorized writes, credential exposure, paid-call
   abuse and availability separately. Treat plausible active data access or
   credential exposure as urgent. A failed scanner is a release failure until
   investigated; a dependency advisory needs an exploitability/patch assessment.
3. Preserve access-controlled provider logs, deployment IDs, database audit
   chain/head and a provider snapshot before changing evidence. Record who
   accessed each item. Originals and previous report versions are immutable
   application records; do not edit them to hide the incident.

## Contain

1. Restrict or disable the affected Vercel deployment through the owner's
   deployment-protection/firewall controls, or roll back to a verified unaffected
   deployment. First confirm the selected control actually covers production;
   do not assume a preview restriction protects the public domain. Verify an
   unauthenticated request is blocked. Pausing processing is preferable to
   silently presenting incomplete checks as clean.
2. Revoke exposed Meta credentials at the provider, remove/replace the production
   secret and redeploy. Confirm the old key is invalid without publishing it.
   Check provider usage and spending controls. A history rewrite alone does not
   revoke a leaked key.
3. Revoke affected scoped API keys using the existing admin API/UI. Disable
   affected service users using `Security.disable` through an owner-operated
   maintenance session; this also revokes their service sessions. Check the
   repository audit. For broader session compromise, keep access restricted
   until a reviewed, scoped session-revocation change is applied and replay
   tests pass. Never paste database credentials or session tokens into a ticket.
4. If database credentials were exposed, rotate/revoke the Neon role credential
   and replace the production `DATABASE_URL`, then redeploy and verify old access
   is denied. Preserve the original `DATA_ENCRYPTION_KEY` in secure offline
   custody: simply replacing it makes stored reports/PDFs unreadable. Encryption
   key rotation needs a separately reviewed re-encryption migration and restore
   rehearsal. Do not erase keys, originals or provider backups as containment.

These are owner-executed incident actions. This document does not authorize
unattended changes to paid plans, customer notifications or destructive data
operations.

## Fix and validate

Reproduce the boundary failure with fictional data in an isolated service. Add
the failing behavior to regression coverage, fix it, audit dependencies/secrets,
and run the full application/OCR/PostgreSQL/container gates. For parser or agent
changes, refresh grounded evaluations and mark older live evidence historical
until rerun; never edit its hashes to pretend it is current. Verify source
ownership, human-review/version guards, no false clean, no paid guest path,
session/API-key revocation and public response headers.

Restore affected data only from a verified backup into an isolated environment
first. SQLite restore tests do not prove Neon/PostgreSQL recovery. Keep an
incident open if the required provider restore, integrity check or affected
record accounting remains unverified.

## Recover and communicate

Release the reviewed fix, verify the production commit and repeated boundary
failure are resolved, and reopen access deliberately. Monitor provider usage,
errors and audit events for the original access path. Record the recovery time
and residual risk; there is no assumed clean bill from a green scan.

The owner assesses which users/providers require notice and obtains appropriate
legal advice for applicable reporting duties. Draft a factual private notice
with known impact, actions and contact path; obtain owner approval before
sending. Do not send messages automatically. Publish a redacted incident summary
only after disclosure review. Close with root cause, timeline, affected records,
evidence links, credential actions, regression proof and follow-up owners.

## Local incident rehearsal

Run from the repository root with the test dependencies installed.

```sh
python -m pytest tests/test_integrations.py tests/test_repository.py -k 'revocable or disabled_owner or tampering_and_truncation or tail_deletion or encrypted_backup' -q
```

Expect five passing checks in disposable test databases. They verify credential
containment, detection of modified or removed audit entries, and encrypted
SQLite recovery. Record the commit and test result with the drill evidence.
Provider recovery and cloud access review require separate exercises.

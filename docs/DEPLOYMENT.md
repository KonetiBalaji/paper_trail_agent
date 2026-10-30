# Vercel + Neon deployment

Vercel is the selected host. The free Neon database `paper-trail-agent` is now
connected to the matching Vercel project. The connection was explicitly limited
to Production, with Sensitive variables enabled. `DATABASE_URL`,
`DATA_ENCRYPTION_KEY` and `MODEL_API_KEY` are saved as Production secrets;
Preview and Development were excluded. The redeploy action is waiting for
Vercel email reauthentication. Hosted behavior remains unverified.

`vercel.json` selects FastAPI and a 300-second request ceiling. Configuration
and a Ready build alone do not prove the app can access its database safely.

## Secret settings

Connect the Neon database to this app's Vercel project. Set `DATABASE_URL` to the pooled PostgreSQL URL with `sslmode=require` (or certificate verification). Keep the connection string marked Sensitive. Set `DATA_ENCRYPTION_KEY` to a separately generated Fernet key, and retain a secure backup outside the database. Do not rotate it without migrating encrypted rows. Set `PAPER_TRAIL_MODE=service`. For authenticated live Meta analysis, also set `MODEL_API_KEY` and `META_MODEL=muse-spark-1.3`. Secrets never belong in Git, browser-visible JavaScript or demo evidence.

`VERCEL=1` also enables service mode automatically. A missing database/key fails closed. The application does not write user cases to Vercel's temporary filesystem. Account provisioning uses the interactive `scripts/manage_users.py` command with a secure database environment. There is no anonymous account-registration endpoint.

## Public synthetic demo

Start demo issues an isolated one-hour guest session. Only four allowlisted repository fixture sets can be analyzed; requests cannot select paths, upload documents, invoke Meta, queue jobs, or administer users. Each session's reviews and exports use its own encrypted database workspace. Guest sessions are revocable on logout, CSRF-protected and rate-limited with shared counters. Limits: six starts per IP per hour, 60 starts globally per hour, 12 fixture analyses per session per hour, 240 analyses globally per hour. Offline evals are separately limited to 120 runs globally per hour.

The anonymous demo uses deterministic checks, not a live model. The UI says so. Live Meta evidence must be provided separately or through an authenticated reviewer account. Review notes must contain no personal information. Expired guest workspaces older than 24 hours are purged in bounded batches when new demo sessions start; this is opportunistic cleanup, not a guaranteed timed deletion service.

## Deployment checks

1. HTTPS health/config respond, secrets are absent from responses and assets.
2. Unauthenticated upload and private case reads are denied.
3. Start two guest sessions and verify cross-session case isolation.
4. Run clean, $25 contradiction, $50 total error, and scanned-PDF review cases.
5. Open highlighted source pages, save/reopen a review, compare two pages and download exports.
6. Verify rate limits, CSRF, logout revocation and hosted request-size bounds.
7. Run the offline eval panel and authenticated live Meta smoke separately.
8. Confirm PostgreSQL backups by restoring into a separate database before claiming recovery readiness.

The service accepts at most 4,000,000 total request bytes on Vercel, including multipart overhead, despite the local per-PDF limit of 10 MB. The current pipeline also limits eight PDFs, 50 pages per PDF and 100,000 extracted characters per document. Larger uploads require a future object-storage ingestion path.

## Worker and operational limits

The optional OCR component and actual scan evaluation are documented in
`docs/OCR.md`. It is not yet connected to the job worker or web UI; Vercel must
continue to use the lightweight core dependencies. The production encryption
key has an ignored local `.env.production` backup, separate from the local
development environment. Keep it private and recoverable; losing it makes
stored reports unreadable. Neither `.env` nor `.env.*` files are committed or
included in Vercel source uploads.

Run `python -m app.worker` on a separate persistent worker host for durable eval jobs. Vercel request functions do not provide a continuously running worker. OCR/ingestion handlers, hosted uptime monitoring and provider backup restoration remain pending. A Dockerfile is an optional worker packaging draft; container execution has not been verified. Do not claim production readiness for real financial documents before the remaining privacy, redaction, retention and security gates pass.

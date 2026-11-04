# OCR worker hosting preparation

Production OCR is not enabled. `vercel.json` is unchanged. The separate
`vercel.worker.disabled.json` proposal preserves the web configuration and sets
every daemon instance count to zero. Validate it against the published Vercel
schema with `python scripts/validate_worker_config.py` after installing
`tests/requirements-tools.txt`.

`Dockerfile.worker` pins the Python base image digest and installs the locked
optional OCR dependencies. Its Dockerfile-specific ignore file allows only
application code, fictional fixtures, requirements and worker scripts. Local
environment files, storage and private documents are excluded. The worker runs
as UID 10001, clears the Meta key and forces service mode. It requires production
database and encryption configuration at runtime; neither is baked into the image.

The worker handles SIGTERM/SIGINT by finishing the currently owned job, retiring
its readiness heartbeat and exiting without claiming another job. Idle waiting
is interruptible. The proposal allows 120 seconds for termination and polls every
15 seconds. A longer poll interval reduces queries but does not make Neon sleep.

The `worker-image` Actions job builds the actual Linux amd64 image and checks
build-context exclusion using fictional probes. It runs without network, as a
non-root user, with a read-only filesystem, writable temporary storage, one CPU,
1 GiB memory, a PID limit and dropped capabilities. The smoke script sends
SIGTERM during actual OCR, verifies the next job remains queued, checks encrypted
report lineage and audit integrity, and runs all four raster fixtures. Its JSON
artifact records the image ID and source commit. Docker is unavailable on the
current Windows machine; local Python tests do not prove this container passes.
The corrected Linux image passed all 17 checks and four scan cases in
[run 41157254054](https://github.com/KonetiBalaji/paper_trail_agent/actions/runs/41157254054):
22.16 seconds overall, 4.31 seconds to finish the owned OCR job after SIGTERM,
and approximately 819 MiB cgroup peak memory under the 1 GiB limit. See
`container-worker-results.json` for image ID, source commit and model hashes.
This tested workload does not establish capacity for arbitrary PDFs.

## Free-tier availability must be checked before enabling

[Vercel daemon limits](https://vercel.com/docs/daemons/limits) document Hobby
allowances of five active CPU hours and 420 provisioned GB-hours per month.
A continuously provisioned 1 GiB worker would use the memory allowance in about
17.5 days, even when idle. Exhaustion stops Hobby daemons until the monthly reset.
The [configuration reference](https://vercel.com/docs/daemons/config-reference)
documents zero instances as disabled and a 1 GiB memory request.

[Neon's free-plan announcement](https://neon.com/blog/neon-free-plan-1-gb-per-project)
documents 100 CU-hours per project per month. Repeated database polling and
heartbeats keep compute awake. Verify actual account quotas and choose an
activation/idle policy before starting a worker. No paid upgrade or running
daemon is configured by this patch. The monitoring handler is available in the
same worker, and the case timeline displays its heartbeat. Confirm an active
heartbeat and process a fictional carry discrepancy when validating a hosted
worker. PostgreSQL dump and restore was verified separately in disposable CI
run 41613699682. Provider backup recovery and hosted worker availability remain
open.

## Worker image OS scan

CI scans an archive of the built Linux amd64 worker image with a digest-pinned
Trivy container and uploads the JSON report. Findings remain visible at every
severity. The scan reports findings without blocking the build based on severity.

The Bookworm scan found 4 critical and 54 high package findings. The Trixie
candidate found 1 critical and 58 high, and passed the worker smoke test. Neither
scan reported fixed versions for its critical or high findings. The remaining
critical Trixie finding is CVE-2026-6653 in libxml2. Debian lists it as a minor
issue and still marks Trixie vulnerable.
[Bookworm scan](https://github.com/KonetiBalaji/paper_trail_agent/actions/runs/41761879097),
[Trixie scan](https://github.com/KonetiBalaji/paper_trail_agent/actions/runs/41762130819),
[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653).

Vercel Hobby cron invokes a function at most daily per schedule, with
hour-level scheduling precision. It can serve a daily maintenance workload
within function limits, but a daily invocation leaves queued OCR and
reconciliation work waiting and cannot provide a live worker heartbeat. Keep
public uptime probes separate from job execution. A production worker release
needs a host that can sustain the tested memory footprint and the agreed
queue-processing interval. Verify the heartbeat, a queued synthetic job, and
the encrypted report and audit record after deployment.
[Vercel cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing).

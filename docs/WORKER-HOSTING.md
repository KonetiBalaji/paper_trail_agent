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
daemon is configured by this patch. Container tests do not establish production
uptime, hosted OCR availability, PostgreSQL recovery or a browser-rendered demo.

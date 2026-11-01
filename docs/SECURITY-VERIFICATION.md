# Public-service security verification

This is a solo-maintained synthetic hackathon demo, not a certified financial
service. Automated scans and scoped boundary probes do not prove it is secure.
Real-document onboarding, provider/IAM review and an independent penetration
test remain release gates.

## Repeatable gates

`Security gates` runs on pushes, pull requests, manual dispatch and weekly.
It has read-only repository permissions, full-history checkout with credentials
not persisted, pinned action commits and a checksum-verified Gitleaks 8.30.1
binary. No deployment, database or Meta credential is provided to that job.

`scripts/security_checks.py` runs:

- Default Gitleaks rules plus the scoped `pta_api_` credential format over all
  reachable Git history and a temporary copy of tracked working files. Ignored
  local environment files are not copied or published. Inline allow comments
  are ignored. A freshly generated, never-used synthetic key must be detected
  before either scan can count as passing. Public evidence records counts and
  rule IDs only; scanner output and matches are never echoed by the wrapper.
- pip-audit 2.10.1 against every entry in the pinned core and OCR inventories,
  using PyPI advisories, strict collection and no dependency resolution or
  package installation from the audited inventory. Skipped packages and
  operational errors fail the check. Linux and Windows marker differences are
  explicit in the audited count. This audits the lock inventory, not unlisted
  system libraries, OS/container CVEs or the installed hosting image.
- `npm audit` against the frontend test lock, with even low-severity findings
  failing the gate. There is no deployed npm runtime dependency.

An advisory-service outage fails the workflow rather than producing clean
evidence. No vulnerability IDs are ignored. Dependabot proposes weekly Python,
frontend and action updates; there is no auto-merge. A Python update must keep
`requirements.txt` and `requirements-lock.txt` aligned and pass existing
orchestration, MCP, OCR, PostgreSQL and resource gates before deployment.

Example local command, with separately installed security tooling and the
checksum-verified scanner:

```powershell
.venv/Scripts/python.exe scripts/security_checks.py --gitleaks work/security-tools/gitleaks/gitleaks.exe --audit-python work/security-venv/Scripts/python.exe --report work/security-results.json
```

## Application and deployment boundaries

`tests/test_public_security.py` checks all ten case read surfaces across
workspaces, anonymous rejection, opaque-session tampering, CSRF/Origin rejection,
cookie flags, private file routes, local login quotas despite spoofed forwarding
headers, and oversized bodies being rejected before parsing/provider calls.
Other service/integration tests cover role permissions, expiring/revocable API
keys, concurrent quotas, report-version races and cleanup.

The authorized hosted probe is fixed to the production origin:

```powershell
.venv/Scripts/python.exe scripts/hosted_security_smoke.py --report work/hosted-security-results.json
```

It makes a bounded number of HTTP requests with two disposable synthetic guests
and deletes its own created case. It checks private-file exposure, all ten
cross-session read surfaces, CSRF/Origin rejection, revocation/replay, guest
privilege limits, cookie/Bearer separation and actual response headers. It does
not try real passwords, invoke Meta, upload real files or exhaust public quotas.
Do not run it repeatedly against production; use disposable local service tests
for iterative development.

Vercel config supplies `nosniff`, frame denial, same-origin referrer policy and
camera/microphone/location/payment permission denial even for early application
rejections. API responses are `no-store`. The home document has a CSP permitting
only self-hosted scripts, styles, images, fonts and API connections, with object,
base and framing disabled. There is no inline-script or `unsafe-eval` allowance.
The separate disabled worker proposal carries the same web headers and remains
at zero instances. Interactive API docs are outside the home-document CSP;
they are public schema documentation, not privileged authorization.

## Evidence and remaining limitations

Record scan/probe dates, exact commits and input hashes alongside each result.
Initial local audits found zero known advisories in 62 Windows core/OCR pins,
zero npm advisories and zero default-rule history findings. Final CI and hosted
evidence is linked from `TESTING.md`; those dated artifacts are not perpetual
guarantees.

GitHub repository inspection confirmed secret scanning and push protection were
already enabled. Vulnerability alerts and Dependabot security updates were
enabled during this patch. This does not claim every provider's token pattern is
recognized. Do not add broad scanner allowlists to make a failure disappear.

Still unverified: independent penetration testing, browser enforcement/visual
compatibility of the CSP, cloud-role/IAM and forwarded-client-IP normalization,
OS/container vulnerability scanning, DDoS resistance, dependency provenance/
fully hashed tool installs, real-document privacy review and staffed incident
response. Branch protection/required-check policy has not been configured by
this patch. Financial actions and outbound dispute delivery remain manual.

Primary references: [Gitleaks](https://github.com/gitleaks/gitleaks),
[pip-audit](https://github.com/pypa/pip-audit),
[Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference),
[Vercel security headers](https://vercel.com/docs/cdn-security/security-headers).

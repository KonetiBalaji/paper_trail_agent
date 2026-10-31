# Case-scoped MCP tools

Paper Trail Agent uses the official Python MCP SDK, pinned to `mcp==2.3.0` and
`mcp-types==2.3.0`. Muse Spark discovers the tools through an actual stdio
subprocess. Each investigation gets its own case bundle and process. There is
no direct-call fallback: transport or result validation failure makes the case
request review. Deterministic extraction/verifier/critic checks remain separate
from the protocol transport; MCP itself is not an accuracy improvement.

`requirements.txt` is a flat, pinned Vercel deployment manifest matching the
portable entries in `requirements-lock.txt`. Vercel rejected the attempted pip
constraint include; `scripts/check_deployment_requirements.py` prevents manifest
drift and unsupported pip include/options. The Windows-only pywin32 pin stays in
the cross-platform lock; MCP resolves that platform dependency on Windows.

Official references: [client transports](https://py.sdk.modelcontextprotocol.io/client/transports/),
[structured outputs](https://py.sdk.modelcontextprotocol.io/servers/structured-output/),
[running a server](https://py.sdk.modelcontextprotocol.io/run/), and
[SDK tracing](https://py.sdk.modelcontextprotocol.io/run/opentelemetry/).

## Tools and boundaries

| Tool | Input | Structured output | Validation |
| --- | --- | --- | --- |
| `search_evidence` | `query` string | `lines`: at most 8 source records (`id`, `text`, `page`, `line`) | 1–500 query characters, no extra arguments; only usable lines from the loaded case |
| `calculator` | `values`: monetary strings | `sum`: exact decimal string | 1–1000 values, at most 32 characters/value, finite amounts, no sub-cent precision, no extra arguments |

Both tools publish input and output JSON schemas. The client verifies the
discovered catalogue/schema pair and validates structured results. The server
validates arguments and enforces eight attempted tool calls per process;
rejected calls count. Muse Spark keeps its separate six-turn/eight-total-call
budget, including malformed calls that never reach the wire.

The server has no model, database, upload, review, deletion, arbitrary file-read
or HTTP tool. A caller cannot switch the case by passing a path, case ID or URL.
The one evidence file is explicitly chosen when the process starts. This is an
application authority boundary, not an operating-system sandbox: the trusted
process runs with its owner's OS permissions.

## Data and traces

The app gives the child only SDK/platform environment variables and no model or
database credentials. The server never imports the web runtime or loads dotenv.
SDK telemetry is disabled in the child, and the pinned environment installs the
OpenTelemetry API without a collector/exporter. This does not configure host
infrastructure telemetry or every possible caller's tracing setup.

The ephemeral bundle contains pattern-redacted usable source text with source
IDs/page/line numbers. It omits filename metadata, bounding boxes and account metadata
objects. Supported PII patterns are removed before transport and logs. This is
not universal anonymization: inspect unsupported personal details before sharing
a bundle with an external host. A bundle is bounded to 2 MiB and each text line
to 2,000 characters; exceeding the limit requests review, not truncation.

Every server tool attempt logs a redacted input, output, validation result,
sequence and duration. The app retains this log under `agent.mcp` in the encrypted
report, alongside discovered schemas, negotiated protocol and server identity.
Tool trace events identify `mcp_stdio` and the matching server sequence, or
`not_dispatched` for malformed JSON rejected before transport. Temporary files
are removed after the SDK closes its owned process. Standalone servers write
redacted JSONL calls to stderr by default, so a host can capture them. Optional
`--audit-log PATH` creates a new private file and refuses to overwrite an
existing one; use a fresh filename for each standalone run.

## Run from a standard host

Prepare a fictional case, then let a host launch the command below:

```powershell
.venv\Scripts\python.exe scripts\prepare_mcp_case.py --synthetic contradiction --output work\mcp-case.json
.venv\Scripts\python.exe -m app.mcp_server --evidence work\mcp-case.json
```

The second command waits for MCP on stdin/stdout. It does not print a human
prompt or open a port. For a real approved saved report, the preparation script
accepts `--report-json PATH` instead of `--synthetic`; it refuses to overwrite its
output. Inspect the redacted bundle before choosing the host that will see it.
Use absolute interpreter/evidence paths in a desktop host's stdio configuration
and set its working directory to the repository root. No Meta key is needed by
the tool server. The owner-supplied bundle is not a certificate of PDF truth;
the application's extraction and critic gates provide the separate evidence
validation when analyzing a case.

An independent official SDK client can connect with `Client(StdioServerParameters(...))`.
`mode="auto"` negotiates `2026-07-28`; the compatibility test also uses
`mode="legacy"` and negotiates `2025-11-25`. Run the executable interop gate:

```powershell
.venv\Scripts\python.exe scripts\evaluate_mcp.py --report work\mcp-results.json
```

It launches real subprocesses and checks both protocol eras, schema discovery,
exact sums, bad/extra arguments, nonfinite/sub-cent rejection, unknown tools,
case isolation, the ninth-call guard, audit completeness and file release. It
uses fictional evidence and no model, database or paid provider call.

## Public demonstration

An isolated synthetic demo session exposes **Run synthetic MCP check**. Its
backend runs actual discovery, evidence search and calculator calls against a
fixed fictional statement and renders the returned schemas and call log.
It makes zero model calls and accepts no user-selected evidence. The write
requires CSRF and the demo role, with limits of four checks/session/hour and
30 checks globally/hour. It is an application smoke-check endpoint, not a public
MCP HTTP endpoint. Remote HTTP MCP deployment and authorization are not claimed.

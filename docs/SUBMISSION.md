# Paper Trail Agent

Track: Indie Developer. Theme: Build for Your World. Builder: Balaji Koneti (solo).

**Submitted and verified November 3, 2026.** After the builder approved the
exact entry and publication permission, the submission was sent to Cerebral
Valley. The event page changed to **View Submission** and the saved entry was
reopened to verify the project name, repository and approved video link. The
private receipt is retained locally. Submitted implementation: `b752f55`;
verification/evidence release: `0a662f8`.

## Project description

Paper Trail Agent checks financial statement PDFs for contradictions using calculator-verified totals and grounded source citations. It extracts principal, interest, dates and tranche amounts, recomputes totals using Python Decimal, and compares matching accounts, currencies and reporting periods. Each confirmed finding links to the original page and highlighted source line. Users can export an evidence-backed report and actionable checklist.

The demonstration has three outcomes: a $25 interest discrepancy between statements, a stated total that is $50 too high, and an image-only statement that triggers manual review instead of invented values. A clean control produces no findings. The public repository contains only fictional documents and known-answer ground truth.

## Impact and design rationale

The intended user is someone checking their own loan or bank paperwork before
asking a lender to explain a discrepancy. The app turns a suspected wrong total
into a reproducible calculation and a highlighted source, then saves the user's
review decision. It does not move money or send a dispute. Evidence-backed draft
text is available only after a human approves an eligible finding.

The implementation separates extraction, deterministic verification and an
independent critic. Muse Spark uses case-scoped standard MCP retrieval and
calculator tools; strict contracts reject unsupported values and citations.
Uncertain scans request review. Offline evals and an ordered tool trace make the
checks inspectable. Duplicate-aware intake prevents comparing a PDF to itself
and reopens saved decisions instead of silently replacing them.

No time-savings, adoption or real-world accuracy numbers are claimed: the
measured results come from published fictional known-answer fixtures.

## Use of Meta products

Muse Spark 1.3 through Meta Model API extracts structured financial fields from PDF text. The server validates amounts and cited sources against the extracted lines. Muse Spark then investigates verified findings using source retrieval and calculator tools, and produces an explanation and review checklist. Arithmetic and comparison checks execute in Python; the model does not decide the numeric result by itself.

## Why Meta models matter

The model connects document evidence to a structured, tool-driven investigation. It can locate relevant source lines, request deterministic arithmetic, and turn discrepancies into understandable next steps. The application constrains that reasoning with evidence validation, exact calculations, account/period comparison guards and explicit review states.

## Implementation feedback to adapt for the form

These are engineering observations from recorded runs, not a quotation or
personal testimonial from the builder. Structured extraction and tool use make
the reasoning auditable, but application-side validation remains necessary.
The project retains failed live attempts alongside successes; bounded tool
budgets, explicit abstention and regression tests were needed to keep failures
from becoming a clean report. Any field asking for the builder's personal
experience still needs the builder's own wording.

## Evidence

- Public code: https://github.com/KonetiBalaji/paper_trail_agent
- Live synthetic demo: https://paper-trail-agent.vercel.app/ (public guests use deterministic checks; paid Meta calls are blocked).
- Narrated/open-captioned video, 2:08: https://paper-trail-agent.vercel.app/static/demo.html (actual app footage plus a clearly labelled graphic of a separate saved Meta result; owner-approved for hackathon use on November 1, 2026).
- 407 core tests passed in verified CI, including public-player/range and gated layout admission tests. PostgreSQL, OCR/frontend and worker-image checks pass separately. The deployed reviewed fictional Cedar package has a source-bound registry, 41-case full regression receipt and 29 passing hosted checks; this is not a universal real-lender accuracy claim.
- 50 hosted API/security checks passed, including all four outcomes, review persistence, session isolation and guest OCR denial.
- Four fresh live MCP-backed Muse Spark cases pass with 3/4/4/3 tool calls against the duplicate-aware intake Python sources; prior successful evidence and failed attempts remain documented. The video additionally includes an actual local contradiction run with three calls, shown as a labelled saved-result graphic.
- Six demo evals, 19 varied-layout cases and four actual OCR scan cases pass their respective gates.
- GitHub Actions runs core/HTTP/resource checks, PostgreSQL integration, real CPU OCR and the frontend/HTTP workflow. Live Meta tests require a local key and are separate.

## Scope to state honestly

The tested benchmark consists of synthetic documents. Local parsing supports labeled statements and documented strict loan/bank table layouts, including linked cross-page rows and carried balances. The extended fictional benchmark has 19 cases; it is not a real-world accuracy claim. This is not a universal financial PDF parser or an amortization engine. Image-only PDFs request review in the public demo. Authenticated OCR queueing, confidence display and versioned review are connected and tested with a separate CPU worker; no persistent hosted OCR worker is configured yet. OCR candidates remain review-only. The current live Meta benchmark covers the four loan cases. Public hosted guests use local checks; the live Meta evidence is a separate real-model test.

## During judging

- Keep the deployed application URL and public guest flow available through judging.
- The saved submission uses the approved public player URL and lists Balaji
  Koneti as the sole contributor. The partner field accurately states that
  Fireworks, Modal and Baseten were not integrated.
- Keep later roadmap changes separate from the submitted feature claims.

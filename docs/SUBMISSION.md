# Paper Trail Agent

Track: Indie Developer. Theme: Build for Your World. Builder: Balaji Koneti (solo).

## Project description

Paper Trail Agent checks financial statement PDFs for contradictions using calculator-verified totals and grounded source citations. It extracts principal, interest, dates and tranche amounts, recomputes totals using Python Decimal, and compares matching accounts, currencies and reporting periods. Each confirmed finding links to the original page and highlighted source line. Users can export an evidence-backed report and actionable checklist.

The demonstration has three outcomes: a $25 interest discrepancy between statements, a stated total that is $50 too high, and an image-only statement that triggers manual review instead of invented values. A clean control produces no findings. The public repository contains only fictional documents and known-answer ground truth.

## Use of Meta products

Muse Spark 1.3 through Meta Model API extracts structured financial fields from PDF text. The server validates amounts and cited sources against the extracted lines. Muse Spark then investigates verified findings using source retrieval and calculator tools, and produces an explanation and review checklist. Arithmetic and comparison checks execute in Python; the model does not decide the numeric result by itself.

## Why Meta models matter

The model connects document evidence to a structured, tool-driven investigation. It can locate relevant source lines, request deterministic arithmetic, and turn discrepancies into understandable next steps. The application constrains that reasoning with evidence validation, exact calculations, account/period comparison guards and explicit review states.

## Evidence

- Public code: https://github.com/KonetiBalaji/paper_trail_agent
- Live synthetic demo: https://paper-trail-agent.vercel.app/ (public guests use deterministic checks; paid Meta calls are blocked).
- 223 automated tests passed locally; PostgreSQL integration is a separate CI gate.
- 49 hosted API/security checks passed, including all four outcomes, review persistence and session isolation.
- Four live Muse Spark acceptance cases passed on October 29, 2026 with 3/7/4/4 tool calls; see TESTING.md for the precise scope and retained initial API failure.
- Six demo evals, 19 varied-layout cases and four actual OCR scan cases pass their respective gates.
- GitHub Actions runs core/HTTP/resource checks, PostgreSQL integration, real CPU OCR and the frontend/HTTP workflow. Live Meta tests require a local key and are separate.

## Scope to state honestly

The tested benchmark consists of synthetic documents. Local parsing supports labeled statements and documented strict loan/bank table layouts, including linked cross-page rows and carried balances. The extended fictional benchmark has 19 cases; it is not a real-world accuracy claim. This is not a universal financial PDF parser or an amortization engine. Image-only PDFs request review in the public demo. Authenticated OCR queueing, confidence display and versioned review are connected and tested with a separate CPU worker; no persistent hosted OCR worker is configured yet. OCR candidates remain review-only. The current live Meta benchmark covers the four loan cases. Public hosted guests use local checks; the live Meta evidence is a separate real-model test.

## Complete before submitting

- Keep the deployed application URL and public guest flow available through judging.
- Add the accessible three-minute demo video URL after recording and review.
- Confirm track and contributor details in the actual submission form.
- Write personal feedback on Meta products and any partner technologies actually used. Do not invent feedback or claim unused services.
- Review the requested publication permission before submitting the form.

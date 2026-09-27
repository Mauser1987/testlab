# TestLab — Requirements & Architecture Phase

Status: **Reviewed — PO decisions round 1 (`/answers_n1.md`) incorporated.
M1 specified in [11-m1-specification.md](11-m1-specification.md).**
No application code has been written.
Date: 2026-09-26
Source brief: `/Projectprompt.md`; PO decisions: `/answers_n1.md`
Source material: `/reference` (read-only)

### PO decisions round 1 (summary)
- Every Test Run has exactly one TCN number (Run 001 ↔ TCN001), even without deviations.
  A TCN may contain zero or more deviations from the program.
- Seal arrangement ∈ {Single, Dual Pressurized, Dual Unpressurized}; **Plug Seal is
  an optional, separate configuration**, not an arrangement.
- Average leakage rate = total leakage quantity / actual running time (calculated).
  Leakage method, intermediate readings, total, running time and average are distinct data.
- Issued TCN never silently changed; formal change → new TCN revision; execution
  deviations belong to the Result.
- Project default edits never change existing TCNs.
- Future (not M1): component lifecycle tracking, DCS integration, automatic acceptance
  evaluation, elaborate approval workflow.
- Deployment: central internal Django server; **PostgreSQL in production**, SQLite
  only for local development; configurable server-side file storage; Django auth in M1.

## How to read this folder

| File | Covers (brief deliverable / task #) |
|---|---|
| [01-current-workflow.md](01-current-workflow.md) | A — understanding of today's workflow; inventory of the supplied documents (task 1) |
| [02-information-analysis.md](02-information-analysis.md) | B — repetition & automation opportunities; which information lives at which level; inherit vs snapshot; free text (tasks 2, 3, 4, 10) |
| [03-domain-model.md](03-domain-model.md) | C — domain model, reusable entities, entity/relationship schema (tasks 5, 6, 14) |
| [04-architecture.md](04-architecture.md) | D — application architecture & technology stack (task 13) |
| [05-ui-and-workflow.md](05-ui-and-workflow.md) | E — navigation, main screens, end-to-end workflow (tasks 7, 8) |
| [06-document-generation.md](06-document-generation.md) | F — DOCX template generation (task 15) |
| [07-excel-vba-legacy.md](07-excel-vba-legacy.md) | What the existing Excel/VBA TCN generator does and what must be preserved (task 9) |
| [08-edge-cases.md](08-edge-cases.md) | Edge cases, inconsistencies and ambiguities found in the documents (task 11) |
| [09-scope-and-milestones.md](09-scope-and-milestones.md) | G, H, J — MVP/V1 scope, later phases, milestones, recommended next step (task 12) |
| [10-questions-and-assumptions.md](10-questions-and-assumptions.md) | I — risks, unknowns, questions for the domain expert; explicit assumptions (task 16) |
| [11-m1-specification.md](11-m1-specification.md) | **Final M1 implementation specification** (replace Excel/VBA TCN generator) |

## Headline findings (one-page summary)

1. **The same facts are re-typed 4–6 times per project.** Customer, project number,
   seal type, order number, drawings, face part numbers, field conditions and
   test conditions appear in the Test Program, every TCN, every Test Summary and
   the Final Report. Every re-typing point in the samples has at least one
   drift/error (see 08-edge-cases.md).
2. **The documents already disagree with each other.** Example: 2023RSD08TL
   Test 1 inner-seal leakage is reported as 16.1 ml/h, 19.7 ml/h and 16 ml/h
   in three places; the accumulated-leakage plot and manual log suggest IB/OB
   are swapped in the "Measurements Results" table. This is the strongest
   argument for "enter once, calculate, reuse".
3. **The Excel/VBA tool already embodies the right core idea** (one record
   per Project+Run, copy previous run, arrangement-dependent labels, parameter
   checklist that drives the log sheet, leakage-rate calculation). It fails on
   history (overwrite/delete), central storage (workbook copied per project)
   and on the Result/Report side (photos by file path, no link to Word).
4. **"TCN" is used with two meanings**: *Test Program Change Notice*
   (deviation from the program — program §Reporting) and *Run/TCN No.*
   (the instruction for every run — Excel, TCN form).
   **Resolved (PO):** every run has a TCN; it may contain zero or more deviations.
5. **Conditions are not always numbers** ("min 75", "60 - 40", "TBD",
   "Approx. 35-50 °C", "depends on how much heat will be generated").
   The model stores the engineer's text *and* optional numeric values.
6. **A single TCN can contain multiple phases** (Run 004: 100 h @ 60 °C then
   100 h @ 40 °C; qualification program: stepped pressures). Conditions need a
   "step" level beneath the TCN.
7. **Recommended first usable milestone: replace the Excel TCN generator**
   (Project + TCN register + TCN DOCX), not the full vision. It is the tool in
   active daily use (entries dated June–Aug 2026), it is small, and it can be
   verified directly against real TCNs. Results/Summary is milestone 2.
8. **Stack:** Python + Django + docxtpl (Word templates with placeholders),
   server-rendered pages, one centrally hosted application on an internal
   server; PostgreSQL in production, SQLite for development.
   Rationale in 04-architecture.md.

## Nothing has been implemented

Per CLAUDE.md and the brief: this phase produces documents only.
Implementation of M1 starts after the product owner approves
11-m1-specification.md.

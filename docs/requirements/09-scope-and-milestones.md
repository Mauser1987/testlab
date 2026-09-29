# 09 — Scope, Milestones & Next Step (Deliverables G, H, J; task 12)

## 1. Guiding choice

Build in the order that **replaces a real, currently-used tool first**, and
that can be checked against real documents at every step.

The Excel TCN generator was used in June–August 2026 (runs 001–004 of
2026RSD03TL). It is small, well-understood and its output (TCN001.pdf) is a
clear acceptance target. The Test Program is written once per project and
works acceptably in Word for now.

## 2. Milestones

### M1 — Replace the Excel/VBA TCN generator — **specified in 11-m1-specification.md**
- Project (identity + project default run setup)
- TCN create from project defaults / copy from previous TCN; run-number
  rules; arrangement (single / dual pressurized / dual unpressurized) +
  optional plug seal with Excel-derived label switching; seal positions;
  process, barrier/buffer/flush and Plug Seal conditions as text values; monitored parameters;
  instructions text
- Differences vs source highlighted
- Issue/lock; new revision with reason; no hard delete of issued TCNs
- Generate the TCN as a PDF from the Word template (controlled document, 11 §17)
- Test Data Sheet export (XLSX, replaces Excel "Create Test Data Sheet")
- Django authentication; registration with corporate email domain and administrator approval (11 §17); PostgreSQL-ready; backup procedure

Deliberately **not** in M1: legacy Excel import (post-M1, after the
data model is validated on new projects), condition steps (multi-phase stays in text as
today), catalogues for rigs/parameters/materials, field-level change log,
Excel "test results" functions (unused), approvals, corporate SSO.

**Acceptance tests:** 11-m1-specification.md §11.

### M2 — Results & Test Summary — *V1 complete*
- Condition steps (multi-phase runs) introduced here or in M3, whichever
  first needs them for comparison
- Result per TCN: actual dates, actual conditions (execution deviations
  recorded here, not in the TCN), manual log grid with calculated running
  hours / interval rate / cumulative leakage
- Leakage per seal: measurement method, intermediate readings, total
  quantity, actual running time, **average = total / running time (calculated)**
- Pre/post face measurements, torque, wear rate
- Photos in slots, uploaded plot images, captions
- Observations, conclusion, verdict (free text)
- Planned*/Instructed/Actual compare view (*planned once M3 exists)
- Generate Test Summary DOCX
**Acceptance test:** re-enter 2023RSD08TL Test 1–4 (TCNs reconstructed from
summaries) using the manual logs; generated summaries match the Word
summaries in content, and the calculated leakage values are explained
where they differ from the originals (see 08-B).

### M3 — Test Program
- Program sections, boilerplate library, planned tests with steps,
  monitoring lists, appendix selection, revision table
- TCN001 created from a planned test; deviations vs program shown
- Generate Test Program DOCX
**Acceptance test:** regenerate 2026RSD06TL Celeros program.

### M4 — Final Report
- Result selection & order, generated executive summary table,
  intro/exec summary/conclusion text, report-specific overrides
- Generate Final Report DOCX with frozen result revisions
**Acceptance test:** regenerate 2023RSD08TL report.

### M5 — Data & dashboard
- DCS/DAQ CSV upload, channel mapping (T04 LBI, T05 LBO, …), generated
  plots (logged data, accumulated leakage), actual-condition statistics
- Dashboard (runs in progress, rig occupancy), search by part number
- (Future, not scheduled) PhysicalItem / component lifecycle tracking
  (face markings, history across runs/projects)

### M6 — P&ID builder
- Symbol library from the existing P&IDs (FI, FIT, PI, PT, PDIT, TT, TI,
  seal, heater, cooler "682", valves, sight glass, back-pressure regulator,
  accumulator, air-driven pump, reservoirs, cooling water/air lines)
- Template or blank canvas, drag/move/rotate, orthogonal pipe connections,
  labels, save per project with revisions, export SVG/PNG used as appendix
- Until M6: P&ID is an uploaded image attachment (as today).

### Later / only on request
- Direct DCS Data Analyzer integration
- Structured acceptance criteria with automatic pass/fail indication
- Windows single sign-on, e-signature approvals
- Customer-specific templates

### Explicitly excluded (brief + CLAUDE.md)
AI-generated conclusions, rig control, automatic DCS acquisition,
general PLM functions, microservices, cloud hosting.

## 3. MVP / V1 definition (Deliverable G)

**V1 = M1 + M2.** An engineer can run a whole project's test runs in
TestLab: create TCNs, issue them, log and calculate results, and produce
TCN and Test Summary documents. Program and final report stay in Word for
V1 (as today) but can already take the generated summaries.

Rationale: this covers the most-repeated, most error-prone part (per-run
documents, 4–10 per project) and the calculations. Program and report are
once per project.

*Alternative if PO prefers:* M1 → M3 → M2 → M4 (lifecycle order). This gives
the planned-vs-instructed comparison earlier but delays the first result-side
benefit.

## 4. Later-phase features (Deliverable H)
M3–M6 above plus the "Later" list.

## 5. Recommended next development step (Deliverable J)

Round 1 done (answers_n1 incorporated). Next:
1. PO approves 11-m1-specification.md (and answers its §15 questions or
   accepts the stated defaults).
2. Implementation follows the commit sequence in 11-m1-specification.md §14,
   each commit reviewable on its own.

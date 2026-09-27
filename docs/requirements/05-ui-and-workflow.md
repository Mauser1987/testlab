# 05 — UI / Navigation and End-to-End Workflow (Deliverable E; tasks 7, 8)

> Long-term target. The exact M1 screens and TCN workflow are specified in
> 11-m1-specification.md §6–§7 (M1 has no program, results, report,
> attachments or dashboard).

## 1. Navigation

```
TestLab
├── Dashboard                    (active projects, runs in progress, drafts awaiting issue)
├── Projects
│   └── Project 2026RSD03TL      ← project workspace, tabs:
│       ├── Overview             identity, status, timeline of runs, related projects
│       ├── Field & Configuration  site conditions, baseline seal build
│       ├── Test Program         sections, planned tests, revisions, [Generate DOCX]
│       ├── Runs (TCN)           run register table: No. | status | rig | dates | key conditions | result
│       │   └── TCN 004          tabs: Instruction | Seal build | Conditions | Log parameters |
│       │                              Compare (planned/instructed/actual) | Result | Documents
│       ├── Results              list of results with status (can also be reached from each run)
│       ├── Final Report         selection, texts, generated summary table, [Generate DOCX]
│       ├── Attachments          drawings, specs, P&ID exports, photos library
│       └── Documents            every generated DOCX with revision/date/snapshot
├── Catalogues (admin)           rigs, parameters, materials, people, boilerplate texts, templates
└── Search                       project no., part no., customer, seal type
```

## 2. Main screens

| Screen | Key content | Notes |
|---|---|---|
| Dashboard | Runs currently running, drafts, recently issued documents | Keep simple in V1 (lists, no charts) |
| Project overview | Cover-block data (customer, user, refs, order, seal); run timeline | One place to correct identity data |
| Field & configuration | Site ConditionSet; project default RunSetup (seal positions, conditions) | Feeds program & TCN001 |
| Program editor | Section texts (prefilled from boilerplate), planned tests table, monitoring lists, appendices picker, revision table | Section order = current Word program |
| Run register | Table of TCNs like the Excel "DataBase" sheet but readable | Buttons: New TCN (copy from previous / from planned test / blank) |
| TCN editor | Left: fields; right: "differs from" badges (vs previous TCN, vs program). Arrangement selector switches labels (IB/OB ↔ Plug/Test; barrier ↔ buffer ↔ none) exactly as Excel | Issue → locks, generates TCN DOCX |
| Log sheet | Spreadsheet-like grid; columns = monitored parameters; running hours, interval hours, leakage rate calculated live | Also printable blank log sheet (replaces "Create Test Data Sheet") |
| Result editor | Actual start/end; actual conditions (prefilled from log where possible); pre/post measurements grid; torque; photos by slot; observation & conclusion text; verdict | "Generate Test Summary" |
| Compare view | Planned / Instructed / Actual table per parameter; differences highlighted | Read-only |
| Report builder | Checklist of completed results (order drag), intro/exec summary/conclusion editors, auto summary table preview | "Generate Final Report" |
| Documents | All generated files, which revision is issued, upload edited final version | Traceability |

## 3. Exact workflow (task 8)

### Step 1 — Create Project
1. Projects → New. Enter project no. (validated format `YYYYRSDnnTL`,
   unique), customer, ultimate user, customer refs, pump manufacturer, order no(s).
2. Enter field conditions and seal type/size, arrangement, material code,
   API plan, drawing numbers. Upload drawings as attachments.
3. Enter baseline seal build (IB/OB positions, face part nos., materials).
   → Project status: *Active*.

### Step 2 — Create Test Program
1. Project → Test Program → New (optionally "start from program of
   project X" — copies texts, planned tests, set-up; **cover data comes from
   this project, never from the copied program**).
2. Edit introduction, objective, acceptance criteria.
3. Lab test conditions + test seal configuration default from step 1; edit.
4. Planned tests: add Test 1, Test 2 (or phases) with condition steps,
   duration, planned start.
5. Monitoring lists & procedure sections from boilerplate; edit.
6. Pick appendices (drawings, P&ID).
7. Generate DOCX → review in Word → Issue rev 0 (frozen). Later changes →
   rev 1 with description ("Customer comments").

### Step 3 — Create TCN001
1. Runs → New TCN. Run no. proposed `001`.
   Source = "Planned Test 1" (default for first run).
2. System copies: seal build (baseline), conditions of planned test 1,
   rig, speed, duration, monitored parameters (from program monitoring list),
   instructions (boilerplate pre-test/installation/start/stop/post-test bullets).
3. Engineer edits what differs (e.g. faces C100603033 SIC30, duration
   "min 75"). Diff badges show "differs from program".
4. Optional: record deviation reason.
5. Issue → TCN001 locked, DOCX (and PDF if wanted) generated, blank log sheet
   printable.

### Step 4 — Execute test
- Technicians fill the manual log (paper or directly in the log grid).
- DCS logs as today (outside TestLab in V1).
- Engineer records pre-test measurements & torque (can be entered before
  the run ends — result is created in *draft* when the TCN is started).

### Step 5 — Enter / import results
1. TCN001 → Result. Instructed values pre-filled (read-only column).
2. Enter/finish manual log rows; system calculates running hours, interval
   leakage rates, cumulative & total leakage, average rate, run time.
3. Enter actual conditions (typical/range) — suggested from log.
4. Post-test measurements & torque; wear rate calculated if heights present.
5. Upload DCS plot(s) and accumulated leakage plot as images (V1–M2);
   later: upload DCS CSV → plots generated.
6. Photos into slots IB rotor / IB stator / OB rotor / OB stator (+ extra).
7. Write observations, face condition, conclusion, verdict.

### Step 6 — Generate Test Summary 001
- "Generate Test Summary" → DOCX from template; engineer reviews.
- Mark result *Completed* → frozen revision A. Corrections later → rev B
  (the new revision records what changed and why).

### Step 7 — Create TCN002, TCN003 …
- New TCN → default source "copy of TCN001" (like Excel "Modify/Copy").
- Face conditions proposed as "From Test 01" for re-used faces.
- Change e.g. barrier fluid to MEG/water 30/70 → diff badge "differs from TCN001".
- Repeat steps 3–6.

### Step 8 — Generate Final Report
1. Final Report → New; report no. proposed `<project>R`.
2. Tick completed results to include; order them.
3. Intro pre-filled from program intro; field/test conditions pre-filled from
   project/program, with **report-specific override text** (e.g. "70 barG and 113 barg").
4. Executive summary table generated from the selected results
   (test, date, type, barrier fluid, pressure, IB/OB leak, wear, verdict).
5. Write executive summary text and final conclusion.
6. Generate DOCX → review → Issue rev 0 (frozen, includes result revisions used).

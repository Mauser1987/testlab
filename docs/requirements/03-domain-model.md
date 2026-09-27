# 03 — Domain Model & Schema (Deliverable C; tasks 5, 6, 14)

Entity/relationship level only — no SQL yet.

> **This is the long-term target model.** M1 implements only a small,
> concrete subset (Project, RunSetup, SealPosition, TestRun, Tcn) — see
> 11-m1-specification.md §1. Entities below that are not in M1 are added in
> the milestone that needs them, not earlier. Where M1 deliberately uses a
> simpler shape (e.g. fixed condition fields instead of generic
> ConditionValue rows), the later migration path is noted in the M1 spec.
>
> PO decisions round 1 applied: TestRun 1–* TCN revisions; arrangement and
> plug seal separate; leakage quantities distinct; PhysicalItem is future.

## 1. Core lifecycle entities

```
Project 1 ──── 1 TestProgram ──── * ProgramRevision (issued snapshots)
   │                 │
   │                 └──── * PlannedTest ──── * ConditionStep
   │
   ├──── * TestRun (run_no 001 = TCN001)
   │         ├── 1..* Tcn revision (rev 0, 1, …; one current, others superseded)
   │         │      ├── 1 RunSetup (arrangement, plug seal flag, conditions,
   │         │      │     instructions, monitored parameters)
   │         │      │     └── * SealPosition (test | inboard | outboard | plug)
   │         │      │              └── * ComponentUse            (later)
   │         │      ├── * ConditionStep                          (later, see M1 spec)
   │         │      └── source: project defaults | Tcn | PlannedTest   (provenance)
   │         │
   │         └──── 0..1 TestResult
   │                    ├── * ActualConditionValue
   │                    ├── * LogReading ──── * LogValue
   │                    ├── * DataFile (DCS CSV)
   │                    ├── * FaceMeasurement (pre/post)
   │                    ├── * TorqueMeasurement
   │                    ├── * Figure (photo / plot / drawing, captioned)
   │                    └── free-text fields (observations, conclusion, verdict)
   │
   ├──── * FinalReport ──── * ReportItem → TestResult (selected, ordered, frozen rev)
   │
   ├──── * Attachment (drawings, specs, RCA, images) 
   ├──── * PidDiagram ──── * PidRevision               (later milestone)
   └──── * GeneratedDocument (every DOCX produced, with data snapshot)
```

Required cardinalities from the brief — all satisfied:

| Requirement | Model |
|---|---|
| Project → many TCN/Test Runs | Project 1–* TestRun; every TestRun has a TCN (same number) |
| TCN → one Result/Summary | TestRun 1–0..1 TestResult (result records which TCN revision was in force) |
| Issued TCN never rewritten | TestRun 1–* Tcn revisions; issued revisions immutable |
| Project → one Test Program | Project 1–0..1 TestProgram (with revisions) |
| Project → many attachments/drawings | Project 1–* Attachment |
| Project → current P&ID + revisions | Project 1–* PidDiagram 1–* PidRevision (one flagged current) |
| Final Report → selected completed results | FinalReport *–* TestResult via ReportItem |
| Planned → Instructed → Actual comparison | Same `Parameter` key used in PlannedTest steps, TestRun steps, and Result actual values |

## 2. Entities

### Project
`project_no` (unique, e.g. 2023RSD08TL), `title` (short description),
customer, ultimate_user, end_user_site, customer_refs (text, may hold
several), pump_manufacturer, pump_description, order_nos, status
(active/closed), responsible_engineer, related_projects (*–*).

### FieldCondition (project level; site conditions)
Stored as a **ConditionSet** (see §3) attached to the project, plus:
seal_type_size, arrangement, material_code, api_plan, assembly_drawing,
system_drawing.

### TestProgram / ProgramRevision
TestProgram: document_no, intro, objective, acceptance_criteria (rich text),
test_setup text, procedure section texts, monitoring (DAQ interval +
parameter lists), planning notes, baseline RunSetup, lab ConditionSet,
appendix selection.
ProgramRevision: rev (0,1,2… or A,B…), description, prepared_by,
approved_by, date, frozen snapshot, generated DOCX.

### PlannedTest
Belongs to TestProgram. `sequence` (Test 1, 2… or phase id "7.2.3"),
name (Characterization Test…), description, planned_start, duration text,
stop/start requirement, 1..* ConditionStep.

### TestRun
`run_no` (1…, displayed 001; unique per project; **Run No. = TCN No.**).
Thin parent that later Results attach to.

### Tcn (TCN revision)
Belongs to TestRun. `revision` (0, 1, …), status (draft / issued /
superseded / cancelled), created_date, issued_at/by, prepared_by initials,
project_description (copied), revision_reason, source (project defaults /
Tcn / later PlannedTest), own RunSetup, issued DOCX + data snapshot.
Later: `realises_planned_test`, deviations_from_program (computed diff +
text), purpose text, rotation, tester drawing, ConditionSteps.

### RunSetup (copyable technical block)
Used both as **project defaults** (Project 1–1 RunSetup) and as each TCN
revision's own copy (Tcn 1–1 RunSetup). Holds arrangement, `plug_seal_present`,
reference drawing, test unit, speed, duration, run description
(instructions), process, seal-support and Plug Seal circuit conditions
(separate fields per circuit; speed common), monitored
parameters; 1..* SealPosition. Copy = deep copy of this block.

### ConditionStep
A phase inside a PlannedTest or TestRun with constant set-points.
`sequence`, label ("100 h @ 60 °C"), duration text,
* ConditionValue.

### ConditionValue (the flexible part)
| Field | Example |
|---|---|
| parameter → Parameter | barrier_pressure |
| circuit | process / barrier / buffer / plan23 / cooling |
| position | IB / OB / plug / test / – |
| text_value (as engineer wrote it) | `Approx. 35-50`, `min 75`, `TBD`, `NA` |
| num_value / num_min / num_max (optional, parsed) | 35 / 50 |
| unit | °C |
| qualifier | nominal / min / max / approx / tbd / na |
| origin | program test 2 / TCN003 / entered |

This keeps "not a rigid schema": new parameters are rows, not columns.

### Parameter (catalogue — reusable measurement definition)
code, name, default unit, category (condition / log channel / measurement),
circuit applicability, position applicability, decimals, DCS tag mapping
(e.g. `T04` → barrier inlet temp LBI), display order.
Seeded from the Excel Y/N list + program monitoring lists:
process pressure, process inlet/outlet temp, process flow,
barrier/buffer pressure, inlet/outlet temp, flow, IB/OB face temp,
IB/OB leakage, speed, torque, power consumption, cooling water in/out.

### Arrangement, Plug Seal, SealPosition / ComponentUse
- Arrangement (PO decision): `single` | `dual_pressurized` | `dual_unpressurized`.
  No other values in M1.
- Plug Seal: process-side simulation/test equipment, **not** a stage of the
  seal under test. Separate boolean `plug_seal_present` + a Plug
  SealPosition + its own circuit conditions (medium, pressure, temperature,
  flow). Never encoded in the arrangement value.
- Positions present: single → Test; dual → Inboard + Outboard; plus Plug if
  `plug_seal_present`.
- Seal-support circuit label follows arrangement: dual pressurized →
  "Barrier", dual unpressurized → "Buffer", single → "Flush" (optional,
  e.g. Plan 23 — single does **not** imply no support circuit, PO round 2).
- (Later) material_code, drawings per build.
- SealPosition: role (test / inboard / outboard / plug), seal_type_size,
  stationary face, rotating face, springs (M1); rotation etc. later.
- ComponentUse: kind (stationary face, rotating face, spring, sleeve,
  gasket, backing ring…), part_no, material, balance_ratio, qty,
  marking/identity (#1…#4), condition (new / from run X / re-lapped),
  `physical_item` (optional link, see below).

### PhysicalItem (future — PO: component lifecycle tracking is not M1)
One physical face/sleeve with a marking, so "same faces from test 01
without lapping" and "use the 2023 sleeve" are traceable across runs and
projects. Keeps measurement history (height → wear rate).

### TestResult
actual_start, actual_end, run_time (calc from log, overridable),
status (draft / completed / approved), prepared_by, approved_by,
observations text(s), face_condition texts, conclusion, verdict (short),
revision. 1..* ActualConditionValue (same shape as ConditionValue,
plus stat: avg/min/max/range, source: log/manual/DCS).

### LogReading / LogValue (manual log)
LogReading: timestamp, by, running_hours (calc), notes.
LogValue: parameter, position, value.

### Leakage (M2 — PO decision: keep these distinct)
- `LeakageMeasurementMethod` per result + seal position: reservoir level
  drop / collected from seal drain / other (text); may differ per seal.
- Intermediate readings: LogValue rows (quantity since previous reading,
  or level reading, depending on method) → interval rate calculated.
- `total_leakage_quantity` per seal position: calculated from readings;
  may be entered directly when readings are incomplete (flagged as entered).
- `actual_running_time`: calculated from log/start-end; overridable with reason.
- `average_leakage_rate` = total_leakage_quantity / actual_running_time —
  **always calculated** when both exist; never typed.
- Excel rule preserved: reading = ml since previous reading;
  interval hours = running-hours difference; interval rate = ml / hours.

### DataFile
Uploaded DCS/DAQ CSV: file, channel mapping, time range, import status.
(Automatic acquisition is out of scope; upload/import only, later milestone.)

### FaceMeasurement / TorqueMeasurement
FaceMeasurement: position, face (stationary/rotating), phase (pre/post),
kind (waviness, taper, Ra, profile, height, flatness in light bands),
value, unit, location/count ("taper on 2 locations"), file (profile plot).
TorqueMeasurement: phase (pre-start/after-stop), time offset (0, 10 min), value Nm.

### Figure / Attachment
Attachment: project-level file (drawing, spec, RCA, P&ID export) with
kind, number, revision, title, file, uploaded_by/date.
Figure: an image used in a document — photo, plot, cross-section,
rig photo — with caption, owner (result/program/report), slot
(e.g. "IB rotor post-test"), linked measurement (Ra value shown in caption).

### FinalReport / ReportItem
FinalReport: report_no (e.g. 2023RSD08TLR), revision table, intro,
executive summary text, conclusion, recommendations, report-specific
condition text overrides, appendix selection.
ReportItem: test_result, frozen result revision, order, section title
("Test N°1 – (Aug 23 – Aug 29, 2023)" — generated, editable).

### GeneratedDocument
doc_type (program / tcn / summary / report), owner record, revision,
template used + template version, generated_at/by, file, JSON snapshot of
data used, `issued` flag, optional uploaded "final edited" DOCX/PDF.

### Supporting catalogues (small, editable)
TestRig (A, B, 4 … ; motor power, notes), Person (initials, name, role),
Material (code, name — e.g. SL = reaction bonded SiC), Boilerplate text
blocks (procedure sections), DocumentTemplate.

### Revision / audit
Every issuable entity (ProgramRevision, Tcn, TestResult, FinalReport)
has `revision` + `status`. Issued records are immutable; changes create a
new revision with a reason — this replaces Excel's silent overwrite/delete.
Deletion of issued records is not allowed (cancel instead).
M1 records created/updated/issued by & at; a field-level change log table
is deferred until drafts of Results/Reports need it (not required in M1
because issued TCNs cannot change at all).
Approval workflow: not built in M1 (PO); approver name/date fields are
added with the Program/Report milestones.

## 3. Planned → Instructed → Actual comparison

Because PlannedTest steps, TestRun steps and Result actuals all use
`Parameter + circuit + position`, a comparison table is a simple join:

| Parameter | Planned (Program Test 1) | Instructed (TCN001) | Actual (Result 001) |
|---|---|---|---|
| Barrier pressure | 70 barG | 70 barg | 70 barg (69.9–80.5) |
| Speed | 2980 rpm | 2980 rpm | 2900 rpm (log) / "2950" (summary) |
| Duration | 100 h | min 75 h | 144.6 h |
| Barrier fluid | Water (potable) | Water | Demi water |

(Values illustrate the real 2023/2026 data and show exactly the drift
the tool should make visible.)

## 4. Reusable entities (task 6) — summary

| Reusable entity | Reused by | Mechanism |
|---|---|---|
| Seal configuration (RunSetup + SealPosition) | Program baseline → each TCN → Result/Summary | copy-on-create + diff |
| Seal faces / components (ComponentUse, PhysicalItem) | TCNs, results, across projects | part catalogue by part no.; physical items by marking |
| Operating/test conditions (ConditionSet/Step/Value) | Field, program tests, TCN, results | same structure everywhere |
| Test instructions | TCN from previous TCN or boilerplate | copy + edit |
| Measurement definitions (Parameter) | TCN log selection, log sheet, results, plots, DCS mapping | catalogue |
| Attachments | Program appendices, report appendices, TCN reference | project library, pick per document |
| Photographs | Summary, report | Figure with slot + caption |
| Plots | Summary, report | Figure (uploaded now, generated later) |
| Conclusions | Summary → report | reference to frozen result revision |
| Revisions | All issued documents | revision + snapshot (issued revisions immutable) |

# 11 — M1 Implementation Specification: TCN Register

Status: **approved in principle** (PO, `/answers_n2.md`, 2026-09-27) with the
corrections incorporated below; implementation started with Commit 1 (§14).
Date: 2026-09-27 (rev. 2; rev. 1 2026-09-26). Amended 2026-09-29 by the
post-Commit-10 stabilization decisions (§17): the controlled TCN document
is a **PDF**; registration with approval by an administrator.
Inputs: 01–10 in this folder, `/answers_n1.md` (PO decisions round 1),
`/answers_n2.md` (PO corrections round 2),
`reference/Testlab Data Program 2026RSD06TL.xlsm`, `reference/tcn/TCN001.pdf`.

## 0. Objective and boundary

**M1 replaces the Excel/VBA "Testlab Data Program" TCN generator** with a
central TestLab web application. An engineer can:

1. create/open a Project;
2. store the minimum project and seal information needed for TCNs (project defaults);
3. create TCN001 from the project defaults;
4. configure the seal arrangement and the Plug Seal (required for single, optional for dual);
5. define the run conditions and instructions;
6. generate the TCN document (PDF, §17 S1);
7. issue/lock the TCN;
8. create TCN002 by copying TCN001 (or any other TCN);
9. change only what differs;
10. generate/issue TCN002 without affecting TCN001.

Also in M1, because they are part of today's Excel TCN workflow:
- **Test Data Sheet export** (Excel "Create Test Data Sheet": blank manual log
  with columns derived from the selected monitored parameters);
- formal **TCN revisions** and **cancel** (PO decision);
- explicit **Plug Seal operating conditions** on the TCN when a Plug Seal
  is installed (PO decision, round 2) — these are the **Process
  Conditions** (domain correction, §5).

**Not in M1:** legacy Excel/XLSM import or any historical migration (PO,
round 2: the data model is first validated on real new projects; see §12),
Test Program, Results, Test Summary, Final Report, DCS, P&ID,
attachments, component lifecycle tracking, condition steps, catalogues
(rigs/materials/parameters as tables), a full API piping-plan model,
approval workflow,
field-level change log, the Excel "Add test results"/"Print test results"
functions (unused in practice — all result columns empty).

## 1. Entities and database fields

Five tables plus Django's `auth_user`. All text is stored as typed
(trimmed); condition values are **text**, exactly as in Excel
("min 75", "TBD", "60 - 40").

### 1.1 `Project` (app `projects`)

| Field | Type | Rules |
|---|---|---|
| id | auto PK | |
| project_no | varchar(20) | required, unique (case-insensitive), stored upper-case; RSD format is a convention (warning only, §10 V1); read-only once a TCN of the project has been issued (§10 V2) |
| description | varchar(200) | required. Printed as "Project Description" (e.g. `ADNOC BAB UHTW/UHTW 4.750/4.750`); copied into each new TCN |
| customer | varchar(200) | optional; list/search only, not printed in M1 |
| default_setup | one-to-one → RunSetup | required, created with the project, PROTECT |
| created_at, created_by, updated_at, updated_by | timestamps / FK user | |

### 1.2 `RunSetup` (app `projects`) — the copyable technical block
Used twice: as **project defaults** (`Project.default_setup`) and as each
TCN revision's **own copy** (`TcnRevision.setup`). One RunSetup is owned by exactly
one Project *or* one TcnRevision.

| Field | Type | Excel column | Printed on TCN as |
|---|---|---|---|
| id | auto PK | | |
| arrangement | varchar(24), choices `single` / `dual_pressurized` / `dual_unpressurized` — the **mechanical seal arrangement under test** | Arrangement (FA) | column headings (§5) |
| plug_seal_present | bool, default false — Plug Seal (test equipment establishing the process conditions) installed; **always true for single** (V16) | (Arrangement = 1) | Plug Seal seal column |
| reference_drawing | varchar(200) | RefDwg | Reference Drawing |
| run_description | text | TestRunDescription | Test Run Description |
| test_unit | varchar(20) | TestUnit | Test Unit |
| duration | varchar(50) | Duration | Duration: `<v> hours` |
| speed | varchar(50) | Speed | Speed: `<v> rpm` |
| process_medium | varchar(100) | Product | Test Medium (Process Fluid) — the Plug Seal operating fluid |
| process_pressure | varchar(50) | ProdPress | Pressure `<v> barg` |
| process_inlet_temperature | varchar(50) | ProdTemp | Inlet Temperature `<v>°C` |
| process_flow | varchar(50) | ProdFlow | Flow `<v> l/min` |
| seal_support_medium | varchar(100) | Bar/Buf | Test Medium (Barrier/Buffer/Flush Fluid) |
| seal_support_pressure | varchar(50) | Bar/BufPress | Pressure |
| seal_support_inlet_temperature | varchar(50) | Bar/BufTemp | Inlet Temperature |
| seal_support_flow | varchar(50) | Bar/BufFlow | Flow |
| monitored_parameters | JSON list of codes (§5.4), canonical order | the 12 Y/N columns | not printed; drives Test Data Sheet |

The conditions are grouped by **physically separate circuit**. There is
exactly **one process-side group**, the Process Conditions: the Plug Seal
is the equipment that establishes them, so its operating fluid, pressure,
temperature and flow *are* the Process Conditions and it has no condition
group of its own. The seal-support circuit is physically separate and keeps
its own fields:

| Group | Fields | Applies |
|---|---|---|
| Common Test Run conditions | test_unit, duration, speed | always. Speed is common to the whole shaft, therefore **not** repeated for the Plug Seal |
| Process Conditions (established with the Plug Seal) | process_* | only when plug_seal_present (V6) — hence always for single |
| Mechanical-seal support circuit | seal_support_* — barrier (dual pressurized), buffer (dual unpressurized) or flush/support system such as Plan 23 (single; optional) | any arrangement |

M1 holds **one** mechanical-seal support circuit (as the existing TCN) and
does not model API piping plans; a plan designation (e.g. "Plan 23") or a
second circuit is described in the run description (§15 Q-J).

### 1.3 `SealPosition` (app `projects`)

One row per seal in the set-up. Roles `test` / `inboard` / `outboard` are
the **mechanical seal arrangement under test**; role `plug` is the
**Plug Seal**, process-side simulation/test equipment — not a stage of a
dual seal. It shares this table only because it has the same four
descriptive fields; code, comments and UI keep the two apart (§5).

| Field | Type | Rules |
|---|---|---|
| id | auto PK | |
| setup | FK → RunSetup, CASCADE | |
| role | varchar(10), choices `plug` / `test` / `inboard` / `outboard` | unique (setup, role) |
| seal_type_size | varchar(100) | e.g. `UHTW 4.750` |
| stationary_face | varchar(100) | e.g. `C100603033 (SIC30)` |
| rotating_face | varchar(100) | e.g. `C100603035 (SL WAVY)` |
| springs | varchar(100) | e.g. `668838NL (9)` |

Exactly the applicable roles exist (§5.1).

### 1.4 `TestRun` (app `tcn`)

| Field | Type | Rules |
|---|---|---|
| id | auto PK | |
| project | FK → Project, PROTECT | |
| run_no | smallint 1–999 | unique (project, run_no); displayed `%03d` → "001"; **Run No. = TCN No.** |
| created_at, created_by | | |

Thin parent so that M2 Results attach to the run, not to one revision.

### 1.5 `TcnRevision` (app `tcn`) — one row per TCN revision

(Named `Tcn` in rev. 2 of this spec; renamed in Commit 5 to make the
TestRun 1–* revision boundary explicit. Fields unchanged.)

| Field | Type | Rules |
|---|---|---|
| id | auto PK | |
| test_run | FK → TestRun, PROTECT | |
| revision | smallint ≥ 0 | unique (test_run, revision); rev 0 = original |
| status | varchar(12): `draft` / `issued` / `superseded` / `cancelled` | §4 |
| setup | one-to-one → RunSetup, PROTECT | own copy, never shared |
| project_description | varchar(200) | copied from Project at creation; editable while draft |
| prepared_by | varchar(10) | initials, e.g. `MG`; default from user (§7); required to issue |
| created_date | date | set once at creation (Excel `TCNCreate`); printed "Created:" |
| revision_reason | text | required to issue when revision ≥ 1 |
| source_kind | varchar(20): `project_defaults` / `tcn_copy` / `new_revision` | (a `legacy_import` value is added with the post-M1 importer, §12) |
| source_tcn | FK → TcnRevision, null, PROTECT | set for `tcn_copy` and `new_revision` |
| issued_at | datetime, null | set at issue |
| issued_by | FK user, null | set at issue (required when status ≠ draft) |
| issued_document | file, null | **PDF** generated at issue — the controlled artifact (§17 S1); never replaced |
| issued_document_sha256 | char(64) | SHA-256 of the stored PDF |
| issued_snapshot | JSON, null | exact render context used (§9) |
| template_sha256 | char(64) | hash of the template file used |
| cancelled_at, cancelled_by, cancel_reason | | only for `cancelled` |
| row_version | int, default 1 | optimistic locking for draft edits |
| created_at, created_by, updated_at, updated_by | | |

Identity and audit fields (PO clarification before Commit 9):
`created_by` = the authenticated user who creates the draft, `created_at` =
automatic creation timestamp; `prepared_by` = the engineer responsible for
preparing the TCN, defaulted from the current user's initials and editable
while draft; `issued_by` = the authenticated user performing the Issue
action (never entered manually), `issued_at` = automatic issue timestamp.
Once issued, all of them are immutable with the rest of the record.

Database constraints (portable Django `UniqueConstraint` with `condition`,
supported by SQLite and PostgreSQL):
- one `draft` per test_run;
- one `issued` per test_run (the current revision).

Further check constraints (Commit 5): status and source_kind values;
source_tcn null exactly for `project_defaults`; revision ≥ 1 exactly for
`new_revision`; issued_at/by set exactly when status ≠ draft; cancelled
fields set (with a non-empty reason) exactly when cancelled; TestRun
run_no 1–999. Model-level rules: a revision is created as a draft with
revision = highest + 1; a new revision's source is in the same run; the
setup is never a project's default setup; test_run, revision, setup,
source and created fields never change; locked revisions, their setup and
seal positions cannot be saved or deleted; a TestRun's run_no/project is
fixed once a revision has been issued; deleting a draft deletes its setup,
and deleting the last one (rev 0) deletes the TestRun.

## 2. Relationships

```
auth_user
Project     1 ──── 1 RunSetup (default_setup)
Project     1 ──── * TestRun (run_no unique per project)
TestRun     1 ──── 1..* TcnRevision (revision 0, 1, …)
TcnRevision 1 ──── 1 RunSetup (own copy)
RunSetup    1 ──── 1..3 SealPosition (applicable roles only)
TcnRevision * ──── 0..1 TcnRevision (source_tcn: copied from / revised from)
```
Future attachment points (not built): TestResult → TestRun (M2);
PlannedTest → TcnRevision source (M3); ConditionStep → RunSetup (M2/M3).

## 3. Project defaults vs TCN snapshots

| Value | Project | TCN | Rule |
|---|---|---|---|
| project_no | master | read via TestRun→Project; frozen in issued_snapshot and file name | correctable until the first TCN of the project is issued, then blocked (V2) → issued TCNs stay correct |
| project description | master | **copied at creation**, editable in draft | as in Excel (per-run field); later project edits don't touch TCNs |
| customer | master | – | not on TCN |
| arrangement, Plug Seal presence, positions, drawing, unit, speed, duration, process / seal-support conditions, run description, monitored parameters | **defaults** (Project.default_setup) | **own copy** (TcnRevision.setup) | copied when the TCN is created from defaults or from another TCN; afterwards independent |
| prepared_by, created_date | – | TCN only | set at creation |
| revision, status, issue data, issued PDF, snapshot | – | TCN only | frozen at issue |

Rules:
- **Editing project defaults never changes any existing TCN** (draft or issued).
- **Issued/superseded/cancelled TCNs are immutable** — enforced in the model
  layer (a save or delete that changes content raises an error), not just
  hidden in the UI. Allowed transitions only: issued → superseded,
  issued → cancelled.
- The issued PDF and snapshot are the record of what was issued; they
  are never regenerated.

## 4. Numbering, status, issue, lock and revision rules

### Numbering
- run_no proposed = highest run_no in the project + 1 (first = 1); the
  engineer may type another free number (gaps allowed; needed for legacy).
  Input accepts `4`, `04`, `004`. Display always `%03d`.
- TCN number shown as `TCN001`; revision ≥ 1 shown as `TCN001 rev 1`.
- Document header: "Run/TCN No.: 001" (rev 0) or "Run/TCN No.: 001 rev 1".
- File name: `<project_no>-TCN001.pdf`, `<project_no>-TCN001-rev1.pdf`
  (draft preview: `…-DRAFT.pdf`).

### Status machine

```
            create                     issue
 (none) ───────────► draft ───────────────────► issued ──── new revision issued ───► superseded
                       │                          │
                       │ delete (no trace)        │ cancel (reason)
                       ▼                          ▼
                    (removed)                 cancelled
```

| Action | Allowed when | Effect |
|---|---|---|
| Edit | status = draft | save with row_version check |
| Delete draft | status = draft | rev 0 → deletes TcnRevision, its RunSetup and the TestRun; rev ≥ 1 → deletes only that draft revision |
| Issue | status = draft and issue validation passes (§10) | in one DB transaction: render the PDF (template → temporary DOCX → PDF), store the PDF + hashes + snapshot, set issued_at/by, status = issued; previous issued revision → superseded. Any failure — including a failed PDF conversion — rolls back everything; TCN stays draft |
| New revision | TCN is the current issued revision; run not cancelled; no draft exists for this run | creates revision n+1 as draft: deep copy of setup + project_description + prepared_by (current user), source_kind = new_revision, source_tcn = issued rev |
| Cancel | current issued revision, reason required | status = cancelled; run shows as cancelled; no new revisions; may still be used as a copy source |
| Copy to new TCN | any TcnRevision (any status) of the **same project** | §7 |

Approval: none in M1 (PO). Any logged-in (active) user may issue; the
check is kept in one place so this can be restricted later (§17 S3).
Execution deviations are **not** entered on the TCN (they belong to the M2 Result).

## 5. Seal arrangement + Plug Seal

Two separate things are configured:
- the **seal arrangement under test** — single (Test seal) or dual
  pressurized / unpressurized (Inboard + Outboard seal); and
- the **Plug Seal** — test equipment on the same shaft that establishes the
  process-side conditions for the seal under test. It is never presented
  as a stage of the seal under test.

**Domain correction (after M1 hands-on testing, 2026-09-30).** The first
M1 implementation gave the Plug Seal its own condition group (plug_*)
next to the Process Conditions. That was wrong: the Plug Seal *is* how the
process conditions are established, so there are not two circuits. Rules
since the correction:
- one process-side group only: **Process Conditions** (medium, pressure,
  temperature, flow); no plug_* condition fields;
- **single ⇒ Plug Seal** (V16): a single seal cannot be tested alone. This
  is a constraint, not a default; the arrangement stays "Single" (there is
  no "Single + Plug" arrangement);
- dual pressurized / unpressurized: Plug Seal optional; when installed its
  conditions are the Process Conditions;
- Process Conditions exist **only with the Plug Seal** (V6; PO decision:
  without a Plug Seal there is no process side, as TCN001 of 2026RSD03TL
  shows "NA");
- the seal-support circuit (Flush / Barrier / Buffer) stays separate;
- Plug Seal equipment data stays separate: its seal position (type, faces,
  springs) and its own measurements (plug_face_temp, plug_leakage).

Existing data was migrated by projects migrations 0005/0006 (plug_* values
moved into empty process_* fields; plug_pressure / plug_inlet_temp /
plug_flow codes renamed to the process codes; single setups given the Plug
Seal). Rows needing a decision (different process and plug values, or
process conditions without Plug Seal) stop the migration with a report and
nothing is changed. Issued TCNs keep their stored PDF, SHA-256 and snapshot.

### 5.1 Positions present

| arrangement | plug_seal_present = false | plug_seal_present = true |
|---|---|---|
| single | *not allowed* (V16) | Plug, Test |
| dual_pressurized | Inboard, Outboard | Plug, Inboard, Outboard |
| dual_unpressurized | Inboard, Outboard | Plug, Inboard, Outboard |

Column order on screen and in documents: Plug, Test / Plug, Inboard, Outboard.

### 5.2 Terminology (migrated from Excel label formulas, generalised)

| Item | single | dual_pressurized | dual_unpressurized |
|---|---|---|---|
| Seal-support circuit label | Flush (§15 Q-B) | Barrier | Buffer |
| TCN conditions columns | Process Fluid, [Flush Fluid — only if any seal_support value is filled] | Process Fluid, Barrier Fluid | Process Fluid, Buffer Fluid |
| Test Data Sheet medium row | "Flush Medium:" if filled, else blank (as Excel) | "Barrier Medium:" | "Buffer Medium:" |
| Test Data Sheet seal-support columns prefix | "Flush" | "Barrier" | "Buffer" |

Column order: Process, seal support. The Process Fluid column holds the
conditions established with the Plug Seal; without a Plug Seal (dual only)
it prints NA, as the Excel TCN did. There is no Plug Seal Fluid column.

| Role | TCN seal column heading | Short label (log sheet) |
|---|---|---|
| plug | Plug Seal | Plug |
| test | Test Seal | Test |
| inboard | Inboard Seal | IB |
| outboard | Outboard Seal | OB |

Differences from Excel (deliberate):
- Plug Seal combinable with any arrangement (PO decision); Excel only
  had "arrangement 1 = plug + test". It is required for single;
- the Plug Seal has no conditions column of its own: its conditions are
  the Process Conditions, as in Excel (domain correction);
- a single seal may have a seal-support (flush) circuit; Excel cleared and
  hid it for single (PO decision: do not assume single = no circuit);
- log sheet position labels follow the role (Excel printed "IB/OB" even in
  arrangement 1);
- Excel Summary-sheet bug ("Inboard Seal" on the OB column) not reproduced.

### 5.3 Switching arrangement / Plug Seal on a draft or on project defaults
- Choosing single installs the Plug Seal automatically; the "Plug Seal
  installed" box is shown ticked and cannot be unticked. Switching single →
  dual keeps the Plug Seal (and the Process Conditions); it can then be
  removed.
- Positions are added (empty) or removed to match §5.1.
- Changing the arrangement **never clears seal_support_* values**; only
  their label changes (Barrier / Buffer / Flush). (Excel `Keuzerondje16`
  cleared them for single — deliberately not migrated.)
- Removing the Plug Seal (dual only) removes the plug position **and** the
  Process Conditions.
- When a switch would **discard non-empty data** (a removed position or
  non-empty process_* values), the form is re-shown with a list of what
  will be discarded and a required "discard" confirmation checkbox. (Excel
  cleared silently.)
- Monitored codes no longer applicable (codes of removed roles; process
  codes when the Plug Seal is removed) are removed.

### 5.4 Monitored parameters (from the 12 Excel Y/N flags)
Canonical order = Excel log column order.

| Code | Applicable | Log sheet column(s) |
|---|---|---|
| process_pressure | Plug Seal present | Process Pressure [barg] |
| process_inlet_temp | Plug Seal present | Process Inlet Temp. [°C] |
| process_outlet_temp | Plug Seal present | Process Outlet Temp. [°C] |
| process_flow | Plug Seal present | Process Flow [l/min] |
| seal_support_pressure | always | `<prefix>` Pressure [barg] |
| seal_support_inlet_temp | always | `<prefix>` Inlet Temp. [°C] |
| seal_support_outlet_temp | always | `<prefix>` Outlet Temp. [°C] |
| seal_support_flow | always | `<prefix>` Flow [l/min] |
| `<role>`_face_temp | role present | `<short>` Face Temp. [°C] |
| `<role>`_leakage | role present | `<short>` Leakage [ml], Over [hours], `<short>` Leakage Rate [ml/hr] |

Role order: plug, test, inboard, outboard. Seal-support codes are
applicable for single (e.g. a Plan 23 flush; the 2025RSD02TL record logs
them). Process codes (PO, round 3, corrected): the pressure, inlet
temperature and flow logged continuously by the DCS/LabVIEW system while
operating the Plug Seal are the process variables, so they use the process
codes (the former plug_pressure / plug_inlet_temp / plug_flow codes were
renamed to them). M1 only defines the codes (selection, log-sheet columns);
no DCS acquisition, time series or calculations. Measurements of the Plug
Seal itself keep their role codes `plug_face_temp` and `plug_leakage`.

## 6. Screens, forms and navigation

Top bar: **TestLab** · Projects · user name · Log out.
Breadcrumbs: Projects › 2026RSD03TL › TCN001 rev 0.
All pages require login (Django auth), except Login and Register. Django
admin: user management and approval of registered accounts (superusers;
§17 S2).

| # | Screen | Content / actions |
|---|---|---|
| S1 | Login | "Log in \| Register"; email address + password (a bootstrap username also works); pending accounts are told they await approval |
| S1a | Register | first name, last name, corporate email address, password, confirmation; only approved domains; account created inactive (§17 S2) |
| S2 | Project list | Search (project no., description, customer). Table: Project no. · Description · Customer · No. of TCNs · last TCN created. **New project** |
| S3 | Project form (create/edit) | project_no (read-only once a TCN has been issued; a non-RSD-format number shows a warning but can be saved), description, customer. On create → continue to S5 (defaults) |
| S4 | Project page | Identity block (Edit). Project defaults summary (Edit). **TCN register**: Run/TCN · Rev · Status · Created · Prepared by · Test unit · Arrangement (+ Plug Seal) · Speed · Barrier/Buffer/Flush pressure · actions (Open · Copy to new TCN · Download PDF). **New TCN** |
| S5 | Project defaults form | Shared *Run setup form* (below) without TCN header fields |
| S6 | New TCN | Run no. (proposed, editable). Source: ◉ Copy of TCN [select, revisions of this project only; default = current revision of highest run] ○ Project defaults (default when the project has no TCN yet). **Create** → S7 |
| S7 | TCN edit (draft) | Header: project no., Run/TCN no., rev, status DRAFT, source ("copied from TCN001 rev 0"). Fields: project description, prepared by, revision reason (rev ≥ 1). **Run setup form**. Fields differing from the source show "changed — was: …". Buttons: **Save** · **Preview PDF** · **Test Data Sheet** · **Issue…** · Delete draft |
| S8 | Issue confirmation | Issue-validation errors, or: summary, list of changes vs source, notice "An issued TCN cannot be changed; changes require a new revision". **Confirm issue** |
| S9 | TCN view (issued / superseded / cancelled) | Read-only content, status banner. **Download issued PDF** · Test Data Sheet · Copy to new TCN · New revision (current issued only) · Cancel TCN. Revision history of the run: rev, status, created, issued at/by, reason, download |
| S10 | Cancel TCN | reason (required), confirm |

**Run setup form** (used by S5 and S7), in the order of the TCN document:
1. Test Run Description — large monospace textarea (indentation preserved).
2. Seal Information, in two visually separate panels:
   - *Seal under test* — arrangement (3 radio buttons), reference drawing,
     positions grid (Test, or Inboard + Outboard; rows Seal Type and Size /
     Stationary Seal Face / Rotating Seal Face / Spring(s));
   - *Plug Seal (process-side test equipment)* — "Plug Seal installed"
     checkbox (ticked and locked for single); when ticked, the same four
     fields for the Plug Seal.
3. Test Conditions — *Common*: test unit, duration [hours], speed [rpm]
   (applies to the whole shaft, incl. Plug Seal). Then one column per
   circuit, each with medium, pressure [barg], inlet temperature [°C],
   flow [l/min]: *Process (established with the Plug Seal)* — only when the
   Plug Seal is installed; *Barrier* / *Buffer* / *Flush (optional, e.g.
   Plan 23)* per arrangement.
4. Parameters to log — checkboxes grouped Process (with Plug Seal) / Barrier-Buffer-Flush / per seal position.

Changing arrangement or Plug Seal re-renders the positions grid, circuit
labels/columns and parameter list (small htmx request; plain "Update" button as
fallback). Units are shown next to inputs, not typed.

## 7. Create-TCN and Copy/Next-TCN workflow

**Create project** (S2 → S3 → S5): enter project no., description,
(customer); set project defaults (arrangement default *dual pressurized*
as in Excel, Plug Seal unchecked, no parameters ticked as in Excel "Add new").

**Create TCN001** (S4 → S6 → S7):
1. Source = project defaults (only option when no TCN exists); run no. 1.
2. System creates TestRun(1) + TcnRevision rev 0 draft with a deep copy of the
   default RunSetup and positions; project_description ← Project.description;
   prepared_by ← user initials (first letters of first and last name,
   upper-case, editable); created_date ← today; source_kind = project_defaults.
3. Engineer completes/edits fields (S7), **Preview PDF**, optionally
   **Test Data Sheet**, then **Issue** (S8) → issued PDF stored; TCN001 locked.

**Create TCN002 (next TCN)** (S4 → "Copy to new TCN" on TCN001, or New TCN):
1. Run no. proposed 2; source preselected = TCN001 (current revision).
2. Deep copy of TCN001's RunSetup (all technical fields incl. all three
   circuits, run description, monitored parameters, positions); project_description ← **current Project
   description** (not the source's); prepared_by ← current user; created_date ← today.
3. S7 shows the form; every field initially equals the source. The
   engineer edits only what differs; changed fields are marked.
4. Preview → Issue. TCN001's record, PDF file and hash are untouched.

A TCN copy (`tcn_copy`) must come from a TCN of the **same project**
(PO, after Commit 5; enforced in the model). Reusing a TCN of another
project is not a TCN copy in M1; it may later become a separate
template/project-copy feature.

**Formal change of an issued TCN**: S9 → New revision → draft rev 1
(copy) → edit → reason → issue → rev 0 becomes superseded; both PDFs kept.

## 8. Business logic migrated from Excel/VBA

| # | Excel behaviour (source) | M1 rule |
|---|---|---|
| E1 | Run no. padded to 3 digits (`Input!EC2`) | display `%03d` |
| E2 | "Run number already used!" (`Knop12_Klikken`, `EC4`) | unique (project, run_no) with same message |
| E3 | Project and run mandatory (`Knop12`) | required fields |
| E4 | Modify → change run no. → Add = copy (`Knop3`, `Knop12`) | Copy to new TCN (§7) |
| E5 | Arrangement 1/2/3 option buttons, default 3 (`FA2`) | arrangement + plug_seal_present (§5), default dual pressurized (legacy 1 = single + Plug Seal, 2 = dual unpressurized, 3 = dual pressurized) |
| E6 | Labels switch Plug/Test ↔ Inboard/Outboard, Barrier/Buffer/none (`TCN!E11,H11,H23`) | §5.2 (single → Flush instead of none) |
| E7 | Single seal clears & greys support fields (`Keuzerondje16`) | **not migrated** (PO): values kept, label "Flush", column optional (§5.3) |
| E8 | Empty process values print **NA**; empty support values print blank (`TCN!E24:E27`, `H24:H27`) | same (§9.3); empty Plug Seal values print **NA** |
| E9 | Units appended only when a value exists: " hours", " rpm", " barg", "°C", " l/min" | same (§9.3) |
| E10 | TCN header "Project No.: … / Run/TCN No.: …"; footer "Prepared by: …", "Created: …" (`Knop5`) | same layout (§9) |
| E11 | Created date set once at first save (`CK` = Date) | `created_date` set at creation |
| E12 | Y/N flags → log columns in fixed order, leakage adds "Over [hours]" and "Leakage Rate [ml/hr]", then "Notes:" (`Knop6`) | §5.4, §9.5 |
| E13 | Running hours `=IF(A="","",((A+B)-($A$7+$B$7))*24)` | same formula in XLSX |
| E14 | Over `=IF(date="","",IFERROR(C−C_prev,0))`; rate `=IF(date="","",IFERROR(ml/over,0))` | same formulas |
| E15 | Log sheet header: project no., run no., description, test unit, speed, "Product" medium, barrier/buffer medium, IB/OB seal type + faces, torque before start-up / after 10 min / after stop / after 10 min | same (roles per §5) |
| E16 | Data sheet rows 7–100, formula cells locked, sheet protected | same |

Not migrated: silent overwrite (`Knop13`), permanent delete (`Button15`),
results form & photo paths (`Knop4`, `Knop7`, `Results_*`) → M2;
DataBase import → post-M1 (§12).

## 9. Document generation architecture (Word template → PDF)

Pipeline (§17 S1): TCN snapshot (render context) → Word template rendered
with docxtpl → temporary DOCX → PDF conversion (LibreOffice headless) →
PDF previewed, or stored and served at issue. The DOCX is an internal
intermediate: it is never stored or offered for download.

### 9.1 Components
- `app/doc_templates/tcn.docx` — Word file with docxtpl tags; contains all
  formatting: Flowserve logo, title "Test Change Notice", header/footer,
  fonts, table layout (based on TCN001.pdf). Editable in Word; tags
  documented in `app/doc_templates/README.md`.
- `documents/tcn_context.py` — `build_tcn_context(tcn) -> dict`: the only
  place that knows labels, units, NA rule, column sets. Returns **plain
  strings/lists** so the template has no logic beyond loops.
- `documents/render.py` — `render_pdf(template, context) -> bytes`, used by
  preview and issue: `render_docx` (docxtpl, internal) followed by
- `documents/pdf.py` — `docx_to_pdf(docx) -> bytes`: LibreOffice headless
  (`soffice --convert-to pdf`) in a separate process with a temporary
  profile and a timeout (`TESTLAB_SOFFICE`, `TESTLAB_PDF_TIMEOUT`); any
  failure raises `PdfConversionError`. `manage.py check` warns when
  LibreOffice is not found (testlab.W001). No Microsoft Office involved.
- Template location configurable (`TESTLAB_TEMPLATE_DIR`); SHA-256 of the
  Word template file stored with every issued TCN (`template_sha256`),
  besides the SHA-256 of the issued PDF.

### 9.2 Context (shape)
```
project_no, tcn_no ("001" or "001 rev 1"), is_draft,
project_description,
run_description_lines: [{text, level}],
reference_drawing,
seal_columns: [{heading, seal_type_size, stationary_face, rotating_face, springs}],   # 1–3
test_unit, duration ("min 75 hours"), speed ("2980 rpm"),
condition_columns: [{heading, medium, pressure, inlet_temperature, flow}],            # 1–2
prepared_by, created_date ("16-Jun-2026")
```
Seal and condition tables use docxtpl column loops (`{%tc for … %}`), so
2- and 3-column seal tables come from one template.

### 9.3 Formatting rules (in `build_tcn_context`)
- Process column: empty → `NA`; otherwise value + unit.
- Seal-support column: empty → blank; otherwise value + unit. Always
  present for dual; for single only when any seal_support value is filled.
- Units: pressure `" barg"`, temperature `"°C"` (no space, as TCN001.pdf),
  flow `" l/min"`, duration `" hours"`, speed `" rpm"`; only when non-empty.
- Run description: each line becomes one paragraph; characters kept
  literally (•, -); leading whitespace → indent level (0: none, 1: 1–4
  spaces or a tab, 2: more) using three paragraph styles in the template.
- Date format `dd-Mmm-yyyy` (§15 Q-D).
- Draft preview: a PDF opened in the browser, header shows "DRAFT — not
  issued"; preview files are not stored.

### 9.4 Issue
Render the PDF → store under `<FILE_ROOT>/projects/<project_no>/tcn/<file name>`
(refuse if the file exists) → verify the stored bytes → store SHA-256 of the
stored PDF and of the template, the context as `issued_snapshot` → commit.
A failed conversion stops the issue before anything is stored; any later
failure removes the written file; the TCN stays draft. Download of an
issued TCN always serves the stored PDF (only a stored `.pdf` is served).

### 9.5 Test Data Sheet (XLSX, openpyxl)
Generated on request for any TCN; not archived (blank form).
Header rows 1–5 per E15; row 6 headers: Date · Time · Running Hours ·
By · Torque [Nm] · monitored columns (§5.4) · Notes (merged to column Z
when space remains); rows 7–100 formulas E13/E14; formula cells locked,
sheet protected without password; file name `<project_no>-TCN001-TestDataSheet.xlsx`.

## 10. Validation rules

| # | Rule | When |
|---|---|---|
| V1 | project_no required, trimmed, upper-cased, ≤ 20 chars, unique (case-insensitive); only letters, digits, `-`, `_`, `.` (used in file names). Not matching `TESTLAB_PROJECT_NO_PATTERN` (default `^\d{4}RSD\d{2}TL$`) gives a **warning only**, never blocks | save project |
| V2 | project_no cannot be changed once any TCN of the project has been issued (issued_at set, whatever its later status). Draft TCNs/TestRuns do not lock it. Enforced in the project form and model validation | save project |
| V3 | project description required, ≤ 200 chars | save project |
| V4 | run_no integer 1–999, unique in project (message "Run number already used!") | create TCN |
| V5 | arrangement ∈ 3 values; positions exactly per §5.1 | every save |
| V6 | process_* values empty when plug_seal_present = false — the process conditions are established with the Plug Seal (seal_support_* are allowed for every arrangement). Model validation + DB check constraint | every save |
| V7 | monitored_parameters ⊆ applicable codes; stored in canonical order | every save |
| V8 | text values trimmed; max lengths per §1; a trailing unit repeating the printed unit is removed and the user informed (`70 barg`→`70`, `40°C`→`40`, `2980 rpm`→`2980`, `min 75 hours`→`min 75`; case-insensitive; also `bar g`, `C`, `h`, `hrs`) | every save |
| V9 | only drafts editable/deletable; model-level guard | always |
| V10 | row_version must match on save, otherwise "changed by <user> at <time> — reload" | save draft |
| V11 | issue requires: project_description, prepared_by, run_description, test_unit, seal_type_size for every applicable position; process_medium when plug_seal_present; revision_reason when revision ≥ 1 | issue |
| V12 | one draft and one issued revision per run (DB constraints) | always |
| V13 | new revision only from current issued revision, no existing draft, run not cancelled | new revision |
| V14 | cancel requires reason; only current issued revision | cancel |
| V15 | issued file path must not exist before writing | issue |
| V16 | arrangement single ⇒ plug_seal_present (a single seal cannot be tested alone). The form sets it; model validation + DB check constraint | every save |

Everything else (e.g. "TBD", "60 - 40", "Approx. 35-50") is accepted as text.

## 11. Acceptance / regression tests

Automated (pytest) unless marked **manual**. Reference files are read, never modified.

| # | Test | Pass criteria |
|---|---|---|
| AT-1 | *(withdrawn — legacy import moved out of M1, §12)* | – |
| AT-2 | **TCN001 regression** — 2026RSD03TL TCN001 entered through the services from a test fixture transcribing the workbook DataBase row, then rendered | Text of the rendered Word template (python-docx extraction, whitespace-normalised — the layout source of the PDF) equals fixture `tcn001_expected.txt` transcribed from `reference/tcn/TCN001.pdf`, except the documented differences: date `16-Jun-2026` vs `6/16/2026`; paper size (§15 Q-C). Key strings: "Project No.: 2026RSD03TL", "Run/TCN No.: 001", "ADNOC BAB UHTW/UHTW 4.750/4.750", "F00321662 / D0527190-2 revB", "Inboard Seal", "Outboard Seal", "C100603035 (SL WAVY)", "668838NL (10)", "min 75 hours", "2980 rpm", "Process Fluid", "Barrier Fluid", "NA", "70 barg", "60°C", "TBD l/min", "Prepared by: MG". The real PDF conversion is checked for the key strings separately (tests marked `libreoffice`) |
| AT-3 | Single + Plug Seal regression — 2025RSD02TL TCN001 from a fixture (product temperature typed as `40°C`, as in the workbook) | headings "Plug Seal" / "Test Seal"; plug: DHTW 4.750, C0625623AP, C0625624SL - WAVY, 668818NL (18); test: …, 668818NL (16); "Process Fluid" column (the Plug Seal operating conditions, Excel "Product"): Water / 80 barg / **40°C** (not "40°C°C") / TBD l/min; no Flush column (seal-support empty); no Plug Seal Fluid column; "50 hours"; "1100 rpm" |
| AT-4 | **M1 success criteria 1–10** on a new project `2099RSD01TL` | project + defaults created; TCN001 from defaults; plug seal toggled; conditions & instructions entered; PDF previewed; issued; TCN002 copied; one field changed; TCN002 issued; TCN001 record, file SHA-256 and snapshot unchanged |
| AT-5 | Re-create 2026RSD03TL TCN002–004 by copying (fresh project) | only these edits needed: 002 ← 001: run description; 003 ← 002: run description, prepared by MT, IB/OB stationary & rotating faces (C0618722SL, C0619339SL, C0618722SL, C0618723SL); 004 ← 003: run description, barrier temp `60 - 40`. Each result equals the workbook row; diff markers show exactly those fields |
| AT-6 | Immutability | editing an issued TCN via form, ORM save and delete all fail; file unchanged |
| AT-7 | Revision | rev 1 of TCN002 needs a reason; after issue rev 0 = superseded, rev 1 = issued, header "002 rev 1", both PDFs downloadable |
| AT-8 | Project defaults edit | after TCN001/002 exist, changing defaults alters no TCN (draft or issued); a new TCN from defaults uses the new values |
| AT-9 | Arrangement switching | dual → single with IB/OB data requires discard confirmation; afterwards positions = Plug + Test (Plug Seal installed automatically, V16), **seal-support values unchanged** and labelled Flush, IB/OB codes removed; single → dual keeps the Plug Seal: Plug, Inboard, Outboard; removing the Plug Seal with process conditions filled requires confirmation and empties process_* |
| AT-10 | Validation | `4` → 004; duplicate rejected with "Run number already used!"; duplicate project_no (any case) rejected; `2099-TEST` saved with a format warning; `A/B` rejected; unit stripping cases of V8 |
| AT-11 | Test Data Sheet | for 2026RSD03TL TCN001 flags: columns Date, Time, Running Hours, By, Torque [Nm], Barrier Pressure [barg], Barrier Inlet Temp. [°C], Barrier Outlet Temp. [°C], Barrier Flow [l/min], IB Face Temp. [°C], IB Leakage [ml], Over [hours], IB Leakage Rate [ml/hr], OB Face Temp. [°C], OB Leakage [ml], Over [hours], OB Leakage Rate [ml/hr], Notes. With the first rows of the 2023 TCN001 manual log typed in (08:09, 08:24, 09:36 with OB 15 ml) LibreOffice-recalculated values give running hours 1.45 and Over 1.20, rate 12.50 at 09:36 |
| AT-12 | **manual** — PO timing | creating TCN005 for 2026RSD03TL by copy is no slower than in Excel |
| AT-13 | PostgreSQL | full suite passes with `TESTLAB_DATABASE_URL` pointing to PostgreSQL |
| AT-14 | Concurrency | two sessions edit the same draft; second save refused (V10) |
| AT-15 | Access | anonymous requests redirect to login |
| AT-16 | Plug Seal conditions | dual pressurized + Plug Seal with distinct process and barrier medium/pressure/temperature/flow: the document shows two condition columns (Process Fluid, Barrier Fluid) with each circuit's own values and no Plug Seal Fluid column, one speed; issue without process_medium refused (V11) |
| AT-18 | Controlled PDF (§17 S1) | preview returns a PDF; issue stores a PDF whose SHA-256 matches the stored bytes; download returns the stored PDF; no DOCX stored or served; failed conversion leaves the TCN draft with nothing stored; superseded and cancelled revisions keep serving their own PDF |
| AT-19 | Registration and approval (§17 S2) | Login \| Register; allowed domain(s) only, case-insensitive, server-side; external address rejected with a clear message and no account; account inactive until approved in Django admin; then login with the email address; bootstrap superuser still works |
| AT-17 | Project number lock | project_no editable while only draft TCNs exist; after TCN001 is issued the form field is read-only and a model-level change is rejected; still locked after that TCN is superseded or cancelled |

## 12. Legacy import — **not in M1** (PO, round 2)

No historical migration is implemented in M1. The data model is first
validated on real new projects; migration tooling is specified and built
afterwards. The mapping below is kept only as input for that later work
and is not an M1 requirement (it would add `source_kind = legacy_import`
and a `legacy_source` field). Additional point for later: legacy rows carry
no separate Plug Seal conditions (Product = process conditions, see the mapping), and legacy 2026RSD03TL rows mention a plug seal in
text without plug data (08-D4).

Draft mapping (`manage.py import_legacy_tcn <xlsm> [--dry-run]`). Source: hidden sheet `DataBase`, table rows 2..n, columns A–AM, CK.

| Excel | TestLab |
|---|---|
| ProjNo | Project.project_no (created if missing) |
| ProjName | Project.description (from the highest run no.) and TcnRevision.project_description |
| RunNo (`"004"`) | TestRun.run_no = 4 |
| Arrangement 1 | single (Plug Seal required); IB* columns → Plug position, OB* columns → Test position; Product* → process_* (the Plug Seal operating conditions); IB/OB face temp & leak flags → plug_/test_ codes |
| Arrangement 2 / 3 | dual_unpressurized / dual_pressurized, no plug; IB*→inboard, OB*→outboard; Product* must be empty (no process conditions without Plug Seal) |
| TestRunDescription, TestUnit, Speed, Duration, RefDwg | RunSetup fields |
| IB/OB SealType, StatFace, RotFace, Spring | SealPosition fields |
| Product, ProdPress, ProdTemp, ProdFlow | process_* |
| Bar/Buf, Bar/BufPress, Bar/BufTemp, Bar/BufFlow | seal_support_* |
| 12 Y/N flags | monitored_parameters |
| By | prepared_by |
| TCNCreate | created_date; issued_at (date, 00:00) |
| – | status issued, revision 0, source_kind legacy_import, legacy_source, issued_by null |

Conversions: numbers → text without trailing `.0` (70.0 → `70`); empty
string → blank; V8 unit stripping (`40°C` → `40`). Issued PDFs for imported
TCNs is generated during import with the M1 template and flagged in
`issued_snapshot.meta.regenerated_from_legacy = true` (the original Excel
printouts remain the historical record). Project default setup = copy of
the highest imported run's setup. Result columns (AN–CJ) are empty and
ignored.

## 13. Repository structure

```
testlab/
├── CLAUDE.md  Projectprompt.md  answers_n1.md  answers_n2.md
├── README.md                    how to run, configure, test
├── pyproject.toml               django, docxtpl, openpyxl, dj-database-url, pytest-django, pypdf (dev); psycopg (optional "postgres" extra); LibreOffice as a system dependency
├── .gitignore                   data/, .venv/, __pycache__/
├── app/
│   ├── manage.py
│   ├── config/                  settings.py (env-driven), urls.py, wsgi.py
│   ├── testlab/
│   │   ├── projects/            models (Project, RunSetup, SealPosition), arrangements.py
│   │   │                        (§5 tables), forms, views, templates/, tests/
│   │   ├── tcn/                 models (TestRun, TcnRevision), services.py (create, copy, issue,
│   │   │                        revise, cancel, delete), diff.py, forms, views, templates/, tests/
│   │   ├── accounts/            registration, email login backend, user admin (approval) (§17 S2)
│   │   ├── documents/           tcn_context.py, render.py, pdf.py, checks.py, test_data_sheet.py, tests/
│   │   └── templates/           base.html, registration/login.html
│   ├── doc_templates/           tcn.docx, README.md (tag reference)
│   └── tests/fixtures/          tcn001_expected.txt
├── data/                        local dev only (git-ignored): SQLite file, file storage
├── docs/requirements/
└── reference/                   read-only source documents
```

## 14. Implementation sequence (small, reviewable commits)

| # | Commit | Contains | Verifiable by |
|---|---|---|---|
| 1 | Project skeleton | pyproject, Django project in `app/`, env settings (`TESTLAB_DATABASE_URL`, SQLite default in `data/`), login/logout, base layout, pytest setup | AT-15 |
| 2 | Project model & screens | Project + list/create/edit (S2, S3), V1, V3 (V2 lock wired in commit 9, when issuing exists) | tests |
| 3 | Run setup model & arrangement rules | RunSetup, SealPosition, `arrangements.py` (§5 tables), V5–V8 unit tests | tests |
| 4 | Project defaults form | shared run setup form, switching with discard confirmation (S5) | AT-9 (defaults) |
| 5 | TestRun/TcnRevision models | models, constraints, immutability guard | AT-6 (model part) |
| 6 | Create & copy TCN | services, S4 register, S6, S7 edit, optimistic locking | AT-8, AT-14 |
| 7 | Differences vs source | diff.py + markers in S7/S8 | AT-5 (diff part) |
| 8 | TCN Word template & preview | tcn.docx, tcn_context, render, Preview DOCX (PDF since §17) | AT-2, AT-3, AT-16 (document part) |
| 9 | Issue & lock | S8, S9, storage, hashes, snapshot, download; project-number lock (V2) | AT-4, AT-6, AT-17 |
| 10 | Revisions, cancel, delete draft | S9 actions, S10 | AT-7 |
| 10a | Stabilization (§17) | controlled PDF, registration + approval, authorization groundwork | AT-18, AT-19 |
| 11 | Test Data Sheet | XLSX export | AT-11 |
| 12 | PostgreSQL & deployment notes | PostgreSQL run of the suite, backup/restore notes, server run instructions | AT-13 |
| 13 | PO acceptance checklist | manual test script for AT-4/AT-5/AT-12 | PO sign-off |

Plug Seal conditions and the project-number lock are part of commits 2–9
(model in 3, form in 4, lock in 2 + 9, document in 8); tests AT-16/AT-17.
The Process Conditions / Plug Seal domain correction (§5) followed as one
separate commit after M1 hands-on testing.

## 15. Remaining questions

None of these block the start of M1; each has a default that M1 will use
unless the PO decides otherwise.

| # | Question | M1 default | DB impact if changed |
|---|---|---|---|
| Q-A | ~~Plug Seal conditions on the TCN?~~ **Resolved (PO round 2), corrected 2026-09-30:** yes — they are the Process Conditions (§1.2, §5); no separate plug group; speed common | – | – |
| Q-B | Label of the single-seal support circuit: "Flush" (generic; the plan, e.g. Plan 23, goes in the run description)? | "Flush" | none (label only) |
| Q-C | Paper size A4 or US Letter (TCN001.pdf is Letter via Print to PDF)? | A4 | none |
| Q-D | Date format on TCN (`16-Jun-2026` vs `6/16/2026`)? | `16-Jun-2026` | none |
| Q-E | Show revision in header as "001 rev 1"? | yes, only for rev ≥ 1 | none |
| Q-F | ~~Legacy import of plug-seal-less 2026RSD03TL rows~~ — moved with the importer to post-M1 | – | – |
| Q-G | ~~Project number pattern enforced?~~ **Resolved (PO round 2):** convention/warning only; uniqueness mandatory | – | – |
| Q-H | Multi-phase conditions (TCN004 "60 - 40") as text in M1; structured steps from M2/M3? | text | additive (new table) |
| Q-I | Server platform for production (Linux/Windows) and PostgreSQL availability | needed before deployment, not before development | none |
| Q-J | Set-ups with more than one seal-support circuit (e.g. Plan 11 on the inboard seal + Plan 53 barrier) or a Plug Seal's own support system | one seal-support circuit + Process Conditions; extra circuits in run description | additive |
| Q-K | ~~Plug Seal circuit monitored parameters?~~ **Resolved (PO round 3), corrected 2026-09-30:** the DCS/LabVIEW values are the process codes process_pressure, process_inlet_temp, process_flow (§5.4) | – | – |

## 16. Readiness statement

**M1 is sufficiently specified to begin implementation.**

No open decision blocks the database design. The open points that would
change the schema only add to it without breaking it:
- **Q-H**, structured condition steps, would add a table in M2/M3; M1's text values stay valid.
- **Q-J**, further support circuits, would add fields or a small circuit table.
- The post-M1 legacy importer adds a `source_kind` value and a `legacy_source` field.

Everything else in §15 affects labels, layout or deployment only.

## 17. Post-Commit-10 stabilization decisions (PO, 2026-09-29)

Approved after Commit 10, from hands-on testing and the intended corporate
environment. The TCN lifecycle (draft → issue → revision / supersede /
cancel) is unchanged.

**S1 — The controlled TCN document is a PDF.** An issued TCN is a
controlled instruction, not to be edited outside TestLab. Therefore:
- Preview PDF (drafts, marked "DRAFT — not issued", not stored) and
  Download issued PDF; no DOCX is offered anywhere in the application.
- The issued artifact stored at issue is the PDF; `issued_document_sha256`
  is the SHA-256 of the stored PDF. The Word template stays the layout
  source (`template_sha256` still identifies it); the rendered DOCX exists
  only temporarily during the conversion.
- Conversion: LibreOffice headless on the server (Linux production; Windows
  development supported with a normal LibreOffice install). No Microsoft
  Word automation, no Microsoft Office requirement.
- Fail-safe: a TCN becomes issued only when the PDF was generated and
  stored; on any failure the TCN stays draft and nothing is kept.
- Revision, supersede, cancel and historical downloads work as before,
  each revision serving its own stored PDF.
- Model fields keep their names (`issued_document`, `issued_document_sha256`)
  — they are format-neutral; no schema migration was needed. The
  development database held no issued TCNs, so no DOCX record exists; a
  stored non-PDF would not be served.
- This decision covers the TCN. Other generated documents (Test Program,
  Summary, Report) are decided when their milestones are specified; the
  "upload final edited DOCX" idea of 06 §4 does not apply to TCNs.

**S2 — Registration with administrator approval.** `createsuperuser` is for
bootstrap only. The login page offers "Log in | Register":
- Register collects first name, last name, corporate email address,
  password and confirmation (Django password validators). The email
  address (lower-case) is the login identity; it is stored as both username
  and email of Django's standard User model, so no custom user model or
  authentication-model rewrite was needed. Bootstrap/admin-made accounts
  may still log in with their username.
- Only addresses of the domains in `TESTLAB_ALLOWED_EMAIL_DOMAINS`
  (comma-separated, e.g. `example.com`; several allowed) may register —
  exact domain match, case-insensitive, checked server-side; no domain is
  hard-coded. Other addresses get a clear message and no account is
  created. With no domain configured, registration is closed.
- New accounts are inactive ("awaiting administrator approval") until an
  administrator activates them in Django admin (action "Approve selected
  accounts", filter "Awaiting approval", or the Active checkbox).

**S3 — Authorization groundwork.** No role system in M1: every active user
may issue and cancel (§4). The checks for these controlled actions are made
in one module (`tcn/permissions.py`), so ordinary engineers, users allowed
to issue controlled TCNs, and administrators can be distinguished later
(e.g. with Django groups/permissions) without changing views, services or
the domain model.

**S4 — Corporate SSO is future work.** Microsoft Entra ID / LDAP / SSO is
not implemented. It can replace or augment local authentication later as
a Django authentication backend; the TestRun/TCN domain refers to users
only through foreign keys (created_by, issued_by, cancelled_by, …) and
does not change.

**S5 — Scope.** Further usability findings from testing are collected
separately and are not part of this change.

# 07 — Existing Excel/VBA TCN Generator: What to Preserve (task 9)

File: `reference/Testlab Data Program 2026RSD06TL.xlsm` — "TESTLAB DATA PROGRAM V1.01.006".
Analysed: all sheets (Main, DataBase, Input, Results, TCN, Summary,
Test Data Sheet, Blad1) and all VBA modules (Module1–4).

## 1. What the tool does

| Main menu button | VBA | Behaviour |
|---|---|---|
| Add new test project and/or run | `Knop2_Klikken` → `Knop12_Klikken` | Clears Input form; saves one row into the DataBase table (inserted at top); stamps `TCNCreate` = today |
| Modify / delete / copy existing run | `Knop3_Klikken`, `Knop13_Klikken`, `Button15_Click` | Loads selected run into Input form. Save = **overwrite** row. Changing Run No. then "Add" = **copy to new run**. Delete = removes row (no history) |
| Add test results to existing run | `Knop4_Klikken`, `Results_Knop8_Klikken` | Results form: summary text, face conditions, actual process/barrier values, IB/OB leakage, face temp, wear rate, pre/post waviness/taper/Ra per face, photo file paths |
| Print TCN form | `Knop5_Klikken` | TCN sheet print preview; header "Project No. / Run/TCN No.", footer "Prepared by", "Created: <TCNCreate>" |
| Print test results form | `Knop7_Klikken` | Summary sheet with 4 photos inserted from stored file paths |
| Create test data sheet | `Knop6_Klikken` | Copies template sheet into a **new workbook** named `TCN<run>`; builds column headers from the Y/N parameter flags; adds leakage interval & rate formulas; protects sheet |

## 2. Data captured per run (89 columns, one flat row)

Identity: ProjNo, RunNo, ProjName, TestRunDescription, TestUnit, Speed, By,
RefDwg, Duration, Arrangement, TCNCreate.
Seal: IB/OB SealType, StatFace, RotFace, Spring.
Conditions: Product, ProdPress, ProdTemp, ProdFlow; Bar/Buf medium, press, temp, flow.
Log selection (Y/N): ProdPress, PInletTemp, POutletTemp, ProdFlow, BPress,
BInletTemp, BOutletTemp, BFlow, IBFaceTemp, IBLeak, OBFaceTemp, OBLeak.
Results: TestResultsSummary, 4 face conditions, actual process/barrier
press/in/out temp/flow, IB/OB SealLeak, FaceTemp, WearRate,
pre/post Wavy/Taper/Ra × {IB,OB} × {Stat,Rot}, SumBy, TestDuration, 4 photo paths.

## 3. Logic that must be preserved

| # | Rule | Where in Excel | TestLab equivalent |
|---|---|---|---|
| 1 | Run number is zero-padded to 3 digits ("1" → "001") | `Input!EC2` | run_no formatting |
| 2 | Project+Run must be unique ("Run number already used!") | `Input!EC4`, `Knop12` | unique constraint |
| 3 | Project no. and Run no. mandatory | `Knop12` | validation |
| 4 | **Copy previous run as starting point** | Modify → change run no. → Add | "New TCN from previous" (default) |
| 5 | **Arrangement switch** 1 = single seal with plug seal, 2 = dual unpressurized (buffer), 3 = dual pressurized (barrier); default 3 | `FA2`, option buttons | **Mapped per PO decision:** Excel 1 → `single` + `has_plug_seal = true` (Excel IB columns → Plug seal, OB columns → Test seal); 2 → `dual_unpressurized`, no plug; 3 → `dual_pressurized`, no plug. Plug seal on dual arrangements was not representable in Excel and is new in TestLab. |
| 6 | Labels depend on arrangement: 1 → "Plug Seal / Test Seal", "PS/TS"; 2/3 → "Inboard/Outboard Seal"; circuit → none / "Buffer" / "Barrier"; results for arrangement 1 use "Plan 23 Pressure/Flush In/Out/Flow" | label formulas on Input, TCN, Results, Summary, log sheet | label mapping table driven by arrangement |
| 7 | Arrangement 1: barrier/buffer fields cleared & greyed | `Keuzerondje16` | hide/disable circuit |
| 8 | Empty process values print as **"NA"** on the TCN; units appended only when a value exists (barg, °C, l/min, hours, rpm) | TCN sheet formulas | template formatting rule |
| 9 | Y/N parameter flags decide which columns the manual log sheet has, in fixed order: Process P, Process In T, Process Out T, Process Flow, Barrier/Buffer P, In T, Out T, Flow, IB face T, IB leakage (+ Over h + rate), OB face T, OB leakage (+ Over h + rate), then Notes | `Knop6` | monitored-parameter selection on the TCN + log sheet export (M1), log grid (M2) |
| 10 | **Running hours** = (date+time − first reading date+time) × 24 | Test Data Sheet col C | calc module |
| 11 | **Leakage entered as ml since previous reading**; "Over [hours]" = running hours − previous running hours; **rate [ml/hr] = ml / hours** (0 if error) | `Knop6` formulas | calc module (plus cumulative & average, which Excel did not do) |
| 12 | TCN "Created" date is set once at creation, not on modify | `CK` / `HK` | created_date immutable; issued_date separate |
| 13 | Log sheet header carries project, run, description, rig, speed, product/barrier medium, IB/OB seal type & faces; torque before start-up / after 10 min / after stop / after 10 min | Test Data Sheet | log sheet header + TorqueMeasurement |
| 14 | Prepared-by as initials (MG, MT) | `By` | Person catalogue with initials |

The TCN printed layout (TCN001.pdf) is the target layout for the TCN template:
header (Project No., Run/TCN No.), Project Description, Test Run Description
(bullets), Seal Information (reference drawing; IB/OB columns: type & size,
stationary face, rotating face, springs), Test Conditions (test unit,
duration, speed; Process/Barrier columns: medium, pressure, inlet temperature,
flow), footer (Prepared by, Created).

## 4. Weaknesses not to carry over

| Weakness | Evidence |
|---|---|
| Workbook copied per project, not central | File named 2026RSD06TL holds 2026RSD03TL and 2025RSD02TL rows, none for 2026RSD06TL |
| Modify overwrites, delete is permanent, no revision | `Knop13`, `Button15` |
| Photos stored as local file paths | `Results_Knop13..16` |
| Log sheet created as separate workbook, not linked back | `Knop6` `.Move` |
| Only IB/OB two positions, one spring field, no sleeve/gasket | column set |
| Only one value per condition (no steps) — run 004 stores "60 - 40" as text | DataBase row 2 |
| Rotation, rig-specific notes, deviations only in free text | run 002 description |
| Results part unused in practice | all result columns empty in current workbook |
| Label bug: Summary sheet OB column titled "Inboard Seal" (`Summary!J14`, `J23`) | formula |
| VBA bug: results shading reads `Range("BO3")` (empty) instead of arrangement `FA2` | `Knop4_Klikken` |
| Leakage "total in the glass" column in the actual logs always 0 | 2023 manual logs |

## 5. Migration

The existing DataBase rows (5 runs) can be imported once into TestLab
to test the TCN template against TCN001.pdf (acceptance test for milestone 1).

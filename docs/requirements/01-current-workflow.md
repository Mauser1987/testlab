# 01 — Current Workflow (Deliverable A)

## 1. Source documents examined

| # | File | Type | Project | Notes |
|---|---|---|---|---|
| 1 | `test-programs/2017RSD10TL- Saipem Seal Test Program.docx` | Test Program | 2017RSD10TL | Single seal UMPW, Plan 54, 2 dynamic tests, carbon face wear-rate criterion |
| 2 | `test-programs/2017RSD11TP REV 4 Qualification Test Program.docx` | Test Program (rev 4) | 2017RSD11TL | Nuclear qualification (EDF/HPC). 5 revisions, reference list, **multi-phase test table** (hydrostatic, running-in, characterization, endurance, thermal shock), >1000 h |
| 3 | `test-programs/2026RSD03TL-Test Program BAB (3).docx` | Test Program | 2026RSD03TL | Created by copying the 2023RSD08TL program — still contains 2023 project no. and dates (see 08-edge-cases) |
| 4 | `test-programs/2026RSD06TL-Test Program Celeros.docx` | Test Program | 2026RSD06TL | Current template; placeholders "xxxxx" for drawings; header still says 2026RSD03TL |
| 5 | `Testlab Data Program 2026RSD06TL.xlsm` | Excel/VBA TCN generator V1.01.006 | contains 2026RSD03TL runs 001–004 and 2025RSD02TL run 001 | See 07-excel-vba-legacy.md |
| 6 | `tcn/TCN001.pdf` | TCN form (printed from Excel) | 2026RSD03TL run 001 | 1 page |
| 7 | `summaries/Test Summary - TCN001..004.docx` (+ PDFs for 001, 002) | Dynamic Test Run Summary | 2023RSD08TL | 5 pages each, identical structure |
| 8 | `reports/2023RSD08TL-Test Report.docx` | Customer Test Report | 2023RSD08TL | Assembles the four summaries + intro, executive summary, field/test conditions, appendices |

Note: the TCNs for 2023RSD08TL and summaries for 2026RSD03TL are not in the
reference set, so the **TCN → Summary link is inferred** across two related
projects (both ADNOC BAB UHTW/UHTW 4.750, same pump application).
`reference/Test_PLM/` is empty.

## 2. The workflow as the documents show it

```
PROJECT (number YYYYRSDnnTL assigned; customer, order, seal known)
   │
   ▼
TEST PROGRAM  (Word; copied from the previous similar program and edited)
   │   cover block: customer, ultimate user, customer ref, pump manufacturer,
   │                test project no., seal type/size, order no.
   │   revision table, TOC
   │   1 Introduction (history, RCA, reason for test)          — free text
   │   2 Objective + acceptance criteria                        — free text/list
   │   3 Field conditions (site)                               — key : value list
   │   4 Test conditions (lab)                                 — key : value list
   │   5 Test seal configuration (IB/OB faces + materials)     — key : value list
   │   6 Test set-up (rig, motor, rotation, alignment std)     — boilerplate + values
   │   7 Procedure: pre-test / dynamic tests (planned runs) /
   │     planning dates / monitoring lists / post-test / reporting — boilerplate + values
   │   Appendices: seal assembly dwg, tester assembly dwg, system dwg, P&ID — images
   ▼
TCN per run  (Excel/VBA "Testlab Data Program" → printed/PDF form)
   │   Project no., Run/TCN no., project description,
   │   test run description (bulleted instructions),
   │   reference drawing, IB/OB (or Plug/Test) seal type, stationary face,
   │   rotating face, springs, test unit, duration, speed,
   │   process & barrier/buffer medium / pressure / inlet temp / flow,
   │   prepared by, created date
   │   + (hidden) which parameters are to be logged → generates a Test Data Sheet
   ▼
TEST EXECUTION on rig (A, B, 4 …)
   │   DAQ/DCS logs every 5 min (tags T04 LBI, T05 LBO, T06–T09, X22, X24,
   │   motor speed, torque) → exported, plotted in Excel
   │   Manual log (Excel "Test Data Sheet" TCNxxx): date/time, running hours,
   │   by, rpm, torque, flow, seal press, LBI/LBO temp, OB/IB leakage per
   │   interval → interval leakage rate
   │   Pre/post: break-out torque (0 and 10 min), face flatness, waviness,
   │   taper, Ra, profile, face height (carbon/SiC30), photographs
   ▼
TEST SUMMARY per run  (Word "Dynamic Test Run Summary", copied from previous summary)
   │   Introduction (identical in every summary of the project)
   │   "Test N°x – (start – end date)" + purpose paragraph
   │   Seal configuration table: part, part drawing, material, face condition
   │     ("New" / "From Test 01")  + cross-section image
   │   Test Conditions & Results table (duration, speed, fluid, pressure,
   │     inlet/outlet temp, IB/OB avg leakage, flow) + tester drawing + rig photo
   │   Logged data: DCS plot (image) + observation text + accumulated leakage plot
   │   Manually logged data: Excel range pasted as picture
   │   Measurement results: total run time, total leakage, leakage rate IB/OB
   │   Post-test pictures IB/OB rotor/stator with "Ra" caption (values empty)
   │   Test conclusion (free text)
   ▼
FINAL TEST REPORT  (Word, same template family as Test Program)
       cover block (same as program) + report no. 2023RSD08TLR
       1 Introduction (program intro, edited)
       2 Executive summary: free text + summary table (Excel range pasted as picture)
       3 Field conditions (program §3, edited: "70 barG and 113 barg")
       4 Test conditions (program §4, edited)
       5 Test results: 5.1…5.n = each Test Summary pasted (minus header),
         some text corrected during pasting
       Appendices I–IV: same drawings/P&ID as the program
```

## 3. What each stage really represents

| Stage | Meaning | Written when | Who |
|---|---|---|---|
| Project | Commercial/engineering container: customer, order, seal, application | Before anything | Test engineer |
| Test Program | **Planned** campaign, often customer-facing & customer-approved | Before testing | Test engineer, approver |
| TCN | **Instructed** run: what the technicians shall build and run | Before each run | Test engineer ("Prepared by: MG/MT") |
| Test execution | Rig operation, logs | During run | Technicians ("By: Rob & Claude") |
| Test Summary | **Actual**: what happened, measured values, engineering observation & conclusion | After each run | Test engineer |
| Final Report | Customer deliverable combining all of the above + overall conclusion | After campaign | Test engineer, approver |

## 4. How information moves today

Today, information moves only by **copy/paste and re-typing**:

- Program → next project's Program: the whole document is copied and edited
  (the 2026RSD03TL program still carries 2023RSD08TL values; the Celeros
  program header still says 2026RSD03TL).
- Program → TCN: re-typed into Excel.
- TCN → next TCN: Excel "Modify/Copy" loads the previous run into the input
  form, the engineer changes the run number and what differs, then saves as new.
- TCN/logs → Summary: re-typed; Excel tables pasted as pictures; plots pasted as pictures.
- Summary → next Summary: whole Word file copied and edited.
- Summaries → Report: pasted into the report; corrections made *only in the
  report* (the standalone summary files keep the errors).
- Summary values → Executive summary table: re-typed in Excel, pasted as a picture.

The Excel TCN tool also contains a "Test Results" form and "Print Test
Results" summary sheet, but the 2023 summaries show that the Word summary
is what is actually produced; the Excel results columns in the current
workbook are empty for all runs.

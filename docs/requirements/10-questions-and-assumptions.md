# 10 — Risks, Questions & Assumptions (Deliverable I; task 16)

Updated after PO decisions round 1 (`/answers_n1.md`) and round 2 (`/answers_n2.md`).

## 1. Questions for the domain expert

### Resolved

| # | Question | Resolution (answers_n1) |
|---|---|---|
| Q1 | TCN for every run or only deviations? | **Every run has a TCN**, even without deviations; a TCN contains zero or more deviations. |
| Q2 | Can an issued TCN change during the run? | **No silent change.** Execution deviations → Test Result. Formal change of the instruction → **new TCN revision**; issued revision kept. |
| Q3 | Run No. = TCN No.? | **Yes for V1**: same sequential identifier within a project. |
| Q4 | Arrangements; plug seal | Arrangements: **Single, Dual Pressurized, Dual Unpressurized**. **Plug seal optional, modelled separately**, on any arrangement. No other arrangements in M1. |
| Q7 | Users / auth | Internal multi-user web app; Django built-in auth in M1; SSO later. |
| Q8 | Deployment | One centrally hosted Django app on an internal server; **PostgreSQL in production**; SQLite only for local development; configurable server-side file storage. |
| Q10 | Average leakage definition | **Average leakage rate = total leakage quantity / actual running time**, calculated. Method, intermediate readings, total, running time, average kept distinct. |
| Q14 | Approval workflow | Not overbuilt in M1. |
| Q16 | Automatic acceptance evaluation | Future scope. |
| Q17 | Physical component tracking | Future feature, not M1. |
| Q13 | DCS | Integration is future scope (details asked again when M5 starts). |
| Q6 | Project number format | RSD format is a **convention (warning only)**; uniqueness mandatory (answers_n2). |
| Q21 | Plug Seal conditions | **Yes**: explicit Plug Seal medium, pressure, temperature, flow on the TCN; speed common to the run (answers_n2). |
| Q22 | Legacy Excel import in M1? | **No**; post-M1, after validation on new projects (answers_n2). |

### Open — not blocking M1

| # | Question | Needed by |
|---|---|---|
| Q5 | Additional TCN fields beyond the Excel set (rotation, sleeve, gaskets, test assembly drawing, log interval)? M1 keeps the Excel field set; additions are simple migrations. | M1 review (optional) |
| Q9 | **Test 1 leakage IB/OB**: log & plot show OB higher; results table shows Inner higher (08-B4). Which is correct? | M2 (calculation regression) |
| Q11 | Speed 2950 (summary) vs 2900 (log) vs 2980 (TCN) — actual source? | M2 |
| Q12 | Manual log in the summary/report: full table, appendix, or attached XLSX? | M2 |
| Q15 | Record of issue DOCX or PDF; archive location (R:\PROJECTS HISTORY…)? | M1 review (default: issued DOCX stored in TestLab) |
| Q18 | Other test types (static/hydrostatic only, qualification phases)? | M2/M3 |
| Q19 | Does the TCN go to customers? | M1 review (default: internal document, same layout as today) |
| Q20 | Unit standardisation (barg, °C, l/min, ml/h …); imperial customers? | M2 |

M1-specific remaining questions are consolidated in 11-m1-specification.md §15.

## 2. Risks

| Risk | Mitigation |
|---|---|
| Engineers keep using Excel because TestLab is slower | M1 must be faster than Excel for the common case (copy previous TCN, change 2 fields, issue). Measured in acceptance test AT-12. |
| Over-structuring engineering text | Free text stays free (02 §4); structure only values that are copied, compared or calculated |
| Template fidelity | TCN template built from TCN001.pdf layout; PO signs off template |
| Historical data inconsistency blocks import (post-M1) | Import stores text as written; only unit-duplication cleanup (08-D21) |
| Data loss | PostgreSQL in production with scheduled backup; restore tested at M1 hand-over |
| Scope creep toward PLM | Milestone acceptance tests tied to real documents; CLAUDE.md rule |
| Corporate IT restrictions (Python/Linux/Windows server, PostgreSQL availability) | Confirm server platform before M1 deployment (not before development) |
| Confidential customer data | Internal hosting only, login required, no external services |

## 3. Assumptions

| # | Assumption | Status |
|---|---|---|
| AS1 | Each run has exactly one TCN number and at most one Result/Summary. | **Confirmed** (TCN may have several revisions) |
| AS2 | TCN numbering restarts at 001 per project. | **Confirmed** ("sequential identifier within a Project") |
| AS3 | Single test lab site ("RSD"); no multi-site requirements. | Assumed |
| AS4 | Small team (< ~20 users), internal network. | Assumed, consistent with PO deployment decision |
| AS5 | English document language. | Assumed |
| AS6 | Manual-log leakage reading = volume since previous reading (Excel logic). | Assumed for the Excel-style log; PO confirmed other methods exist (reservoir level drop) → method stored per seal in M2 |
| AS7 | Flowserve Word layout may be reused for TestLab templates. | Assumed |
| AS8 | The 2023 summaries correspond to TCN001–004 of 2023RSD08TL. | Assumed |
| AS9 | DCS data outside TestLab until M5; plots uploaded as images in M2. | **Confirmed** (DCS future scope) |
| AS10 | P&ID remains an uploaded image until M6. | Assumed |
| AS11 | Issued documents never regenerated silently. | **Confirmed** |
| AS12 | Approval recorded, not enforced as a workflow. | **Confirmed** (not overbuilt in M1; TCN has no approver field, as today) |
| AS13 | Project short description is editable text. | Assumed |
| AS14 | The legacy 2026RSD03TL runs (arrangement 3, no plug data) are imported without plug seal even though their text mentions a plug seal. | Deferred with the importer (post-M1) |
| AS15 | Multi-phase conditions inside one TCN (e.g. "60 - 40" °C) remain text in M1, as in Excel. | New |

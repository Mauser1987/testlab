# 02 — Information Analysis (Deliverable B; tasks 2, 3, 4, 10)

## 1. Repeated information across documents (task 2)

✔ = appears in that document type (typed again each time).

| Information | Program | TCN (Excel) | Summary | Report | Times typed per 4-run project* |
|---|:-:|:-:|:-:|:-:|:-:|
| Project number | ✔ cover, header, footer filename | ✔ | ✔ header, manual log | ✔ cover, header | ~12 |
| Customer / ultimate user / customer ref / pump manufacturer | ✔ | – | – | ✔ | 2 |
| Flowserve order no. | ✔ cover + field cond. | – | ✔ intro text | ✔ | 4+ |
| Seal type & size | ✔ cover, field, test cond., config | ✔ IB & OB, project description | ✔ manual log | ✔ | ~15 |
| Seal configuration (arrangement: dual pressurized F2F …) | ✔ ×2 | ✔ (arrangement option) | – | ✔ ×2 | ~8 |
| Material code | ✔ ×2 | – | – | ✔ ×2 | 4 |
| Face part numbers & materials | ✔ config | ✔ per run | ✔ config table + manual log header | ✔ per test | ~20 |
| Springs | – | ✔ | – | – | 4 |
| Reference / assembly drawing | ✔ several | ✔ | – | ✔ | ~8 |
| Tester drawing | ✔ | – | ✔ | ✔ | 9 |
| Test rig / unit | ✔ | ✔ | ✔ caption + manual log | ✔ | ~13 |
| Field conditions block | ✔ | – | – | ✔ (edited) | 2 |
| Test conditions (speed, pressure, fluid, temp) | ✔ | ✔ | ✔ (mix of instructed & actual) | ✔ | ~13 |
| Campaign introduction text | ✔ | – | ✔ identical in all 4 | ✔ | 6 |
| Test purpose paragraph ("First test intends to…") | – | (run description) | ✔ | ✔ | 8 |
| Monitoring parameter list | ✔ | ✔ Y/N flags | ✔ manual log headers | ✔ | – |
| Pre/post procedure bullets | ✔ | ✔ run description | – | – | 5 |
| Leakage totals & rates | – | – | ✔ ×2 per summary | ✔ ×2 per test + exec table | ~20 |
| Photos, plots, cross-section, rig photo | ✔ (appendices) | – | ✔ | ✔ | 2× each |
| Prepared by / date | ✔ | ✔ | – | ✔ | 6 |

\* Order of magnitude, counted from 2023RSD08TL + 2026RSD03TL samples.

### Automation opportunities (highest value first)

1. **Seal configuration + conditions entered once, copied forward per TCN
   with visible differences.** Removes the most typing and the most errors.
2. **Leakage calculations done by the system** from the manual log
   (interval rate, cumulative total, run time, average rate). Removes the
   three-way inconsistency seen in the samples.
3. **Executive summary table generated** from completed results (date,
   type, barrier fluid, pressure, IB/OB leakage, wear, result verdict text).
4. **Headers/footers/cover blocks filled from project data** (fixes stale
   project numbers in headers).
5. **Test Summary assembled from TCN + result data**, with only the
   engineering text written by hand.
6. **Final report assembled from selected summaries** instead of paste.
7. **Manual log tables as real Word tables** (or a generated appendix) instead
   of pictures; **plots generated from data** (later milestone).
8. **Boilerplate procedure text** (pre-test, post-test, monitoring, reporting)
   from a library with project-specific values inserted.

## 2. Which level each piece of information belongs to (task 3)

### Project level (identity, rarely changes)
- Project number (e.g. `2023RSD08TL`), project short description
  (e.g. "ADNOC BAB UHTW/UHTW 4.750/4.750" — today derived by hand)
- Customer, ultimate user (+ site), customer reference(s) (can be several:
  "11-20-P-2142-02 / …-2143-02 / …-2144-02"), pump manufacturer, pump type
- Flowserve order number(s)
- Responsible engineer(s), approver
- Related projects (2026RSD03TL re-tests 2023RSD08TL hardware — "use 2023 sleeve")
- Customer document numbers (HPC program: EDF document no.)
- **Field (site) conditions**: seal type/size, arrangement, material code,
  pump fluid, seal chamber pressure (norm/min/max), product temperature,
  barrier/buffer fluid, pressure, temperature, speed(s), API plan,
  assembly drawing, system drawing
- Attachments: drawings, P&ID, RCA references, customer specs

### Seal / configuration level (the physical build)
- Arrangement — **PO decision:** exactly Single, Dual Pressurized,
  Dual Unpressurized (face-to-face / face-to-back is descriptive detail, not a
  separate arrangement)
- **Plug Seal: modelled separately** from the arrangement; it establishes
  the process conditions. Required for Single (a single seal cannot be
  tested alone), optional for Dual Pressurized / Dual Unpressurized
  (corrected 2026-09-30; its conditions are the Process Conditions)
- Seal positions: Plug + Test seal (single) or IB & OB (dual), plus Plug seal when present
- Per position: seal type & size, stationary face (part no., balance %,
  material), rotating face (part no., material), spring(s) (part no. + qty),
  sleeve, gaskets/secondary seals, material code
- Reference drawing(s) (seal assembly) and test assembly (tester) drawing
- Rotation (CW/CCW, free end / drive end)
- Per physical face: identity marking (#1…#4, "#31"), condition (new / from
  test N / re-lapped)

A project has a **baseline configuration** (from the program). Each TCN
holds **its own configuration** (copied, then changed).

### Test Program level (planned)
- Program document no. & revision history (rev, prepared, approved,
  description, date)
- Introduction, objective, acceptance criteria (free text / list)
- Test conditions (lab), test seal configuration (baseline)
- Test set-up: rig, motor power, drawing, rotation, alignment standard
  (API 682 edition + clauses), support system description
- Procedure sections (pre-test, dynamic tests, post-test, reporting)
- **Planned tests** (1…n, or phased table): duration, product fluid,
  barrier temperature, pressure, speed, stop/starts, special notes, planned
  start date
- Monitoring: DAQ parameters + interval, manual parameters
- Appendices (seal dwg, tester dwg, system dwg, P&ID)
- References list (qualification-type programs)

### TCN / Test Run level (instructed)
- Run/TCN number (001, 002, …), created date, prepared by, status
- Link to the planned test it realises (or "additional test")
- Purpose/rationale ("Test to reproduce 2023 test results…")
- Instructions (bullets; pre-test, installation, run, stop, post-test)
- Seal configuration for this run (copy of previous/baseline + changes)
- Test unit, speed, duration, rotation
- Process and barrier/buffer circuit: medium, pressure, inlet temp, flow
- Steps/phases when conditions change inside a run (60 °C → 40 °C)
- Parameters to be logged (the Excel Y/N flags) and log interval
- Deviations from program (explicit list — "TCN = change notice")

### Result level (actual)
- Actual start / end date-time, run time (calculated from log)
- Actual conditions per parameter (typical value / range, derived from logs
  or entered)
- Manual log readings (time series)
- DCS/DAQ data files (CSV) and plots
- Break-out torque pre/post (0 min, 10 min)
- Face measurements pre/post per face: waviness, taper, Ra, profile, height
  → wear rate (carbon/SiC30)
- Leakage (PO decision — keep these distinct):
  - measurement method per seal (reservoir level drop, collected drain liquid, …)
  - individual/intermediate readings (quantity since previous reading, interval rate)
  - total accumulated leakage quantity
  - actual running time
  - **overall average leakage rate = total leakage quantity / actual running time**
    (calculated whenever both source values exist; not typed)
- Face/part condition after test, observations (free text)
- Photographs (IB/OB rotor/stator + others) with captions
- Engineering conclusion (free text), result verdict (short text)
- Prepared/approved, issue date

### Report level
- Report number (`2023RSD08TLR`), revision, prepared/approved, date
- Selection and order of results to include
- Introduction (starts from program intro, edited)
- Executive summary text + generated summary table
- Final conclusion / recommendations
- Report-specific versions of field/test conditions (report shows
  "70 barG and 113 barg" — reflects what was actually tested)
- Appendices selection

## 3. Inherit vs snapshot (task 4)

Principle in plain terms: **a document that has been issued describes the
world as it was on that day.** Changing today's data must never rewrite it.

Three mechanisms are needed:

| Mechanism | Meaning | Used for |
|---|---|---|
| **Live reference** | Child always shows the parent's current value | Project identity in *drafts* only (project number, customer, order no.) |
| **Copy-on-create (inherit)** | When the child is created, parent values are copied into the child. After that the child owns them. System remembers where each value came from and shows differences. | Seal configuration, conditions, instructions, monitoring parameters → into each TCN; TCN conditions → Result "instructed" column |
| **Freeze on issue (snapshot)** | When a record is issued/approved, it is locked. A stored snapshot of the exact data + the generated DOCX is kept. Changes require a new revision with a reason. | Issued Program revision, issued TCN, completed Result/Summary, issued Report |

Detailed rules (confirmed by PO decisions round 1; M1 detail in 11-m1-specification.md):

1. **Project identity**: the project number cannot change once any TCN
   exists; the project description is copied into each TCN when it is
   created (as the Excel tool did per run). Issued TCNs also keep a frozen
   data snapshot and the generated DOCX.
2. **Seal configuration, conditions and instructions are always copied,
   never live-linked, into a TCN.** Source for TCN001 = project defaults
   (M1) or a program planned test (from M3). Source for TCN00n = user's
   choice: previous TCN (default, matches today's Excel habit), project
   defaults, or (from M3) a planned test.
3. The TCN records its **source** (project defaults / TCN003 rev 0 / …).
   The UI highlights fields that differ from the source (M1) and from the
   program (M3) — the latter *is* the list of deviations from the program.
4. **Editing project defaults never changes any existing TCN** — draft or
   issued. Defaults only affect TCNs created afterwards. (Simplified from
   the earlier proposal to offer re-applying defaults to drafts.)
5. **Issued TCNs are never edited.** If the instruction itself must formally
   change, a new TCN revision (rev 1, 2, …) is created as a copy, edited and
   issued; the previous revision stays unchanged and becomes *superseded*.
6. **Deviations that occur during execution belong to the Test Result**,
   not to the TCN.
7. **Result** (M2) creates its "instructed" values by copying the issued TCN
   revision's values; actual values are stored separately beside them. The
   result never edits the TCN. Planned / instructed / actual always remain
   distinguishable.
8. Once a Result is **completed**, the Final Report includes a frozen version
   of it. If a Result is revised later, the report shows "newer revision
   available" and the engineer decides.
9. Physical face condition ("From Test 01"): **future feature** (component
   lifecycle tracking is not M1). Until then it is typed text.

## 4. What deliberately stays free text (task 10)

Engineering judgement and narrative stay free text. The system stores them,
reuses them as starting points, and never generates them in V1.

| Free text | Where | Why not structured |
|---|---|---|
| Introduction / background (history, RCA summary) | Program, Report | Narrative, customer-specific |
| Objective | Program | Narrative |
| Acceptance criteria | Program | Mixed units (g/h, cc/h, µm/h), per-seal/per-pair/per-cartridge, conditions ("after run-in", "at start-up may be 30 cc/hr"); qualitative ("no chipping… some contact traces can be expected"). *Numbers may be added later as optional structured fields for display next to results; no automatic pass/fail in V1.* |
| Test set-up description | Program | Rig-specific narrative (starts from boilerplate) |
| TCN instructions / run description | TCN | Bulleted, highly variable ("Reversed rotation test… allow flexible hoses knowing the flow may change") — start from a template/previous TCN |
| Test purpose paragraph | TCN / Summary | Narrative |
| Observations on logged data ("barrier temperature was too low reason for reducing the cooling water flow…") | Result | Judgement |
| Face/part condition after test | Result | Judgement; optionally a short pick-list (no damage / contact traces / chipping / …) plus text |
| Test conclusion | Result | Engineer-controlled (CLAUDE.md) |
| Result verdict ("Excellent (leakage + face conditions)") | Result | Short text used in exec table |
| Executive summary, final conclusion, recommendations | Report | Engineer-controlled |
| Notes column in manual log | Result log | Ad-hoc remarks |

Semi-structured (store text, parse numbers when possible):
condition values like `min 75`, `60 - 40`, `TBD`, `NA`, `Approx. 35-50`,
`5200/5235/5610`, `12 barG Norm, 9-98 barG`.

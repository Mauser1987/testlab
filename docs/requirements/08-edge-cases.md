# 08 — Edge Cases, Inconsistencies & Ambiguities (task 11)

These come directly from the supplied documents. They are listed not to
criticise the documents but because each one is a requirement the system
must handle (or prevent).

## A. Copy/paste drift (prevented by "enter once")

| # | Finding | Location |
|---|---|---|
| A1 | 2026RSD03TL program cover says "Flowserve Test Project: 2023RSD08TL"; planning dates Aug 2023; drawings F000904152 — values from the 2023 program | BAB program |
| A2 | BAB program intro says the fix is graphite-loaded SiC faces; §5 configuration lists reaction bonded SiC C0618722SL/C0619339SL (2023 parts); TCN001 of that project uses C100603033 (SIC30) + SL WAVY — **program configuration was never updated; the TCN is the truth** | BAB program vs TCN001 |
| A3 | Celeros program page header "Project: 2026RSD03TL"; drawings "xxxxx"/"xxxxxx"; tester drawing F000904152 copied from BAB; §7.1 says "drawing xxxxxx rev. A"; footer filename "2021RSD03TL-Test Program.docx" | Celeros program |
| A4 | Report header reads "Test Program" | 2023 report header |
| A5 | Summary TCN003: "same faces from test 01" — report version corrected to "From Test 02" in table, text still "from test 01" | Summary 003 vs report 5.3 |
| A6 | Summary TCN004: "The third test…", "exceeding 144h" for a 69.5 h run — report corrected hours to 69h but kept "third test" | Summary 004, report 5.4 |
| A7 | Standalone summaries were not updated with the corrections made in the report → two different "final" versions exist | summaries vs report |
| A8 | Report exec summary says "Total 4 tests … as per the original program"; the program (as reconstructed) lists 2 tests; 113 barg tests were added by TCN | report §2 |

## B. Numbers that disagree

| # | Finding |
|---|---|
| B1 | Test 1 IB leakage: 16.1 ml/h (conditions table), 19.7 ml/h (measurement results), 16 ml/h (exec summary table) |
| B2 | Test 4 IB leakage: 16.9 (conditions), 16.5 (measurement results; 1176 ml / 69.5 h = 16.9), 20 (exec table). OB: 25 / 25 / 26.5 (1781.7/69.5 = 25.6) |
| B3 | Test 2 IB: 2378 ml / 145.3 h = 16.4, reported 16.5 |
| B4 | **Possible IB/OB swap in Test 1**: manual log cumulative at 47 h: OB ≈ 776 ml, IB ≈ 720 ml; accumulated-leakage plot ends OB ≈ 2850 ml, IB ≈ 2150 ml; measurement table gives *Inner* 2857.6 ml, *Outer* 2164.3 ml. **Needs PO confirmation which is right.** |
| B5 | Speed: program/TCN 2980 rpm; summary 2950 rpm; manual log 2900 rpm. Unclear whether 2950 is actual, typo or VFD setting |
| B6 | Duration field in summaries mixes instructed ("Minimum 72h", "Minimum 144") and actual ("69.5 hrs"); test 1 actually ran 144.6 h |
| B7 | Manual log in summary 001 stops at 47 h but test ran 144.6 h (table truncated to a page) |
| B8 | TCN001 log 13:28 seal pressure 80.50 barg among ~70.0 values — outlier or typo; system must accept but may flag |
| B9 | "Average leakage" is defined differently in different places (total/run time vs mean of interval rates vs "after run-in"). **Resolved (PO):** average leakage rate = total leakage quantity / actual running time, calculated. |

## C. Identity & naming

| # | Finding |
|---|---|
| C1 | Part numbers written inconsistently: C0618722SL vs C618722SL; OB rotor C0618723SL (config) vs C0619323SL (manual log header) |
| C2 | Project number reused as document number (program `2026RSD03TL`), with suffix (`2017RSD11TP-rev 4`, `2017RSD10TL-01`, report `2023RSD08TLR`). Numbering rule unclear |
| C3 | "Flowserve Test Project" vs "Roosendaal Test Project" label on cover |
| C4 | Seal type spelled "UPMW" and "UMPW" in same program; "UHTW/UHTW-4.750/4.750" vs "UHTW/UHTW 4.750/4.750" |
| C5 | Units spelled barG / barg / Barg / bar(g); ml/h, ml/hr, cc/h, cc/hour; g/h in acceptance criteria (mass vs volume) |
| C6 | Physical faces identified by marking (#1…#4, "#31" on photo) but marking not recorded in configuration table |
| C7 | Project description "ADNOC BAB UHTW/UHTW 4.750/4.750" = end user + field + seal; derived by hand |

## D. Structure the model must support

| # | Finding |
|---|---|
| D1 | **TCN meaning**: "Test Program Change Notice… every deviation" (program §Reporting) vs "Run/TCN No." per run (Excel, TCN form, summaries). **Resolved (PO):** every run has a TCN (Run No. = TCN No.) with zero or more deviations. |
| D2 | **Multiple phases inside one run**: TCN004 "60 °C for 100 h then 40 °C for 100 h" (stored as "60 - 40") |
| D3 | Qualification program: phased table (hydrostatic steps 5→30 bar, running-in 2×48 h, characterization 6×96 h, endurance with 12 stop/starts, thermal shocks at given hours) and examinations between phases — one planned test ≠ one run necessarily |
| D4 | Plug seal + job/test seal set-ups; seal positions IB/OB vs Plug/Test; "DE or NDE seal", "FE seal". **Resolved (PO):** arrangement ∈ {single, dual pressurized, dual unpressurized}; plug seal optional and modelled separately. DE/NDE/FE remains descriptive text. Note: 2026RSD03TL TCNs mention "Job and plug seal" post-test work but the Excel row (arrangement 3) has no plug seal data — imported as no plug seal (see M1 spec). |
| D5 | Rotation change as a test variable (TCN002 reversed CCW→CW, LBI/LBO swapped, temporary hoses → P&ID differs for that run) |
| D6 | Re-use of hardware across runs ("same faces… without lapping") and across projects (2026 re-test uses "the 2023 sleeve"; old part code C0618730NL = current C100028091 = drawing F000893469) |
| D7 | Multiple customer references per project; multiple speeds in field conditions ("5200/5235/5610 rpm") |
| D8 | Conditions not numeric: "NA", "TBD", "To be defined", "depends on how much heat will be generated", "Approx. 55-60 °C (outlet cooler, inlet seal)" |
| D9 | Test duration conditional: "100 hours, depending on stability of performance"; "continued till stable performance is achieved" |
| D10 | Pre-test data carried over: "Pre will be post from TCN001" |
| D11 | Face height measured only for carbon/SiC30 faces → wear rate only then |
| D12 | Photo captions "Ra" are always empty in summaries — Ra values exist in the Excel design but are not filled |
| D13 | Program revisions with customer involvement (HPC rev 0–4, EDF document number) |
| D14 | Programs with a References list and customer document numbers (nuclear) vs short commercial programs |
| D15 | Monitoring lists differ per program (stationary face temp, power consumption, torque) — parameter set is per project/run, not fixed |
| D16 | Manual log header fields not in TCN: "Aligned yes", "Acquire rate s/S on 60 trigger on 5", "Cooling CTRL valve 0% is complete open", "Flow CTRL valve 100%…" |
| D17 | Log readings across weekends: 16 h and 64 h intervals (fine for rate, but plots show gaps) |
| D18 | Different barrier fluid naming: "Water", "Demi water", "Potable water", "Glycol 30/ Water 70", "MEG/Water 30/70", "70%Demi water-30%Glycol" |
| D19 | Approval: "Approved by" empty on recent programs and report. PO: approval workflow not overbuilt in M1 (TCN has "Prepared by" only, as today). |
| D21 | Legacy Excel values sometimes already include the unit (2025RSD02TL product temperature "40°C"); the Excel TCN formula appends "°C" again → "40°C°C". Import must strip a trailing unit that duplicates the field unit. |
| D22 | TCN001.pdf is US Letter, printed via "Microsoft Print to PDF"; run description is printed exactly as typed (literal "•" and "- " characters, indentation), not Word list formatting. |
| D20 | Both DOCX and PDF of summaries exist — which one is the issued record? |

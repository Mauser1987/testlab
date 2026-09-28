You are acting as the lead software architect, senior full-stack engineer, and requirements analyst for an internal engineering application called TestLab — Test Lifecycle Management.
The application is intended initially for a mechanical wet-seal test laboratory. I am a mechanical seal engineer and will act as the domain expert/product owner. You are responsible for understanding the existing workflow from the supplied real project documents and designing a practical application that replaces the current fragmented Excel/VBA/Word/manual-copy-paste process.
This is not a generic PLM system and should not become one. Keep the scope tightly focused on the actual TestLab workflow demonstrated by the supplied documents.
<source_material>
I have supplied examples of:

- Test Programs / Test Plans, including P&IDs
- An existing Excel/VBA TCN generator and its internal data
- Individual TCN documents
- Individual Test Summary reports
- A completed Final Test Report containing multiple test runs
Treat these documents as the primary requirements source.
Study them carefully before proposing architecture.
Pay particular attention to repeated information, relationships between documents, values inherited from earlier stages, values that change between individual test runs, engineering free text, tables, images, test data, measurements and document assembly.
Do not assume that the current documents represent an ideal database structure. They represent the existing engineering workflow.
</source_material>
<business_workflow>
The high-level lifecycle is:

PROJECT
→ TEST PROGRAM
→ TCN / TEST RUN INSTRUCTION
→ TEST EXECUTION
→ TEST RESULT / TEST SUMMARY
→ repeat TCN + Result as required
→ FINAL TEST REPORT
A Test Program describes the overall intended campaign.
A TCN (Test Change Notice) defines what shall actually be performed for an individual test run. Conditions, components, instructions and configurations may differ from the original Test Program and from previous TCNs.
A Test Result/Test Summary records what actually happened during that TCN: actual conditions, logged data, manually logged data, measurements, observations, photographs, plots and engineering conclusion.
The Final Test Report combines project-level information and the individual completed test summaries and adds an executive summary and final engineering conclusion.
It is important to preserve the distinction:
PROGRAM = planned campaign
TCN = instructed individual test
RESULT = what actually happened
</business_workflow>
<core_principle>
Information should be entered once and reused downstream wherever possible.

Do not reproduce the current copy/paste workflow digitally.
For example, project number, customer, seal configuration and drawings should not be independently typed into every TCN and Test Summary.
A new TCN should inherit sensible project/default information and allow overrides.
Results should inherit the corresponding TCN conditions while allowing actual values to be recorded.
The Final Report should assemble information already stored by the system rather than requiring the engineer to rebuild the report.
</core_principle>
<initial_modules>
The envisioned system contains:

Project Management
Test Program
TCN / Test Run Management
Test Results / Test Summary
Final Test Report Generator
Attachments / Engineering Documents
P&ID Builder
Dashboard / Project Overview
Future integration with an existing DCS Data Analyzer
Do not assume every module belongs in V1.
</initial_modules>
<pid>
The P&ID requirement is intentionally limited.

We do NOT need AutoCAD, Visio or a general industrial P&ID package.
TestLab uses a limited number of recurring test-loop components and symbols.
Eventually we want a simple interactive builder where an engineer can:
- select a starting template or blank canvas
- drag predefined components onto a canvas
- move and rotate components
- connect components using clean piping lines
- add labels and annotations
- save the P&ID with the project
- export PNG/SVG for automatic inclusion in Test Programs and Reports
This may be postponed until a later development phase if appropriate.
</pid>
<data>
Test results can contain:

- test start/end and runtime
- speed
- pressure
- temperature
- flow
- torque
- IB/OB leakage
- accumulated leakage
- calculated leakage rate
- manually logged measurements
- CSV/DCS logged data
- plots
- photographs
- pre/post-test measurements
- observations
- conclusions
Different tests may require different parameters, so avoid designing a rigid schema that only supports the supplied examples.
</data>
<document_generation>
TestLab must ultimately generate professional DOCX documents compatible with our existing engineering documentation style.

At minimum:
- Test Program
- TCN
- Test Summary
- Final Test Report
Generated documents should use templates rather than having document formatting scattered throughout application logic.
The engineer must remain able to edit generated DOCX documents if necessary.
</document_generation>
<constraints>
This is an internal engineering application.

Prefer a simple, maintainable architecture over enterprise complexity.
The application may initially run locally/on an internal network.
Avoid unnecessary cloud dependencies.
Do not introduce microservices unless there is a compelling reason.
Do not add AI functionality in V1.
Do not build direct test-rig control in V1.
Do not build automatic DCS acquisition in V1.
Do not attempt to reproduce a commercial PLM product.
Avoid over-engineering and hypothetical requirements.
Design around the workflow demonstrated by the supplied documents.
</constraints>
<important_design_requirement>
The architecture must support:

Project → many TCN/Test Runs
TCN → one corresponding Test Result/Summary
Project → one Test Program
Project → many attachments/drawings
Project → current P&ID + possible revisions
Final Report → selected completed Test Results
We must also be able to compare:
Planned condition → TCN instructed condition → Actual result
</important_design_requirement>
<your_first_task>
DO NOT WRITE THE APPLICATION YET.

First perform a requirements and architecture phase.
1. Examine all supplied source documents carefully.
2. Identify information repeated across Test Program → TCN → Test Summary → Final Report.
3. Identify which information belongs at:
   - Project level
   - Seal/configuration level
   - Test Program level
   - TCN/Test Run level
   - Result level
   - Report level
4. Identify fields that should inherit from parent records versus fields that should be copied/snapshotted for historical traceability.
This distinction is important: changing a Project later must not silently rewrite the historical configuration of a completed test.
5. Propose the domain/data model and relationships.
6. Identify reusable entities such as:
   - seal configuration
   - seal faces/components
   - operating/test conditions
   - test instructions
   - measurement definitions
   - attachments
   - photographs
   - plots
   - conclusions
   - revisions
7. Propose the application navigation and main screens.
8. Describe the exact workflow for:
   Create Project
   → create Test Program
   → create TCN001
   → execute test
   → enter/import results
   → generate Test Summary 001
   → create TCN002
   → etc.
   → generate Final Report.
9. Identify where the existing Excel/VBA TCN logic needs to be preserved.
10. Identify what should deliberately remain free-text because engineering judgment cannot reasonably be structured.
11. Identify edge cases and ambiguities you find in the supplied documents.
12. Divide implementation into sensible milestones.
I expect the first usable milestone to be much smaller than the complete vision.
13. Recommend a practical technology stack, explaining why it suits a locally/internal-hosted engineering application.
14. Propose a database schema at entity/relationship level. Do not yet generate hundreds of lines of SQL.
15. Propose how DOCX template generation should work.
16. Explicitly identify any assumptions you made because the supplied documents did not provide enough information.
    </your_first_task>
<working_style>
Treat me as the engineering product owner, not as a software architect.

Explain important software architecture decisions in practical engineering language.
Challenge requirements when you see a simpler solution.
Do not add features simply because they are technically interesting.
Prefer incremental development that can be tested against real TestLab work.
When information is unclear, identify the ambiguity instead of silently inventing a business rule.
Our priority is a tool engineers will actually use.
</working_style>
<deliverables>
For this first phase, produce:

A. Your understanding of the current workflow
B. Repetition/automation opportunities found in the supplied documents
C. Proposed domain model
D. Proposed application architecture
E. Proposed UI/navigation structure
F. Proposed document-generation architecture
G. MVP/V1 scope
H. Later-phase features
I. Risks/unknowns/questions for the domain expert
J. Recommended next development step
Do not begin implementation until I review and approve this architecture.
</deliverables>
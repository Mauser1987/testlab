We have reviewed the architecture and can now resolve three important open questions from the requirements analysis.
Product-owner decisions
1. Relationship between Test Run and TCN
Every individual Test Run shall have a TCN.
This is true even when the Test Run follows the original Test Program exactly and there is no deviation.
Therefore:
Test Run 001 → TCN001
Test Run 002 → TCN002
Test Run 003 → TCN003
etc.
The TCN is the issued instruction for that individual Test Run, not merely an exception document.
A TCN may therefore contain zero or more deviations from the original Test Program.
For V1, Run Number and TCN Number can be treated as the same sequential identifier within a Project.
2. Wet-seal arrangements and Plug Seal
The principal wet-seal arrangements currently required are:
- Single seal
- Dual Pressurized
- Dual Unpressurized
A Plug Seal is optional and should NOT be modeled as a seal arrangement itself.
A Plug Seal may be installed when testing a single seal or when process-side simulation is required on a dual seal.
Typical configurations therefore include:
- Single
- Single + Plug Seal
- Dual Pressurized
- Dual Pressurized + Plug Seal
- Dual Unpressurized
- Dual Unpressurized + Plug Seal
Do not hard-code Plug Seal into the arrangement enumeration.
Model:
Seal Arrangement and Plug Seal presence/configuration separately.
The application should adapt relevant terminology/fields according to the selected configuration, preserving useful conditional behaviour currently implemented in the Excel/VBA generator.
Do not invent additional arrangements for M1.
3. Leakage measurement and average leakage
Leakage can be measured by different physical methods depending on the test setup.
Typical methods are:
- level drop from a reservoir
- liquid collected from the seal drain
Leakage can vary during a test, so individual leakage readings/rates may be recorded throughout the Test Run.
However, the overall reported average leakage is defined as:
Average Leakage Rate = Total Leakage Quantity / Actual Running Time
For example:
Total collected leakage = 2400 ml
Actual running time = 150 h
Average leakage = 16 ml/h
The overall average should therefore eventually be a calculated value rather than manually entered when the required source values are available.
Preserve the distinction between:
- leakage measurement method
- individual/intermediate leakage measurements
- total accumulated leakage
- actual running time
- calculated overall average leakage rate
This result functionality does not need to be implemented in M1 unless required by the architecture, but the data model must not prevent it later.
Additional product-owner decisions
Use the following unless you identify a serious architectural problem:
- An issued TCN must not be silently changed.
- Actual deviations occurring during execution belong to the Test Result.
- If the issued instruction itself must formally change, create a new TCN revision rather than rewriting the issued revision.
- Historical completed Test Runs must remain unchanged when Project defaults are edited later.
- Planned, Instructed and Actual values must remain distinguishable.
- Physical individual seal-component lifecycle tracking is a future feature, not M1.
- DCS integration is future scope.
- Automatic acceptance evaluation is future scope.
- Approval workflow should not be overbuilt in M1.
Your task
Update the requirements documents to incorporate these product-owner decisions and resolve the corresponding open questions and assumptions.
Then produce a final M1 implementation specification only.
M1 has one primary objective:
Replace the existing Excel/VBA TCN generator with a maintainable TestLab application.
A successful M1 shall allow an engineer to:
1. Create/open a Project.
2. Store the minimum Project and seal information required for TCN generation.
3. Create TCN001 using Project defaults.
4. Configure the applicable seal arrangement and optional Plug Seal.
5. Define the Test Run conditions and instructions.
6. Generate the TCN document.
7. Issue/lock the TCN.
8. Create TCN002 by inheriting/copying appropriate information rather than retyping everything.
9. Modify only what differs for TCN002.
10. Generate its TCN document without affecting TCN001.
Use the supplied real Excel/VBA generator and existing TCN documents as the primary M1 requirements and regression examples.
Important scope control
Design the architecture so later milestones can support Test Programs, Results, Test Summaries, Final Reports, DCS data, P&IDs and richer component traceability.
Do not implement those features in M1.
Do not create abstractions, database entities or services in M1 merely because they might be useful someday unless they are necessary to avoid an obvious architectural dead end.
We prefer a simple M1 that completely replaces the current TCN workflow over a sophisticated partial PLM architecture.
Deliverables
Update the existing requirements documents as appropriate and produce the final M1 specification containing:
1. Exact M1 entities and database fields.
2. Relationships between them.
3. Which values are Project defaults versus TCN snapshots/overrides.
4. TCN numbering, status, issue, lock and revision rules.
5. Seal Arrangement + optional Plug Seal behavior.
6. Exact M1 screens/forms and navigation.
7. Create-TCN and Copy/Next-TCN workflow.
8. Conditional terminology/business logic that must be migrated from the Excel/VBA generator.
9. DOCX template-generation architecture.
10. Validation rules.
11. Acceptance/regression tests using the supplied real TCN examples.
12. Proposed repository/file structure.
13. Implementation sequence divided into small, reviewable Git commits.
14. Any remaining questions that genuinely block M1.
Do not write application code yet.
Do not expand scope.
Finish by stating whether M1 is sufficiently specified to begin implementation and identify any unresolved decisions that would materially affect its database design.
Deployment target: TestLab shall be designed as an internal multi-user web application. During local development it may use SQLite and local file storage. Production deployment shall run one centrally hosted Django application on an internal company server, accessed by engineers through a standard web browser without local installation. Production must not rely on a SQLite database located on a network share or synchronized folder. The architecture shall remain database-portable so PostgreSQL can be used for production. Project documents, drawings, photographs, CSV files and generated reports shall use configurable server-side file storage. Corporate SSO may be integrated later; M1 may use Django's built-in authentication.
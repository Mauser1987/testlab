The M1 specification is approved in principle with the following final corrections:
1. Move the legacy Excel/XLSM importer out of M1. Do not implement historical migration yet. We will validate the data model against real new projects before building migration tooling.
2. Project number may be corrected while no TCN has been issued. Once at least one TCN has been issued, changing the project number shall be blocked in normal M1 UI. Do not use creation of a draft TestRun as the locking event.
3. Do not enforce ^\d{4}RSD\d{2}TL$ as a hard project-number requirement. Treat the normal RSD format as a convention/UI warning if useful. Uniqueness remains mandatory.
4. In the domain/UI, distinguish the optional Plug Seal from the mechanical seal arrangement under test. A Plug Seal is process-side simulation/test equipment and is not another stage of a dual mechanical seal. It may still be represented by a SealPosition internally if that keeps M1 simple, but UI terminology and domain comments must preserve this distinction.
5. Do not assume that Single means there is no support/flush circuit. Single seals may use a support/flush arrangement such as Plan 23. Do not destructively clear support-system information merely because arrangement changes to Single unless this is explicitly required by confirmed business logic.
6. For M1, keep support-system modelling simple and compatible with the existing TCN. Do not attempt to build a full API piping-plan model.
7. Keep the Test Data Sheet XLSX generation in M1.
8. Keep the existing snapshot architecture, TestRun/TCN-revision separation, issued-document immutability, optimistic locking and DOCX/template hashing. These are approved.
9. Keep production deployment as a centrally hosted Django web application with PostgreSQL and configurable server-side file storage. SQLite is development/test only.
Update the M1 specification only where these decisions require changes. Do not perform another broad architecture redesign.
Then begin implementation of M1 Commit 1 only from the proposed implementation sequence.
Before writing code, state exactly what Commit 1 will contain. Then implement it, run its tests, and stop.
Do not proceed to Commit 2 until explicitly instructed.
Do not implement any post-M1 functionality.

Plug Seal conditions clarification
The optional Plug Seal is not merely a configuration flag or free-text item. When installed, it normally has its own operating conditions that must be explicitly captured on the TCN.
Plug Seal conditions typically include:
- fluid/medium,
- pressure,
- temperature,
- flow.
Rotational speed is common to the entire Test Run because the Plug Seal and test seal operate on the same shaft. Do not duplicate speed as an independent Plug Seal condition.
Therefore, M1 must support explicit Plug Seal operating conditions when plug_seal_present = true.
Keep a clear distinction between:
- common Test Run conditions such as speed and duration,
- process/test-side conditions,
- mechanical-seal support conditions such as barrier/buffer/flush,
- Plug Seal conditions.
Do not assume that these fluid circuits share pressure, temperature, flow or fluid.
Review the current proposed RunSetup / condition model accordingly. Avoid ambiguous generic fields such as a single support_pressure if they cannot distinguish physically separate circuits.
Keep the implementation pragmatic for M1. Do not build a generic piping-plan or process-simulation framework merely to support this requirement.
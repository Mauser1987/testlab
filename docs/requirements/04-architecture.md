# 04 — Application Architecture & Technology Stack (Deliverable D; task 13)

Updated with PO deployment decision (answers_n1): internal multi-user web
application, one centrally hosted Django application, PostgreSQL in
production, SQLite only for local development, configurable server-side
file storage, Django built-in authentication in M1 (SSO later).

## 1. Shape of the application

One application, one database, one file store, one internal server.

```
 Engineers' browsers (no local installation)
          │  https on internal network
          ▼
 ┌──────────────────────────────────────────────┐
 │  TestLab — single Django application         │
 │   • pages & forms (server-rendered)          │
 │   • business rules (copy/inherit, lock,      │
 │     revisions, later calculations)           │
 │   • DOCX generator (Word templates)          │
 └───────────────┬──────────────────┬───────────┘
                 │                  │
     PostgreSQL (production)    File storage (configurable root;
     SQLite (local dev only)    templates, generated DOCX, later
                                drawings, photos, CSV)
                 │                  │
                 └── scheduled backup (DB dump + files) ──► backup location
```

Why a **central web application**:
- The current workbook is copied per project (the "2026RSD06TL" workbook
  holds 2026RSD03TL and 2025RSD02TL data). One central database ends that.
- Nothing to install on engineers' laptops.
- Still no cloud and no microservices.

**Production must not use SQLite on a network share or synced folder.**
SQLite is used for local development and automated tests only.
The code uses only the Django ORM and portable field types, so the same
code runs on SQLite (dev) and PostgreSQL (production). The test suite runs
on SQLite by default and must also pass on PostgreSQL before a release.

## 2. Stack

| Part | Choice | Why it suits this lab |
|---|---|---|
| Language | **Python 3.12** | Best ecosystem for Word generation, spreadsheet/CSV handling and plotting; readable for engineers who know some scripting. |
| Web framework | **Django 5.x (LTS)** | Batteries included: migrations, forms with validation, built-in authentication, and an **admin screen** for maintenance tasks without building extra screens. Mature — good for a tool that must live 10+ years. |
| Pages | Server-rendered Django templates, minimal JavaScript (htmx optional, only where it removes a full page reload) | Forms-heavy app; no separate front-end project. |
| Database | **PostgreSQL** (production), **SQLite** (development/tests) | Multi-user safe, standard backup tooling; Django keeps the code database-portable. |
| File storage | Django storage API, root directory configured by environment variable | Server-side, configurable; can move to another storage backend without code changes. |
| DOCX | **docxtpl** (Jinja placeholders inside real Word templates) | Templates are edited in Word; formatting stays in Word, not in code. See 06. |
| XLSX (log sheet export) | **openpyxl** | Replaces Excel "Create Test Data Sheet" (M1). |
| PDF | LibreOffice headless on the server (Linux; a normal LibreOffice install on Windows development machines) | **The controlled TCN document is a PDF** (11 §17 S1): Word template → temporary DOCX → PDF. No Microsoft Office. |
| Plots (later) | matplotlib | Generates plots from logged data. |
| P&ID builder (later) | Isolated browser SVG editor page; diagram as JSON; SVG/PNG export | Keeps the rest of the app free of heavy JS. |
| App server | gunicorn (Linux) or waitress (Windows) behind the company's reverse proxy (nginx/IIS) | Standard, simple. |
| Auth | Django built-in users/groups in M1; corporate SSO later | Per PO decision. |

Alternative considered: .NET (Blazor) + OpenXML templating — reasonable if
IT mandates Microsoft-only stacks; more code for the same result.

## 3. Internal structure (Django apps inside the single project)

| App | Responsibility | Milestone |
|---|---|---|
| `projects` | Project, project default run setup | M1 |
| `tcn` | TestRun, Tcn revisions, RunSetup, SealPosition, copy/diff, issue/lock, labels | M1 |
| `documents` | Template rendering (TCN PDF via Word template, log sheet XLSX) | M1 |
| `legacy` | Import of the Excel/VBA DataBase sheet (management command) | post-M1 (PO round 2) |
| `programs` | Test program, planned tests, revisions | M3 |
| `results` | Result, manual log, measurements, leakage calculations, figures | M2 |
| `reports` | Final report assembly | M4 |
| `dcs`, `pid` | CSV import/plots; P&ID editor | M5, M6 |

Only the M1 apps are created in M1.

## 4. Data safety

- Status-based locking; issued TCN revisions are read-only at model level
  (not only in the UI); changes via a new revision with a reason.
- No hard delete of issued records (cancel instead).
- Issued documents are stored once and never regenerated in place.
- Optimistic concurrency check on draft edits (two engineers editing the
  same draft → the second save is refused with a clear message, no silent
  overwrite).
- Scheduled backup of PostgreSQL (pg_dump) + file storage; restore
  procedure tested once as part of M1 hand-over.

## 5. Configuration (environment variables)

`TESTLAB_SECRET_KEY`, `TESTLAB_DEBUG`, `TESTLAB_ALLOWED_HOSTS`,
`TESTLAB_DATABASE_URL` (default: local SQLite file for development),
`TESTLAB_FILE_ROOT` (file storage root), `TESTLAB_TEMPLATE_DIR`
(Word templates; default: repository `doc_templates/`),
`TESTLAB_PROJECT_NO_PATTERN` (format convention; mismatch gives a warning only, see M1 spec).

# TestLab

Internal Test Lifecycle Management application for the wet-seal test
laboratory. Milestone M1 replaces the Excel/VBA TCN generator; see
`docs/requirements/11-m1-specification.md` (requirements index:
`docs/requirements/README.md`).

## Status

M1 is implemented commit by commit following §14 of the M1 specification.

| # | Commit | State |
|---|---|---|
| 1 | Project skeleton (settings, login, base layout, pytest) | done |
| 2 | Project model & screens (list/search, create, edit) | done |
| 3 | Run setup model & arrangement rules | done |
| 4 | Project defaults form (shared run setup form, arrangement switching) | done |
| 5 | TestRun / TCN revision models (constraints, immutability guard; no screens yet) | done |
| 6 | Create & copy TCN (project page / register, new TCN, draft edit, optimistic locking) | done |
| 7 | Differences vs source (“changed — was: …” markers, difference list) | done |
| 8 | TCN Word template & Preview DOCX (PDF since 10a) | done |
| 9 | Issue & lock (issue confirmation, stored document (PDF since 10a) + hashes + snapshot, read-only view, download, project-number lock) | done |
| 10 | Revisions, cancel, delete draft (new revision from S9, cancel with reason S10, delete draft with confirmation) | done |
| 10a | Stabilization (spec §17): controlled TCN document is a PDF; registration with corporate email domain and administrator approval | done |
| 11–13 | Test Data Sheet, PostgreSQL, acceptance | not started |

What works today:

- **Projects** — list with search, create, edit. Project numbers are stored
  upper-case and must be unique; the usual `YYYYRSDnnTL` format is a
  convention (warning only).
- **Project defaults** — the run setup new TCNs will start from:
  - seal arrangement under test: Single, Dual Pressurized or Dual Unpressurized;
  - **Plug Seal** (test equipment that establishes the process conditions,
    not part of the arrangement) with its own seal data — required for a
    single seal, optional for dual;
  - conditions per circuit: common (test unit, duration, speed) · process
    (the Plug Seal operating conditions; only with a Plug Seal) · seal
    support (Barrier / Buffer / Flush — a single seal may have a flush
    circuit);
  - parameters to log (process pressure, temperature and flow are logged
    with the Plug Seal; Plug Seal face temperature and leakage);
  - switching arrangement or Plug Seal asks for confirmation before any
    non-empty data is discarded; seal-support values are never cleared.
- **Project page and TCN register** — one row per Test Run (its current
  revision), with Open and Copy to new TCN.
- **New TCN** — from the project defaults or as a copy of a TCN of the same
  project; the run number (= TCN number) is proposed and may be changed.
  The TCN gets its own copy of the run setup: later changes to the project
  defaults or to the source TCN never affect it.
- **Draft TCN editing** — project description, prepared by, and the shared
  run setup form. If someone else saved the draft in the meantime, the save
  is refused with who/when (reload to continue).
- **Differences vs source** — on a copied TCN every field that differs from
  the source TCN is marked "changed — was: …", with a list of all
  differences at the top (saved values; TCNs made from the project defaults
  have no comparison).
- **Preview PDF** — a draft TCN opens as a PDF in the layout of the Excel
  TCN, marked "DRAFT — not issued". It shows the saved draft and is not stored.
- **Issue** — "Issue…" on a draft checks that the TCN is complete, shows the
  differences from its source, and on confirmation stores the **PDF** (without
  the draft marking), its SHA-256, the document template's SHA-256 and the
  printed data. The user who confirms is recorded as issued by. The issued
  TCN is read-only for good; downloads always serve the stored PDF. If the
  PDF cannot be generated nothing is issued. Once a TCN of a project is
  issued, the project number can no longer be changed.
- **Controlled document** — TCNs are only ever shown and downloaded as PDF.
  Layout comes from the HTML document template `app/doc_templates/tcn/`
  (HTML + print CSS, bundled Carlito font), rendered directly to PDF by
  WeasyPrint. It is separate from the TCN pages of the application.
- **New revision** — "New revision" on the current issued TCN creates the
  next revision as a draft (a copy of it; prepared by the current user).
  Only one draft at a time, and none for a cancelled run. It needs a reason
  to be issued; issuing it supersedes the previous revision, whose record
  and document stay unchanged and downloadable.
- **Cancel TCN** — the current issued revision can be cancelled with a
  reason (not while a draft revision of the run is pending — delete that
  first). It is kept with its document, cannot be revised any more, and
  can still be copied to a new TCN.
- **Delete draft** — after confirmation a draft is removed without trace;
  deleting a draft rev 0 also removes the run (the number becomes free). A
  draft another TCN was copied from cannot be deleted.

- **Accounts** — "Log in | Register". Registration asks first name, last
  name, corporate email address and password; only the domains in
  `TESTLAB_ALLOWED_EMAIL_DOMAINS` may register. New accounts wait for an
  administrator to approve them (below). Users log in with their email address.

Out of M1: legacy Excel import, Test Programs, Results, Summaries, Final
Reports, DCS/LabVIEW data.

## Development setup

Requires Python 3.12+ and the **Pango** library, which WeasyPrint uses to
render the TCN PDF:

- Linux: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0` (present on
  most desktop installations).
- Windows: see *Windows: WeasyPrint* below.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python app/manage.py migrate
.venv/bin/python app/manage.py createsuperuser
.venv/bin/python app/manage.py runserver
```

`manage.py check` (and `runserver`) warn with `testlab.W002` when
WeasyPrint cannot be loaded. The TCN PDF uses only the fonts in the
template bundle, so it looks the same on every machine; no Office or
LibreOffice is needed.

### Windows: WeasyPrint

WeasyPrint needs Pango from MSYS2 on Windows:

1. Install MSYS2 from https://www.msys2.org (default folder `C:\msys64`).
2. In the **MSYS2 UCRT64** shell: `pacman -S mingw-w64-ucrt-x86_64-pango`
3. WeasyPrint finds `C:\msys64\ucrt64\bin` by itself; for another folder
   set `WEASYPRINT_DLL_DIRECTORIES` to its `bin` directory.

```bat
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\weasyprint --info
.venv\Scripts\python app\manage.py check
```

**Proof on the corporate workstation** (required before the transitional
DOCX renderer below is removed):

1. `weasyprint --info` runs and `manage.py check` reports no `testlab.W002`.
2. `.venv\Scripts\pytest` passes — every TCN test renders real PDFs,
   including A4 size, header/footer and "Page x of y" on each page, only
   the bundled fonts embedded, and byte-identical output on repeated
   renders.
3. Preview PDF of a TCN shows the same line and page breaks as the same TCN
   rendered on the Linux server. (The files need not be byte-identical
   across machines: Pango/HarfBuzz versions can differ.)

### Chromium renderer (under validation, M1 spec §19)

`TESTLAB_TCN_RENDERER=chromium` prints the TCN with headless Chromium
through Playwright (the engine Seal Inspection uses). It needs no system
libraries on Windows; the browser is downloaded once into the user profile:

```bat
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
```

(about 150 MB; behind HTTPS inspection the download may need the company
root certificate. On Linux, if Chromium cannot start for missing libraries:
`.venv/bin/python -m playwright install-deps chromium` on Debian/Ubuntu.)
`manage.py check` warns with `testlab.W003` when Chromium is missing.

**Validation on the corporate Windows workstation:**

1. `set TESTLAB_TCN_RENDERER=chromium` and `.venv\Scripts\python app\manage.py check`
   reports no `testlab.W003`.
2. `set TESTLAB_PROOF_DIR=%CD%\proof` and `.venv\Scripts\pytest -m chromium`
   passes (exact page size, margins, Carlito only, logo, header/footer and
   "Page x of y" on every page, draft marking, page breaks, no request
   outside the template, content/layout determinism, AT-2/AT-3/AT-16).
   It writes the sample PDFs and `timings.json` to `proof\`.
3. The PDFs in `proof\` show the same line and page breaks as the same
   samples rendered on Linux.

### Transitional: DOCX renderer

Until the proof above is done, `TESTLAB_TCN_RENDERER=docx` renders the
TCN the old way: Word template `app/doc_templates/tcn.docx` → DOCX → PDF
converted by **LibreOffice** (`TESTLAB_PDF_CONVERTER=libreoffice`, the
default; `apt install libreoffice-writer`, or LibreOffice for Windows,
otherwise set `TESTLAB_SOFFICE`) or by the locally installed desktop
**Microsoft Word** (`TESTLAB_PDF_CONVERTER=word`, Windows only, needs
`pip install -e ".[dev,word]"`; `auto` = LibreOffice when found, else
Word). Word runs invisibly in its own instance per conversion and is
closed again after every conversion, also when it fails; run TestLab in
the desktop session of a user with an activated Word. With this renderer
`manage.py check` warns with `testlab.W001` when the converter is not
found; tests marked `libreoffice` or `word` use the real conversion and
are skipped without it.

Open http://localhost:8000/ and log in. `createsuperuser` is for the first
(bootstrap) administrator only.

### Users: registration and approval

1. Set the corporate domain(s), e.g. `TESTLAB_ALLOWED_EMAIL_DOMAINS=example.com`
   (comma-separated for several). Without it registration is closed.
2. A user chooses **Register** on the login page. The account is created
   inactive: "awaiting administrator approval".
3. An administrator opens Django admin → **Users**, filter **Approval:
   Awaiting approval**, selects the account(s) and runs **Approve selected
   accounts (activate)** — or ticks **Active** on the user page.
   Deactivating an account (untick Active) blocks its login again.
4. The user logs in with the email address.

Every active user may issue and cancel TCNs in M1; the check lives in
`app/testlab/tcn/permissions.py` so it can be restricted later. Corporate
SSO (Entra ID/LDAP) is future work and would be added as another Django
authentication backend without changing the TCN data.

By default the development database is a SQLite file at `data/testlab.sqlite3`
(git-ignored).

### Starting TestLab locally (after the setup above)

Convenience scripts for local testing; they can be run from any directory.
They use the existing `.venv` (nothing is installed), apply pending
migrations to the development database, and start the Django development
server at **http://127.0.0.1:8000/** (stop with Ctrl+C). They are not a
production deployment.

- Linux: `scripts/start-linux.sh`
- Windows: double-click `scripts\start-windows.bat`, or run it from a
  command prompt. On Windows the environment is created with
  `py -3.12 -m venv .venv` and `.venv\Scripts\pip install -e ".[dev]"`.

If `.venv` is missing or incomplete, the script stops and prints the setup
commands.

## Using it

1. Log in and choose **New project**: project no., description (printed on
   the TCN as "Project Description"), customer.
2. Saving continues to **Project defaults**. Choose the arrangement and
   whether a Plug Seal is installed — always for Single (the form redraws; the **Update** button
   does the same without JavaScript), fill in seals, conditions and
   parameters to log, then **Save**.
3. Typed units that TestLab prints anyway are removed (`70 barg` → `70`);
   a message shows each change.
4. On the project page choose **New TCN**: TCN001 starts from the project
   defaults; later TCNs are proposed as a copy of the latest TCN (or use
   **Copy to new TCN** on any register row). Edit what differs and **Save**.

## Code layout

```
app/
├── manage.py
├── conftest.py                 shared pytest fixtures
├── config/                     settings (env-driven), urls, wsgi
├── doc_templates/              document templates: tcn/ (HTML bundle), tcn.docx (transitional) + reference (README.md)
├── tests/                      cross-cutting tests (login required); fixtures/ (AT-2 expected text)
└── testlab/
    ├── templates/              base layout, login
    ├── static/testlab/         CSS
    ├── accounts/               registration, email login backend, user admin with approval
    ├── projects/
    │   ├── models.py           Project, RunSetup, SealPosition
    │   ├── arrangements.py     arrangement / Plug Seal rules, labels, monitored parameters
    │   ├── conditions.py       condition field groups per circuit, unit clean-up
    │   ├── forms.py            project form
    │   ├── setup_forms.py      shared run setup form + RunSetupEditor (switching, discard)
    │   ├── templatetags/       `was` filter: change markers in the shared form
    │   ├── views.py, urls.py, templates/projects/
    │   ├── migrations/
    │   └── tests/
    ├── tcn/
    │   ├── models.py           TestRun, TcnRevision; status rules and immutability guards
    │   ├── services.py         create / copy TCN, save draft (optimistic locking), issue, revise, cancel, delete
    │   ├── permissions.py      who may issue / cancel (M1: every active user)
    │   ├── diff.py             differences vs the source TCN (markers, change list)
    │   ├── forms.py, views.py, urls.py, templates/tcn/
    │   ├── migrations/
    │   └── tests/
    └── documents/
        ├── tcn_context.py      TCN render context: labels, units, NA rule, column sets
        ├── render.py           tcn_template(): HTML template bundle → PDF (WeasyPrint); DOCX renderer (transitional)
        ├── pdf.py              DOCX → PDF for the DOCX renderer: LibreOffice headless (timeout, temporary profile)
        ├── pdf_word.py         optional Microsoft Word backend of pdf.py (Windows, COM automation via pywin32)
        ├── checks.py           system checks: WeasyPrint loadable; PDF converter present (DOCX renderer)
        └── tests/
docs/requirements/              requirements and M1 specification
reference/                      historical source documents (read-only)
```

## Tests

```bash
.venv/bin/pytest
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `TESTLAB_DEBUG` | `1` | Set `0` in production |
| `TESTLAB_SECRET_KEY` | dev key (only when debug) | Required when debug is off |
| `TESTLAB_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `TESTLAB_DATABASE_URL` | `sqlite:///<repo>/data/testlab.sqlite3` | e.g. `postgres://user:pass@host/testlab` |
| `TESTLAB_DATA_DIR` | `<repo>/data` | Location of the default SQLite file |
| `TESTLAB_PROJECT_NO_PATTERN` | `^\d{4}RSD\d{2}TL$` | Usual project-number format; a mismatch only gives a warning |
| `TESTLAB_TIME_ZONE` | `Europe/Amsterdam` | |
| `TESTLAB_FILE_ROOT` | `<repo>/data/files` | Server-side file store (issued TCN PDFs) |
| `TESTLAB_TEMPLATE_DIR` | `<repo>/app/doc_templates` | Document templates of generated documents |
| `TESTLAB_TCN_RENDERER` | `html` | TCN PDF renderer: `html` (WeasyPrint), `chromium` (under validation) or `docx` (transitional, see above) |
| `TESTLAB_PDF_CONVERTER` | `libreoffice` | DOCX renderer only: `libreoffice`, `word` (Windows workstation with Microsoft Word, needs the `word` extra) or `auto` (LibreOffice when found, else Word) |
| `TESTLAB_SOFFICE` | found on PATH / usual install dirs | DOCX renderer only: path of LibreOffice `soffice` (`soffice.com` on Windows) |
| `TESTLAB_PDF_TIMEOUT` | `120` | DOCX renderer only: seconds allowed per PDF conversion |
| `TESTLAB_ALLOWED_EMAIL_DOMAINS` | *(empty: registration closed)* | Comma-separated email domains that may register, e.g. `example.com` |
| `TESTLAB_STATIC_ROOT` | `<repo>/staticfiles` | Target of `collectstatic` |

Production runs one central Django application with **PostgreSQL**
(`pip install -e ".[postgres]"`). SQLite is for development and tests only
and must not be placed on a network share or synchronised folder.

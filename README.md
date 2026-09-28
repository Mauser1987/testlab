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
| 8 | TCN Word template & Preview DOCX | done |
| 9 | Issue & lock (issue confirmation, stored DOCX + hashes + snapshot, read-only view, download, project-number lock) | done |
| 10–13 | Revisions/cancel/delete draft, Test Data Sheet, PostgreSQL, acceptance | not started |

What works today:

- **Projects** — list with search, create, edit. Project numbers are stored
  upper-case and must be unique; the usual `YYYYRSDnnTL` format is a
  convention (warning only).
- **Project defaults** — the run setup new TCNs will start from:
  - seal arrangement under test: Single, Dual Pressurized or Dual Unpressurized;
  - optional **Plug Seal** (process-side test equipment, not part of the
    arrangement) with its own seal data and conditions;
  - conditions per circuit: common (test unit, duration, speed) · process ·
    seal support (Barrier / Buffer / Flush — a single seal may have a flush
    circuit) · Plug Seal;
  - parameters to log (incl. Plug Seal pressure, inlet temperature, flow);
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
- **Preview DOCX** — a draft TCN can be downloaded as a Word document in the
  layout of the Excel TCN (template `app/doc_templates/tcn.docx`), marked
  "DRAFT — not issued". It shows the saved draft and is not stored.
- **Issue** — "Issue…" on a draft checks that the TCN is complete, shows the
  differences from its source, and on confirmation stores the Word document
  (without the draft marking), its SHA-256, the template's SHA-256 and the
  printed data. The user who confirms is recorded as issued by. The issued
  TCN is read-only for good; downloads always serve the stored file. Once a
  TCN of a project is issued, the project number can no longer be changed.
- New revisions, cancelling and deleting drafts follow in the next commit.

Out of M1: legacy Excel import, Test Programs, Results, Summaries, Final
Reports, DCS/LabVIEW data.

## Development setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python app/manage.py migrate
.venv/bin/python app/manage.py createsuperuser
.venv/bin/python app/manage.py runserver
```

Open http://localhost:8000/ and log in. Users are managed by superusers
in Django admin (`/admin/`).

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
   whether a Plug Seal is installed (the form redraws; the **Update** button
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
├── doc_templates/              Word templates (tcn.docx) + tag reference (README.md)
├── tests/                      cross-cutting tests (login required); fixtures/ (AT-2 expected text)
└── testlab/
    ├── templates/              base layout, login
    ├── static/testlab/         CSS
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
    │   ├── services.py         create / copy TCN, save draft (optimistic locking)
    │   ├── diff.py             differences vs the source TCN (markers, change list)
    │   ├── forms.py, views.py, urls.py, templates/tcn/
    │   ├── migrations/
    │   └── tests/
    └── documents/
        ├── tcn_context.py      TCN render context: labels, units, NA rule, column sets
        ├── render.py           docxtpl rendering (keeps template column widths)
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
| `TESTLAB_FILE_ROOT` | `<repo>/data/files` | Server-side file store (issued TCN documents) |
| `TESTLAB_TEMPLATE_DIR` | `<repo>/app/doc_templates` | Word templates of generated documents |
| `TESTLAB_STATIC_ROOT` | `<repo>/staticfiles` | Target of `collectstatic` |

Production runs one central Django application with **PostgreSQL**
(`pip install -e ".[postgres]"`). SQLite is for development and tests only
and must not be placed on a network share or synchronised folder.

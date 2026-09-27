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
| 5–13 | TCN models, create/copy, diff, DOCX, issue/lock, revisions, Test Data Sheet, PostgreSQL, acceptance | not started |

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

## Using it

1. Log in and choose **New project**: project no., description (printed on
   the TCN as "Project Description"), customer.
2. Saving continues to **Project defaults**. Choose the arrangement and
   whether a Plug Seal is installed (the form redraws; the **Update** button
   does the same without JavaScript), fill in seals, conditions and
   parameters to log, then **Save**.
3. Typed units that TestLab prints anyway are removed (`70 barg` → `70`);
   a message shows each change.

## Code layout

```
app/
├── manage.py
├── conftest.py                 shared pytest fixtures
├── config/                     settings (env-driven), urls, wsgi
├── tests/                      cross-cutting tests (login required)
└── testlab/
    ├── templates/              base layout, login
    ├── static/testlab/         CSS
    └── projects/
        ├── models.py           Project, RunSetup, SealPosition
        ├── arrangements.py     arrangement / Plug Seal rules, labels, monitored parameters
        ├── conditions.py       condition field groups per circuit, unit clean-up
        ├── forms.py            project form
        ├── setup_forms.py      shared run setup form + RunSetupEditor (switching, discard)
        ├── views.py, urls.py, templates/projects/
        ├── migrations/
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
| `TESTLAB_STATIC_ROOT` | `<repo>/staticfiles` | Target of `collectstatic` |

Production runs one central Django application with **PostgreSQL**
(`pip install -e ".[postgres]"`). SQLite is for development and tests only
and must not be placed on a network share or synchronised folder.

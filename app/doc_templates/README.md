# Document templates

TestLab owns both the data and the layout of its controlled documents.
Each is an HTML template bundle printed to PDF by headless Chromium
through Playwright (`testlab/documents/render.py`, `ChromiumTemplate`), the
only PDF renderer. A template is a document template only — it is not a
page of the application and has no access to the application's page
templates.

The directory is configurable with `TESTLAB_TEMPLATE_DIR` (default: this
directory).

Rules for every bundle:

- Only files of the bundle are loaded (relative URLs such as `logo.jpg`,
  `fonts/…`); anything else — other files, `file:`/`http(s):` URLs — stops
  the printing. A missing file, an unloaded font or a broken image stops it
  too.
- Only the bundled fonts (Carlito, metric-compatible with Calibri, SIL Open
  Font License — `fonts/OFL.txt`) are used, so the PDF does not depend on
  the fonts installed on the machine. New characters must exist in Carlito.
- `header.html` and `footer.html` are Chromium's header/footer templates,
  repeated on every page; they cannot load files, so they inline bundle
  files with `{% bundle_data_uri "logo.jpg" %}`. Chromium fills in elements
  with the classes `pageNumber` and `totalPages` (also `title`, `date`,
  `url`): do not use these classes for own content.
- The bundle is hashed byte for byte (`.gitattributes` keeps line endings
  unchanged): `template_sha256` of an issued TCN /
  of an issued report document is the SHA-256 of the lines `<path>\0<SHA-256 of the
  file>\n`, one per file of the bundle, sorted by path. Any change to any
  file gives a new hash; stored PDFs are never re-rendered.

## `tcn/` — Test Change Notice

Layout of `reference/tcn/TCN001.pdf` (the Excel TCN print), on A4, 11 pt.

| File | Content |
|---|---|
| `tcn.html` | The body: project and run description, seal information, test conditions, acceptance requirement changes (only when the TCN has any) |
| `header.html`, `footer.html` | Logo, project/TCN numbers, draft marking, Prepared by/Created, "Page x of y" |
| `tcn.css` | Print layout: `@page` size and margins, column widths |
| `logo.jpg`, `fonts/Carlito-*.ttf` | Logo and fonts |

The context is built by `testlab/documents/tcn_context.py`: `project_no`,
`tcn_no`, `is_draft`, `project_description`, `run_description_lines`
(`line.text`, `line.level` 0–2 → class `level-N`), `reference_drawing`,
`seal_columns`, `test_unit`, `duration`, `speed`, `condition_columns`,
`prepared_by`, `created_date`, `requirement_changes` (`action`, `ref`,
`criterion`, `requirement`, `was`, `reason`). It already contains labels,
units and "NA". Previews use the named page `draft` (deeper top margin for
the draft marking). After changing the template, run the test suite: AT-2
compares the text of the rendered TCN001 with
`app/tests/fixtures/tcn001_expected.txt`; tests marked `chromium` check
the PDF (A4, header/footer and page numbers on every page, fonts,
determinism).

## `run_report/` — Test Run Report (Chromium HTML template bundle, M2C)

A4 portrait, printed by headless Chromium (Playwright) like `tcn/`.

| File | Content |
|---|---|
| `report.html` | The document body: identification (title, elapsed and running hours, Prepared by, Draft/Final), numbered sections (objective, description, configuration, conditions, leakage with the cumulative chart, plots, events and observations, measurements and wear, seal-face details, pictures, acceptance with requirement sources, conclusion), Annex A (manual log) |
| `header.html`, `footer.html` | Chromium header/footer templates: logo, project/run/TCN, DRAFT marking, Page x of y |
| `report.css` | Print layout: `@page`, tables (repeated headers, rows never split), figures (never cropped) |
| `logo.jpg`, `fonts/Carlito-*.ttf` | Same files as `tcn/` (each bundle is self-contained) |

The context is built by `testlab/documents/run_report_context.py`
(`build_run_report_context`): plain data only, every value already
formatted, sections without content left out (`sections` holds the numbers
of the sections present). Calculations come from `results.runtime`,
`results.evidence` and `results.acceptance`, never from the template. At
finalization this context is stored as the snapshot of the final report
(`is_draft` false, `report.finalized` with who and when).

Pictures and plots are not bundle files: they are passed to the renderer
as `assets/…` (`report_assets`), next to the bundle and outside its hash.
Pictures are the stored display copies (whole picture, at most 1600 px,
upright); plots are the stored report PNGs of the Result.

Do not give elements the classes `title`, `date`, `url`, `pageNumber` or
`totalPages` in the header/footer for own content: Chromium fills them in.

## `final_report/` — Final Report of a project (rough version)

`final_report.html` (the document), `header.html`, `footer.html` and
`final_report.css`. It is printed together with the files of `run_report/`
(styles, fonts, logo): each run's section is rendered by
`run_report/report.html` from the run's frozen record and placed in the
document as it is, with its section numbers under 5.<n>
(`testlab/reports/assembly.py`). Draft only: no template hash is stored.

# Document templates

TestLab owns both the data and, for the TCN, the layout: the controlled TCN
document is rendered from an HTML template with print CSS straight to PDF
(WeasyPrint). The template is a document template only — it is not the TCN
page of the application and has no access to the application's page
templates.

The directory is configurable with `TESTLAB_TEMPLATE_DIR` (default: this
directory).

## `tcn/` — Test Change Notice (HTML template bundle)

Layout of `reference/tcn/TCN001.pdf` (the Excel TCN print), on A4, 11 pt.

| File | Content |
|---|---|
| `tcn.html` | The document: page header, page footer, body. Django template language, values escaped |
| `tcn.css` | Print layout: `@page` size and margins, running header/footer, "Page x of y", column widths |
| `logo.jpg` | Header logo |
| `fonts/Carlito-*.ttf` | Carlito (metric-compatible with Calibri), SIL Open Font License — `fonts/OFL.txt` |

The context is built by `testlab/documents/tcn_context.py` (the same as
for the Word template below): `project_no`, `tcn_no`, `is_draft`,
`project_description`, `run_description_lines` (`line.text`,
`line.level` 0–2 → class `level-N`), `reference_drawing`, `seal_columns`,
`test_unit`, `duration`, `speed`, `condition_columns`, `prepared_by`,
`created_date`. It already contains labels, units and "NA".

Rules:

- Only files of the bundle are loaded (relative URLs such as `logo.jpg`,
  `fonts/…`); anything else — other files, `file:`/`http(s):` URLs — stops
  the rendering. A missing file stops it too.
- Only the bundled fonts are used, so the PDF does not depend on the
  fonts installed on the machine. New characters must exist in Carlito.
- The page header and footer are running elements: they must stay before
  `<main>` so that they appear from the first page on.
- Previews use the named page `draft` (deeper top margin for the draft
  marking); the issued layout is unchanged by it.
- The bundle is hashed byte for byte (`.gitattributes` keeps line endings
  unchanged): `template_sha256` of an issued TCN is the SHA-256 of the
  lines `<path>\0<SHA-256 of the file>\n`, one per file of the bundle,
  sorted by path (`HtmlTemplate.sha256`). Any change to any file gives a
  new hash; the issued PDFs themselves are never re-rendered.
- After changing the template, run the test suite: AT-2 compares the text
  of the rendered TCN001 with `app/tests/fixtures/tcn001_expected.txt`,
  other tests check the PDF (A4, header/footer and page numbers on every
  page, fonts, determinism).

## `tcn.docx` — Test Change Notice (Word template, transitional)

Used only with `TESTLAB_TCN_RENDERER=docx`, until WeasyPrint is proven on
the Windows workstations; then removed. The Word file rendered from it is
an internal step: TestLab converts it to PDF with LibreOffice
(`documents/pdf.py`; Microsoft Word on Windows workstations configured with
`TESTLAB_PDF_CONVERTER=word`) and only the PDF is previewed, issued and
downloaded (M1 spec §17 S1). Its tags are edited in Word:

Layout of `reference/tcn/TCN001.pdf` (the Excel TCN print), on A4, Calibri 11.
The context is built by `testlab/documents/tcn_context.py`; it already
contains labels, units and "NA", so the template only places values.

| Tag | Content | Example |
|---|---|---|
| `{{ project_no }}` | Project number (header) | `2026RSD03TL` |
| `{{ tcn_no }}` | Run/TCN number (header); revision from rev 1 | `001`, `001 rev 1` |
| `{%p if is_draft %}` … `{%p endif %}` | Draft marking under the header rule (previews) | `DRAFT — not issued` |
| `{{ project_description }}` | Project Description | `ADNOC BAB UHTW/UHTW 4.750/4.750` |
| `{%p for line in run_description_lines %}` | One paragraph per line of the Test Run Description | |
| `{{ line.text }}`, `line.level` | Line text (leading spaces removed); indent level 0, 1 or 2, printed with the paragraph styles **TCN Run Description**, **TCN Run Description 2**, **TCN Run Description 3** | `• Start Test Unit` |
| `{{ reference_drawing }}` | Reference Drawing | `F00321662 / D0527190-2 revB` |
| `{%tc for col in seal_columns %}` … `{%tc endfor %}` | One column per seal: Plug Seal (if installed), then Test Seal or Inboard + Outboard Seal | |
| `col.heading`, `col.seal_type_size`, `col.stationary_face`, `col.rotating_face`, `col.springs` | Seal column values | `Inboard Seal`, `UHTW 4.750` |
| `{{ test_unit }}`, `{{ duration }}`, `{{ speed }}` | Common Test Run conditions, with unit | `B`, `min 75 hours`, `2980 rpm` |
| `{%tc for col in condition_columns %}` … `{%tc endfor %}` | One column per circuit: Process Fluid (established with the Plug Seal; NA without it), Barrier/Buffer/Flush Fluid | |
| `col.heading`, `col.medium`, `col.pressure`, `col.inlet_temperature`, `col.flow` | Circuit values, with unit; `NA` or blank when empty (M1 spec §9.3) | `Barrier Fluid`, `70 barg`, `60°C`, `TBD l/min` |
| `{{ prepared_by }}`, `{{ created_date }}` | Footer | `MG`, `16-Jun-2026` |

Notes for editing:

- A `{%tc … %}` tag replaces the whole table cell it is in; each loop row
  therefore has a cell with `{%tc for … %}`, the value cell, and a cell with
  `{%tc endfor %}`. The table grid holds the widths of the rendered table
  (label column + three value columns); unused value columns are dropped
  without changing the others.
- `{%p … %}` tags replace the whole paragraph they are in.
- Keep the small **TCN Table Gap** paragraphs between adjacent tables:
  without them Word and LibreOffice join the tables.
- Labels follow TCN001.pdf literally, including "Stationary Seal Face"
  without a colon.
- After changing the template, run the test suite: AT-2 compares the
  generated TCN001 text with `app/tests/fixtures/tcn001_expected.txt`.

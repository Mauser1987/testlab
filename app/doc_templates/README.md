# Document templates

Word owns the look, TestLab owns the data (requirements 06 §1, M1 spec §9).
The templates are normal Word files with [docxtpl](https://docxtpl.readthedocs.io)
tags; edit them in Word. TestLab never sets fonts, margins or colours.

The directory is configurable with `TESTLAB_TEMPLATE_DIR` (default: this
directory).

The Word file rendered from a template is an internal step: TestLab
converts it to PDF with LibreOffice (`documents/pdf.py`) and only the PDF
is previewed, issued and downloaded (M1 spec §17 S1). Check a template
change in Preview PDF — LibreOffice renders the Word layout.

## `tcn.docx` — Test Change Notice

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

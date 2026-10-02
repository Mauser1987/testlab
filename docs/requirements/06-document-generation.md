# 06 — DOCX Document Generation (Deliverable F; task 15)

> The M1 TCN template, render context, formatting rules and issue storage
> are specified in 11-m1-specification.md §9. Uploading an edited final
> DOCX (§4 below) is not part of M1.
>
> **Amended 2026-09-29 (11 §17 S1):** the TCN is a controlled document —
> it is issued, stored and downloaded as a **PDF** generated from the Word
> template (template → temporary DOCX → PDF, LibreOffice headless). The
> DOCX is never offered, and §4 (engineer editing) does not apply to TCNs.
> Other document types are decided with their milestones.
>
> **Amended 2026-10-01 (11 §18):** the TCN layout is an HTML document
> template with print CSS rendered directly to PDF (WeasyPrint); for the
> TCN, §1 "Word owns the look" no longer applies.

## 1. Principle

**Word owns the look, TestLab owns the data.**
Each document type has one Word template (`.docx`) containing the existing
Flowserve layout — cover block, header/footer, confidentiality text, TOC,
styles — with placeholders where data goes. The code never sets fonts,
margins or colours.

## 2. Templates needed

| Template | Based on | Family |
|---|---|---|
| `test_program.docx` | 2026RSD06TL Celeros program (latest) | "Program/Report" template (cover block, TOC, revision table, appendices) |
| `tcn.docx` | TCN001.pdf layout (currently an Excel print) | New Word version of the Excel TCN form |
| `test_summary.docx` | Test Summary – TCN00x.docx | "Dynamic Test Run Summary" |
| `final_report.docx` | 2023RSD08TL-Test Report.docx | Program/Report family |
| `log_sheet.docx` or `.xlsx` (optional) | Excel "Test Data Sheet" | Blank printable manual log |

Templates live in the file store, registered in the app with a version
number; each generated document records which template version was used.
Engineers can update a template in Word and upload it (admin screen).

## 3. How it works

1. Engineer presses *Generate*.
2. App builds a **context** (plain data): project, program, run(s),
   result(s), computed values, image files, tables.
3. docxtpl renders the template:
   - simple fields: `{{ project.customer }}`, `{{ run.run_no }}`
   - conditional blocks: `{% if run.arrangement == 'single' %}` (Plug/Test labels) 
   - repeating rows/sections: `{% for r in results %}` … section 5.x … `{% endfor %}`
   - images: photos/plots inserted at fixed width inside table cells
   - rich text: paragraphs and bullet lists from free-text fields mapped onto
     the template's existing styles (engineers write with a minimal editor:
     paragraphs, bullets, sub-bullets, bold, sub/superscript for units)
4. The DOCX is saved as a `GeneratedDocument` together with a JSON snapshot
   of the context (exactly what was printed).
5. Word fields (TOC, page numbers, cross references) are flagged to update
   when the document is opened.

### Final report assembly
The report is **one template with loops over results**, not a merge of the
separately generated summary files. The summary section inside the report
and the standalone summary use the same data, so they can no longer diverge
(today, corrections were made only in the report).

### Tables
- Seal configuration, conditions & results, measurement results,
  executive summary table: real Word tables generated from data
  (today: summary table is a pasted Excel picture).
- Manual log: real Word table, landscape section. Long logs (>1 page) —
  option: full table in an appendix, or attach the log as XLSX.
  **Question for PO** (see 10).

## 4. Engineer editing of generated documents

- Generated DOCX is a normal Word file; the engineer may edit it.
- The app allows uploading the **final edited DOCX/PDF** as the issued file
  of that revision, so the archive holds what was actually sent.
- Warning shown: regenerating will not contain manual edits — corrections to
  *data* (values, conclusions) should be made in TestLab so later documents
  (report) pick them up. Manual edits are intended for layout and one-off wording.

## 5. What this fixes from the samples

| Sample problem | Fixed by |
|---|---|
| Header of Celeros program says 2026RSD03TL | header placeholder `{{ project.project_no }}` |
| Report header says "Test Program" | separate report template |
| BAB program cover block shows 2023RSD08TL | cover block always from current project |
| Summary numbers differ from report/exec table | all from one calculated value |
| Pasted pictures of Excel tables | generated Word tables |
| Report corrections not reflected in summaries | shared data source |

## 6. Out of scope for templates in V1
- Automatically written conclusions (CLAUDE.md: no AI conclusions).
- Tracked changes / comments generation.
- Customer-specific document formats beyond these four templates
  (can be added as extra templates later).

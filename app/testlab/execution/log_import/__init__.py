"""Importing a manual log kept in Excel into a Test Run (M2F).

    workbook (.xlsx) ──xlsx.read_sheet──▶ SourceSheet ──mapping──▶ confirmed mapping
         ──service.stage──▶ preview rows (interpret, matching, events, run check)
         ──service.commit──▶ ManualLogEntry rows, one transaction; service.undo removes them again

The importer is built around the manual-log schema (measurements.py), not
around one workbook: columns are matched by their header text, unit and the
run's configuration, never by fixed column letters. A source that already
names TestLab fields (a TestLab-generated log template, later) produces the
same SourceSheet with exact targets and feeds the same service.
"""

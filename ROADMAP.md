# TestLab roadmap

Where the project stands and what comes next. Written 2026-10-12, last updated 2026-10-14; update it at the end of
each working session.

## Where we are

- `main` on GitHub holds everything up to M2F-B2 (Result revisions), the
  test workflow and the rough Final Report (840 tests pass with it).
- Built: Project, Test Program (minimal), TCN, Test Execution (manual log,
  DCS data, running intervals, Excel log import), Test Result (components,
  pictures, plots, seal-face measurements, acceptance), Test Run Report
  (Customer and Engineering profiles, issued documents, Result revisions).
- The **Test Summary** step is covered by the Test Run Report: it has the
  content of the old Word "Dynamic Test Run Summary" (objective, seal
  configuration, conditions and results, leakage, logged data,
  measurements, pictures, conclusion). Confirmed 2026-10-13: the Test Run
  Report replaces the Test Summary; there is no separate summary document.
- The **Final Report** (project page → Final Report): texts, included runs,
  generated summary table, one section per run from the frozen records,
  draft PDF, and since 2026-10-14 issuing: `<project>R-R0`, `-R1`, … stored
  once, the earlier one Superseded, a reason from R1, refused while an
  included run has a Result revision in progress. The texts stay editable
  after issuing; the page says what changed since the issue. Missing:
  appendices (drawings, P&ID) and the Test Program texts it could start
  from (the Test Program holds acceptance requirements only).
- Validated on Windows: up to M2D and the Chromium report (2026-10-05).
  M2E, running intervals, log import, M2F-a, B1 and B2 are not.
  The automated tests pass on Windows and Linux on GitHub for 3fe4635
  (2026-10-13); trying those parts by hand on the workstation is still open.
- `data/` is **test data and can be thrown away**, but it is made from
  real material: real projects (for example 2026RSD06TL TCN001, from start
  to finish), real DCS exports, measurement files and photos. A change
  counts as working when it works on that data, not only in the automated
  tests.
- `data/` is on this machine only and kept out of git because of its size
  (about 60 MB for one full run, mostly original photos and DCS data;
  screens and reports already use a reduced copy of each photo).

## How we work

- Requests come directly from the engineer; no intermediate prompt writer.
- Commit only when told. Suggested, not yet decided: one commit per
  accepted milestone.
- Larger changes: proposal first, code after approval.

## Agreed plan, in order

1. **Tests on Windows at every push.** `.github/workflows/tests.yml` runs
   the test suite on a fresh checkout on Windows and Linux. Added
   2026-10-12.
2. **Rough Final Report.** Done 2026-10-12, to be tried on real projects.
   What it showed so far:
   - The run sections reuse the Customer Test Run Report as it is; their
     status line ("Preview", "Customer report") was replaced by a Source
     line (the Customer document, else "Final Result", and the Result
     revision) on 2026-10-14.
   - The summary table reads speed, medium and pressure from the
     conditions table by row name; a record field for them would be
     sturdier.
   - Only one run of the real data is final, so the report over several
     runs is proven by the automated tests only.
3. **Evidence corrections.** Decided and done 2026-10-14, the simple way:
   the manual log, DCS data, running intervals and log imports are locked
   while the Result is Final and open again, like the rest of the Result,
   while a revision is in progress. The revision reason says why; each final
   revision keeps its own frozen copy of the evidence, so earlier revisions
   and their documents never change. No per-correction entries with their
   own reason ("not vaccine manufacturing: change is not harmful").

Then, in no fixed order:

| Change | Size | Touches |
|---|---|---|
| Requirements flow one way, Program → TCN → Result, instead of being synced from the Result side | Medium | `results/requirements.py`, Test Program, TCN requirement changes |
| One change log for the whole app (who changed what, when) | Medium | New table, hooked into every save |
| Locks in one place instead of per-table checks | Small | `results/models.py`, `tcn/models.py` |
| Backup of `data/` to another disk, needed once the app holds records that must be kept | Small | Run script or a scheduled job |
| "On record" from an explicit list of what each revision froze, instead of by time added | Small | `results/models.py`, `results/records.py` |

## Left alone

Projects, Test Program and TCN screens and documents; DCS import, signal
mapping and running intervals; Excel log import; seal-face measurement
analysis; report profiles, frozen records, issued documents and revisions.

## Confirmed 2026-10-13

Choices made during implementation, answered by the engineer.

M2F-B2 (Result revisions):
1. A revision in progress cannot be discarded; finalizing it unchanged
   gives a revision with the same content. Agreed.
2. While revising, acceptance requirements are brought in step with the
   Test Program and TCN again, as in any Draft. Agreed.
3. "Cannot be deleted" goes by when an item was added, so it also covers
   unreviewed measurements that existed at finalization. Agreed.
4. The revision reason appears in the Engineering document history only,
   not in the Customer report. Agreed.

M2E (final report):
5. A manual-log interval counts as running only when the entries at both
   ends agree. Agreed.
6. Pre and Post inspection times default to the whole run. Agreed.
7. The TCN does not have to be issued to finalize a Result; it is shown as
   a notice only. Agreed for now.

Running intervals:
8. Samples inside a bridged dip count as running time but are left out of
   the min–max, because they are below the threshold. Agreed.
9. A manual/DCS difference close to a DCS start or stop is not listed as a
   discrepancy: changed from 5 to 10 minutes on 2026-10-13.
10. Each confirm, override or re-detect adds a record that is never
    changed. Agreed.

Other:
11. Excel log import: tested with the real workbook; the rows above the log
    table got in the way. Since 2026-10-13 only the log table is read: the
    comparison of the top rows with the run and its acknowledgement are
    gone.
12. DOCX was a mistake: documents are HTML rendered to PDF by Chromium.
    Removed from `CLAUDE.md`, `README.md`, the code and the tests on
    2026-10-13; `docs/requirements/` (the first design, built on Word
    templates) was deleted the same day.

## Open points

1. Code comments still cite section numbers of the M1 specification
   ("M1 spec §9.4", "AT-16"); the specification was deleted with
   `docs/requirements/` on 2026-10-13 and is in the git history only.

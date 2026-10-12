# TestLab roadmap

Where the project stands and what comes next. Written 2026-10-12; update it
at the end of each working session.

## Where we are

- `main` at `0522b99` holds everything up to M2F-B2 (Result revisions),
  pushed to GitHub. 823 tests pass.
- Built: Project, Test Program (minimal), TCN, Test Execution (manual log,
  DCS data, running intervals, Excel log import), Test Result (components,
  pictures, plots, seal-face measurements, acceptance), Test Run Report
  (Customer and Engineering profiles, issued documents, Result revisions).
- Not built: **Test Summary** and **Final Report**, the last two steps of
  the lifecycle.
- Validated on Windows: up to M2D and the Chromium report (2026-10-05).
  M2E, running intervals, log import, M2F-a, B1 and B2 are not.
- `data/` is **test data and can be thrown away**, but it is made from
  real material: real projects (for example 2026RSD06TL TCN001, from start
  to finish), real DCS exports, measurement files and photos. A change
  counts as working when it works on that data, not only in the automated
  tests.
- `data/` is on this machine only and kept out of git because of its size
  (about 60 MB for one full run, mostly photos and DCS data).

## How we work

- Requests come directly from the engineer; no intermediate prompt writer.
- Commit only when told. Suggested, not yet decided: one commit per
  accepted milestone.
- Larger changes: proposal first, code after approval.

## Agreed plan, in order

1. **Tests on Windows at every push.** A GitHub configuration file that
   runs the test suite on Windows. No application code changes.
2. **Rough Test Summary and Final Report.** A crude version of both, so the
   whole lifecycle exists end to end. Their needs decide the form of the
   changes below.
3. **Decide on evidence corrections, with real cases in hand.** Today the
   manual log, DCS data and running intervals are locked for good after the
   first Final. The alternative: a correction is a new entry that replaces
   the old one, with a reason, and a Result revision may then correct
   evidence too. About one milestone of work; only worth it if correcting
   evidence after Final is really needed.

Then, in no fixed order:

| Change | Size | Touches |
|---|---|---|
| Requirements flow one way, Program → TCN → Result, instead of being synced from the Result side | Medium | `results/requirements.py`, Test Program, TCN requirement changes |
| One change log for the whole app (who changed what, when) | Medium | New table, hooked into every save |
| Locks in one place instead of per-table checks | Small | `results/models.py`, `tcn/models.py` |
| Backup of `data/` to another disk, needed once the app holds records that must be kept | Small | Run script or a scheduled job |
| Reduced-size photo copies for screens and reports; original kept once | Small | Picture upload, report building |
| "On record" from an explicit list of what each revision froze, instead of by time added | Small | `results/models.py`, `results/records.py` |

## Left alone

Projects, Test Program and TCN screens and documents; DCS import, signal
mapping and running intervals; Excel log import; seal-face measurement
analysis; report profiles, frozen records, issued documents and revisions.

## Open points to confirm

Choices made during implementation that have not been confirmed.

M2F-B2 (Result revisions):
1. A revision in progress cannot be discarded; finalizing it unchanged
   gives a revision with the same content.
2. While revising, acceptance requirements are brought in step with the
   Test Program and TCN again, as in any Draft.
3. "Cannot be deleted" goes by when an item was added, so it also covers
   unreviewed measurements that existed at finalization.
4. The revision reason appears in the Engineering document history only,
   not in the Customer report.

M2E (final report):
5. A manual-log interval counts as running only when the entries at both
   ends agree.
6. Pre and Post inspection times default to the whole run.
7. The TCN does not have to be issued to finalize a Result; it is shown as
   a notice only.

Running intervals:
8. Samples inside a bridged dip count as running time but are left out of
   the min–max, because they are below the threshold.
9. A manual/DCS difference within 5 minutes of a DCS start or stop is not
   listed as a discrepancy.
10. Each confirm, override or re-detect adds a record that is never changed.

Other:
11. The Excel log import is still waiting for a test with the real TCN01
    workbook.
12. `CLAUDE.md` still says "DOCX generation is template-based"; documents
    are HTML rendered to PDF by Chromium since M2E.

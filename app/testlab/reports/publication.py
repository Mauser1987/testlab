"""Issuing the Final Report: R0, R1, … each stored once, the latest one Issued, the earlier ones Superseded.

    <report_no>-R<revision>          e.g. 2026RSD06TLR-R0, stored at projects/<project_no>/final_report/

Issuing renders the report as the draft would be rendered now (assembly.build) with the document's
identity, and stores the PDF with its SHA-256, the texts and the included runs (each with its Result
revision and Customer document). It is refused while an included run has a Result revision in
progress. Issuing again needs a reason; the earlier issue becomes Superseded. No PDF is ever
overwritten or deleted.
"""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from testlab.documents.run_report_context import _datetime
from testlab.documents.tcn_context import format_date
from testlab.results import records
from testlab.results.models import RecordIntegrityError
from testlab.tcn.permissions import can_issue_report

from . import assembly
from .models import FinalReport, FinalReportDocument


class PublicationError(Exception):
    """An issue the rules do not allow; the message says why."""


def identity(report, revision):
    return f"{report.report_no}-R{revision}"


def document_path(report, ident):
    return f"projects/{report.project.project_no}/final_report/{ident}.pdf"


def _person(user):
    return user.get_full_name() or user.username


def history(report, upcoming=None, superseding=None):
    """The issued documents of the report, oldest first; `upcoming` (a row) is the one being issued now."""
    rows = [{"identity": doc.identity, "revision": doc.revision, "status": "Superseded" if doc.pk == getattr(
        superseding, "pk", None) else doc.get_status_display(), "issued_on": format_date(
        timezone.localtime(doc.issued_at))} for doc in report.documents.order_by("revision")]  # fmt: skip
    return rows + ([upcoming] if upcoming else [])


def contents(report):
    """What an issue is rendered from: the texts and the included runs ({"result", "run_no", "revision"})."""
    texts = {name: getattr(report, name) for name in FinalReport.TEXT_FIELDS}
    runs = [{"result": result.pk, "run_no": result.test_run.display_no, "revision": result.revision.number}
            for result in assembly.included(report)]  # fmt: skip
    return texts, runs


def changed_since(document):
    """What differs between the issued document and the report as saved now: [] when nothing does."""
    texts, runs = contents(FinalReport.objects.select_related("project").get(pk=document.report_id))
    found = [FinalReport._meta.get_field(name).verbose_name.lower() for name in FinalReport.TEXT_FIELDS
             if texts[name] != document.texts.get(name, "")]  # fmt: skip
    issued_runs = [{key: run[key] for key in ("result", "run_no", "revision")} for run in document.runs]
    if runs != issued_runs:
        found.append("runs or their Result revisions")
    return found


def issue(report, user, reason=""):
    """Issue the next revision of the Final Report; returns the FinalReportDocument."""
    if not can_issue_report(user):
        raise PublicationError("You are not allowed to issue report documents.")
    reason = (reason or "").strip()
    written = []
    try:
        with transaction.atomic():
            report = FinalReport.objects.select_for_update().select_related("project").get(pk=report.pk)
            previous = report.documents.select_for_update().filter(status=FinalReportDocument.Status.ISSUED).first()
            latest = report.documents.aggregate(n=Max("revision"))["n"]
            number = 0 if latest is None else latest + 1
            if number > 0 and not reason:
                raise PublicationError(f"{identity(report, number - 1)} was issued before: give the reason for "
                                       f"issuing {identity(report, number)}.")  # fmt: skip
            now = timezone.now()
            ident = identity(report, number)
            upcoming = {"identity": ident, "revision": number, "status": "Issued",
                        "issued_on": format_date(timezone.localtime(now))}  # fmt: skip
            document = {"identity": ident, "revision": number, "issued_on": upcoming["issued_on"],
                        "issued_at": _datetime(now), "history": history(report, upcoming, previous)}  # fmt: skip
            try:
                context, assets, template = assembly.build(report.project, document)
            except assembly.AssemblyError as error:
                raise PublicationError(str(error)) from error
            content = template.render_pdf(context, assets)
            name = records._save_new(document_path(report, ident), content, written)
            texts, _ = contents(report)
            runs = [{"result": run["result"], "run_no": run["summary"]["run_no"], "revision": run["revision"],
                     "document": run["document"]} for run in context["runs"]]  # fmt: skip
            if previous is not None:  # one issued document per report
                previous.status, previous.status_changed_at = FinalReportDocument.Status.SUPERSEDED, now
                previous.save()
            doc = FinalReportDocument.objects.create(
                report=report, revision=number, identity=ident, reason=reason, texts=texts, runs=runs, file=name,
                sha256=records.sha256(content), size=len(content), template_sha256=template.sha256, issued_at=now,
                issued_by=user,
            )  # fmt: skip
            if previous is not None:
                previous.superseded_by = doc
                previous.save()
            return doc
    except BaseException:
        for name in written:
            records.storage().delete(name)
        raise


def document_bytes(document):
    """The stored PDF, byte for byte; refused when it does not match its SHA-256."""
    with document.file.open("rb") as stored:
        content = stored.read()
    if records.sha256(content) != document.sha256:
        raise RecordIntegrityError(f"{document.identity} does not match its SHA-256; it is not served.")
    return content

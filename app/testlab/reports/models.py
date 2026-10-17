"""Final Report of a project: the texts the engineer writes, the runs it includes, the documents issued.

Everything else in the report comes from the frozen records of the included
Results (results/records.py): the report holds no copy of test data.

    Draft PDF            rendered on request from what is saved, marked DRAFT, never stored
    FinalReportDocument  an issued revision R0, R1, …: the PDF stored once with what went into it

The texts and the included runs stay editable after issuing: the issued PDF
is the controlled document, and the next issue (with a reason) supersedes it.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver

from testlab.projects.models import Project
from testlab.results.models import RecordIntegrityError, TestResult


class FinalReport(models.Model):
    project = models.OneToOneField(Project, on_delete=models.PROTECT, related_name="final_report")
    introduction = models.TextField("Introduction", blank=True)
    executive_summary = models.TextField("Executive summary", blank=True)
    field_conditions = models.TextField("Field conditions", blank=True)
    test_conditions = models.TextField("Test conditions", blank=True)
    conclusion = models.TextField("Conclusion", blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    TEXT_FIELDS = ("introduction", "executive_summary", "field_conditions", "test_conditions", "conclusion")

    def __str__(self):
        return f"Final Report {self.report_no}"

    @property
    def report_no(self):
        return f"{self.project.project_no}R"


class FinalReportRun(models.Model):
    """A Result included in the Final Report, in report order."""

    report = models.ForeignKey(FinalReport, on_delete=models.CASCADE, related_name="runs")
    result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["report", "result"], name="final_report_run_once")]

    def __str__(self):
        return f"{self.report}: {self.result}"


class FinalReportDocument(models.Model):
    """An issued Final Report: one rendering, stored once with its SHA-256 and what it was rendered from.

    Identity <report_no>-R<revision>, e.g. 2026RSD06TLR-R0. Issued: the controlled publication; one per
    report. Superseded: replaced by the next revision. The PDF and what it was rendered from never change.
    """

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        SUPERSEDED = "superseded", "Superseded"

    report = models.ForeignKey(FinalReport, on_delete=models.PROTECT, related_name="documents")
    revision = models.PositiveSmallIntegerField()
    identity = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ISSUED)
    reason = models.TextField(blank=True)  # why it was issued again: required from R1
    texts = models.JSONField(default=dict)  # {field: text} as issued
    runs = models.JSONField(default=list)  # [{"result", "run_no", "revision", "document"}] in report order
    file = models.FileField(max_length=255)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    template_sha256 = models.CharField(max_length=64, blank=True)
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status_changed_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["report", "revision"]
        constraints = [
            models.UniqueConstraint(fields=["report", "revision"], name="one_final_report_revision"),
            models.UniqueConstraint(fields=["report"], condition=Q(status="issued"),
                                    name="one_issued_final_report"),
            models.CheckConstraint(condition=Q(revision=0) | ~Q(reason=""), name="final_report_reissue_has_reason"),
        ]  # fmt: skip

    def __str__(self):
        return self.identity


@receiver(pre_save, sender=FinalReportDocument, dispatch_uid="issued_final_report")
def _guard_document(sender, instance, **kwargs):
    """Only an issued document changes, and only to Superseded by its successor."""
    if instance.pk is None:
        return
    stored = FinalReportDocument.objects.filter(pk=instance.pk).values().first()
    if stored is None:
        return
    changed = {f.attname for f in FinalReportDocument._meta.concrete_fields
               if stored[f.attname] != getattr(instance, f.attname)}  # fmt: skip
    linking = (changed == {"superseded_by_id"} and stored["status"] == sender.Status.SUPERSEDED
               and stored["superseded_by_id"] is None)  # a superseded issue gets its successor once  # fmt: skip
    if not linking and (changed - {"status", "status_changed_at"} or stored["status"] != sender.Status.ISSUED):
        raise RecordIntegrityError(f"{instance} is issued: it may only become superseded, and nothing else of it "
                                   "changes.")  # fmt: skip


@receiver(pre_delete, sender=FinalReportDocument, dispatch_uid="issued_final_report_delete")
def _guard_document_delete(sender, instance, **kwargs):
    raise RecordIntegrityError(f"{instance} is a controlled record and cannot be deleted.")

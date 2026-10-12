"""Final Report of a project (rough version): the texts the engineer writes and the runs it includes.

Everything else in the report comes from the frozen records of the included
Results (results/records.py): the report holds no copy of test data. It is a
draft only for now — not issued, not frozen, no revisions.
"""

from django.conf import settings
from django.db import models

from testlab.projects.models import Project
from testlab.results.models import TestResult


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

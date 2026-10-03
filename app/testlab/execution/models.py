"""Evidence recorded while a Test Run is executed (M2A): Actual, not Instructed.

Both sources belong to the TestRun, never to a TCN revision, and stay
separate; they meet on the run's timeline (absolute timestamps):

    TestRun
    ├── ManualLogEntry → ManualMeasurement   readings taken by a technician
    └── DcsDataset                           a LabVIEW/DCS export, kept unchanged

Deleting a run's evidence is never a side effect: the foreign keys to
TestRun protect it (a draft TCN whose run holds evidence cannot be deleted).

Whether evidence may be recorded for a run whose TCN is still a Draft is a
lifecycle/authorization rule, deliberately not a model constraint: it is
allowed during development and validation (intentional temporary policy) and
will be refused in production (views.recording_refusal,
TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN).
"""

from django.conf import settings
from django.db import models

from testlab.tcn.models import TestRun


class ManualLogEntry(models.Model):
    """One manual observation at a point in the run: readings, an event note, or both.

    Not an Excel row: date/time is one value, elapsed hours and leakage
    rates are calculated (manual_log.py), the person is the logged-in user.

    The log is also the run's event timeline (M2B): an entry with a category
    and/or a note is an observation or event (flow adjusted, test stopped,
    abnormal noise, …). Its absolute time places it on the DCS time axis, so
    events can later be drawn as plot markers without another model.
    """

    class Category(models.TextChoices):
        START = "start", "Start / restart"
        STOP = "stop", "Stop"
        ADJUSTMENT = "adjustment", "Adjustment"
        LEAKAGE_COLLECTION = "leakage_collection", "Leakage collection"
        ABNORMAL = "abnormal", "Abnormal observation"
        INSPECTION = "inspection", "Inspection"
        OTHER = "other", "Other"

    test_run = models.ForeignKey(TestRun, on_delete=models.PROTECT, related_name="manual_log_entries")
    observed_at = models.DateTimeField("Date / time")
    note = models.TextField("Note / event", blank=True)
    category = models.CharField("Event", max_length=20, choices=Category.choices, blank=True)
    # Leakage is collected since the previous reading (legacy practice). When the
    # collection did not start at the previous reading, the technician enters the
    # collection period; it then replaces the time since the previous reading.
    leakage_hours = models.DecimalField(
        "Leakage collected over", max_digits=8, decimal_places=3, null=True, blank=True,
        help_text="Hours. Leave empty: since the previous reading.",
    )
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    entered_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["test_run", "observed_at", "pk"]
        indexes = [models.Index(fields=["test_run", "observed_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(leakage_hours__isnull=True) | models.Q(leakage_hours__gt=0),
                name="leakage_hours_positive",
            ),
        ]

    def __str__(self):
        return f"{self.test_run} reading {self.observed_at:%d-%b-%Y %H:%M}"


class ManualMeasurement(models.Model):
    """One entered value. `code` is from measurements.py; the unit is stored as entered."""

    entry = models.ForeignKey(ManualLogEntry, on_delete=models.CASCADE, related_name="measurements")
    code = models.CharField(max_length=40)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=10)

    class Meta:
        ordering = ["entry", "pk"]
        constraints = [models.UniqueConstraint(fields=["entry", "code"], name="one_value_per_code_per_entry")]

    def __str__(self):
        return f"{self.code} = {self.value} {self.unit}"


class DcsDataset(models.Model):
    """A LabVIEW/DCS export attached to a run.

    The uploaded file is stored unchanged (raw_file, sha256) and stays the
    source of truth. What the import learned from it is stored here; samples
    are not stored as rows. A derived column file (columns_file) holds the
    parsed numbers for fast plotting and is rebuilt from the raw file when
    missing.
    """

    test_run = models.ForeignKey(TestRun, on_delete=models.PROTECT, related_name="dcs_datasets")
    raw_file = models.FileField(max_length=255)
    original_name = models.CharField("Source file name", max_length=255)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    columns_file = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    # Parsed structure (labview.py)
    encoding = models.CharField(max_length=20)
    delimiter = models.CharField(max_length=4)
    header_lines = models.JSONField(default=list)  # metadata lines before the signal names, as read
    signals = models.JSONField(default=list)  # [{"column", "name", "unit"}], every column in file order
    time_column = models.PositiveSmallIntegerField()
    time_unit = models.CharField(max_length=20, blank=True)  # unit as written in the file, e.g. "Hrs"
    sample_count = models.PositiveIntegerField()
    time_start_h = models.FloatField()
    time_end_h = models.FloatField()
    recording_started_at = models.DateTimeField(null=True, blank=True)
    recording_start_note = models.CharField(max_length=200, blank=True)  # how the start was determined, or why not
    warnings = models.JSONField(default=list)

    class Meta:
        ordering = ["test_run", "imported_at", "pk"]

    def __str__(self):
        return self.original_name

    @property
    def duration_h(self):
        return self.time_end_h - self.time_start_h

    def value_signals(self):
        return [signal for signal in self.signals if signal["column"] != self.time_column]

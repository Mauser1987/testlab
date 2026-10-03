"""Test Result of a Test Run (M2B): inspection evidence and engineering assessment.

    TCN                    INSTRUCTED
    Manual log + DCS       ACTUAL EXECUTION DATA (testlab.execution)
    Test Result            INSPECTION EVIDENCE + ENGINEERING ASSESSMENT (here)

    TestRun ── TestResult (one-to-one; never a TCN revision)
               ├── ResultComponent      a physical part inspected: position + component (inspection.py)
               │   └── InspectionMeasurement   Pre and Post as entered; Δ and wear are calculated
               ├── ResultImage          picture evidence, original file kept unchanged
               ├── ResultPlot           a DCS plot: its definition (reproducible) + the report image (plots.py)
               └── AcceptanceItem       criterion, requirement, actual, assessment, remark

Nothing the manual log or the DCS data already holds is stored again:
leakage totals, average leakage rate, logged period and wear rate are
derived when shown (evidence.py, acceptance.py). Events are manual log
entries with a category (execution.ManualLogEntry).

The Result keeps its own copy of what it starts from (components, the
materials as instructed on the TCN at that moment), so later edits of the
project defaults or of the TCN never change it.

Lifecycle: Draft only. A Result may exist while the run's TCN is a Draft —
intentional development-phase policy; production will refuse it through the
same lifecycle/authorization rule as the manual log
(execution.views.recording_refusal, TESTLAB_EXECUTION_REQUIRES_ISSUED_TCN),
not through these models. Controlled issue/revision of results is not part
of M2B.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from testlab.execution.models import DcsDataset
from testlab.projects.arrangements import SealRole
from testlab.tcn.models import TestRun

from . import inspection
from .inspection import Component


class TestResult(models.Model):
    __test__ = False  # not a pytest test class

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"

    test_run = models.OneToOneField(TestRun, on_delete=models.PROTECT, related_name="result")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    # Engineer-authored narrative (legacy report: commentary under the plots, Test Conclusion).
    observations = models.TextField(
        "Observations", blank=True,
        help_text="What was seen during the run and in the logged data.",
    )
    conclusion = models.TextField("Conclusion", blank=True)
    recommendation = models.TextField("Recommendation", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status="draft"), name="result_status_valid")]

    def __str__(self):
        return f"Result of {self.test_run}"


class ResultComponent(models.Model):
    """A physical part inspected for the Result, e.g. IB Rotor, with its identity as fitted."""

    result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name="components")
    position = models.CharField(max_length=10, choices=SealRole.choices, blank=True)  # "": whole cartridge
    component = models.CharField(max_length=10, choices=Component.choices)
    # As fitted for the run (legacy "Seal Configuration" table).
    part_no = models.CharField("Part drawing", max_length=60, blank=True)
    material = models.CharField("Material", max_length=100, blank=True)
    condition = models.CharField("Face condition", max_length=60, blank=True, help_text="e.g. New, Re-lapped")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["result", "position", "component"], name="one_component_identity"),
            models.CheckConstraint(
                condition=Q(component="sleeve") | ~Q(position=""), name="only_sleeve_without_position"
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        return inspection.identity_label(self.position, self.component)

    @property
    def sort_key(self):
        return inspection.sort_key(self.position, self.component)

    @property
    def description(self):
        return inspection.COMPONENT_DESCRIPTIONS[Component(self.component)]

    def quantities(self):
        return inspection.quantities_for(self.component)

    def is_empty(self):
        return not (self.measurements.exists() or self.images.exists())


class InspectionMeasurement(models.Model):
    """Pre-test and post-test value of one quantity on one component, as entered.

    Either value may be missing (not measured). Δ and wear are never stored.
    """

    component = models.ForeignKey(ResultComponent, on_delete=models.PROTECT, related_name="measurements")
    quantity = models.CharField(max_length=30)
    pre_value = models.DecimalField("Pre", max_digits=16, decimal_places=6, null=True, blank=True)
    post_value = models.DecimalField("Post", max_digits=16, decimal_places=6, null=True, blank=True)
    unit = models.CharField(max_length=10)  # stored as entered, with the value
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["component", "quantity"], name="one_value_pair_per_quantity"),
            models.CheckConstraint(
                condition=Q(pre_value__isnull=False) | Q(post_value__isnull=False), name="pre_or_post_entered"
            ),
        ]

    def __str__(self):
        return f"{self.component} {self.quantity}"

    @property
    def definition(self):
        return inspection.quantity(self.quantity)

    @property
    def delta(self):
        return inspection.delta(self.pre_value, self.post_value)

    @property
    def wear(self):
        return inspection.wear(self.quantity, self.pre_value, self.post_value)


class ResultImage(models.Model):
    """A picture of the Result. The uploaded file is kept byte for byte (sha256);
    a display copy (preview) is derived from it and rebuilt when missing."""

    class Category(models.TextChoices):
        CROSS_SECTION = "cross_section", "Seal cross section"
        PRE_TEST = "pre_test", "Pre-test"
        POST_TEST = "post_test", "Post-test"
        OTHER = "other", "Other / supporting"

    result = models.ForeignKey(TestResult, on_delete=models.PROTECT, related_name="images")
    category = models.CharField(max_length=20, choices=Category.choices)
    # Optional: a cross section or an overall view belongs to no single component.
    component = models.ForeignKey(
        ResultComponent, on_delete=models.PROTECT, null=True, blank=True, related_name="images"
    )
    caption = models.CharField("Caption / remark", max_length=300, blank=True)
    order = models.PositiveIntegerField(default=0)

    file = models.FileField(max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    image_format = models.CharField(max_length=10)  # as detected, e.g. JPEG, PNG
    preview_file = models.CharField(max_length=255, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["result", "category", "order", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(category__in=["cross_section", "pre_test", "post_test", "other"]),
                name="result_image_category_valid",
            ),
        ]

    def __str__(self):
        return self.original_name


class ResultPlot(models.Model):
    """A plot of a DCS dataset added to the Result.

    The definition is what reproduces the plot from the stored dataset:
    source dataset, signals with their axis, time window and axis ranges
    (null = automatic / whole recording). The image is the rendering of that
    definition for the report, made by the same plot code as the DCS viewer;
    it is never the source of truth and is replaced when the plot is
    updated from the viewer.
    """

    result = models.ForeignKey(TestResult, on_delete=models.PROTECT, related_name="plots")
    dataset = models.ForeignKey(DcsDataset, on_delete=models.PROTECT, related_name="result_plots")
    order = models.PositiveIntegerField(default=0)
    caption = models.CharField("Caption", max_length=300, blank=True)

    # Definition (plots.py validates it against the dataset)
    signals = models.JSONField()  # [{"column", "name", "unit", "axis": "y" | "y2"}], in legend order
    time_start_h = models.FloatField(null=True, blank=True)  # dataset time axis [h]; null: whole recording
    time_end_h = models.FloatField(null=True, blank=True)
    y_min = models.FloatField(null=True, blank=True)  # left axis; null: automatic
    y_max = models.FloatField(null=True, blank=True)
    y2_min = models.FloatField(null=True, blank=True)  # right axis; null: automatic
    y2_max = models.FloatField(null=True, blank=True)

    # Report image, rendered from the definition
    image = models.FileField(max_length=255)
    image_sha256 = models.CharField(max_length=64)
    image_width = models.PositiveIntegerField()
    image_height = models.PositiveIntegerField()
    # How the data was reduced for the image: {"samples_in_window", "points_per_signal", "decimated"}
    rendering = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["result", "order", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(time_start_h__isnull=True, time_end_h__isnull=True)
                | Q(time_start_h__isnull=False, time_end_h__isnull=False, time_start_h__lt=models.F("time_end_h")),
                name="plot_time_window_valid",
            ),
            models.CheckConstraint(
                condition=Q(y_min__isnull=True, y_max__isnull=True)
                | Q(y_min__isnull=False, y_max__isnull=False, y_min__lt=models.F("y_max")),
                name="plot_y_range_valid",
            ),
            models.CheckConstraint(
                condition=Q(y2_min__isnull=True, y2_max__isnull=True)
                | Q(y2_min__isnull=False, y2_max__isnull=False, y2_min__lt=models.F("y2_max")),
                name="plot_y2_range_valid",
            ),
        ]

    def __str__(self):
        return self.caption or f"Plot of {self.dataset}"

    def definition(self):
        """The plot definition as the DCS viewer reads it back."""
        pair = lambda a, b: None if a is None else [a, b]  # noqa: E731
        return {
            "id": self.pk,
            "dataset": self.dataset_id,
            "signals": self.signals,
            "time_range": pair(self.time_start_h, self.time_end_h),
            "y_range": pair(self.y_min, self.y_max),
            "y2_range": pair(self.y2_min, self.y2_max),
            "caption": self.caption,
        }


class Assessment(models.TextChoices):
    PASS = "pass", "Pass"
    FAIL = "fail", "Fail"
    NOT_EVALUATED = "not_evaluated", "Not evaluated"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class AcceptanceItem(models.Model):
    """One acceptance criterion of the Result: requirement, actual, assessment, remark.

    The actual is either typed by the engineer (basis manual) or derived
    from structured evidence (acceptance.py), never both. `assessment` is the
    engineer's decision; when it is empty, Pass/Fail is derived only for a
    numeric limit on a derived actual, otherwise the item is Not evaluated.
    """

    class Basis(models.TextChoices):
        MANUAL = "manual", "Entered by engineer"
        LEAKAGE_RATE = "leakage_rate", "Average leakage rate (manual log)"
        WEAR_RATE = "wear_rate", "Face wear rate (face length, Pre − Post)"
        LOGGED_HOURS = "logged_hours", "Logged period, clock time"

    class Comparison(models.TextChoices):
        AT_MOST = "<=", "≤"
        AT_LEAST = ">=", "≥"

    result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name="acceptance_items")
    order = models.PositiveIntegerField(default=0)
    criterion = models.CharField("Criterion", max_length=120)
    basis = models.CharField("Actual from", max_length=20, choices=Basis.choices, default=Basis.MANUAL)
    position = models.CharField("Seal", max_length=10, choices=SealRole.choices, blank=True)  # leakage_rate
    component = models.ForeignKey(  # wear_rate
        ResultComponent, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    comparison = models.CharField(max_length=2, choices=Comparison.choices, blank=True)
    limit = models.DecimalField("Limit", max_digits=24, decimal_places=12, null=True, blank=True)
    requirement_text = models.CharField(
        "Requirement", max_length=200, blank=True, help_text="When the requirement is not a numeric limit."
    )
    unit = models.CharField(max_length=20, blank=True)
    actual_text = models.CharField("Actual", max_length=200, blank=True)  # basis manual only
    assessment = models.CharField(max_length=20, choices=Assessment.choices, blank=True)
    remark = models.TextField("Engineer remark", blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["result", "order", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(assessment__in=["", "pass", "fail", "not_evaluated", "not_applicable"]),
                name="acceptance_assessment_valid",
            ),
            models.CheckConstraint(
                condition=Q(basis__in=["manual", "leakage_rate", "wear_rate", "logged_hours"]),
                name="acceptance_basis_valid",
            ),
            models.CheckConstraint(
                condition=Q(comparison="", limit__isnull=True) | (~Q(comparison="") & Q(limit__isnull=False)),
                name="acceptance_comparison_with_limit",
            ),
        ]

    def __str__(self):
        return self.criterion

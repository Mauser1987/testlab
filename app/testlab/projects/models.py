import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction

from . import conditions
from .arrangements import (
    Arrangement,
    SealRole,
    applicable_monitored_parameters,
    applicable_roles,
    canonical_order,
    seal_under_test_roles,
)

project_no_characters = RegexValidator(
    r"^[A-Za-z0-9._-]+$",
    "Use only letters, digits, '-', '_' and '.' (the project number is used in file names).",
)


def normalize_project_no(value):
    return (value or "").strip().upper()


def project_no_format_warning(project_no):
    """Return a warning if project_no does not follow the lab convention (V1).

    The format is a convention only and never blocks saving.
    """
    pattern = settings.TESTLAB_PROJECT_NO_PATTERN
    if pattern and not re.fullmatch(pattern, project_no):
        return f"Project number {project_no} does not follow the usual format (e.g. 2026RSD03TL)."
    return None


class Project(models.Model):
    # Stored upper-case, so the unique constraint is case-insensitive (V1).
    project_no = models.CharField(
        "Project no.",
        max_length=20,
        unique=True,
        validators=[project_no_characters],
        error_messages={"unique": "A project with this number already exists."},
    )
    description = models.CharField(
        "Description",
        max_length=200,
        help_text="Printed on the TCN as “Project Description”, e.g. ADNOC BAB UHTW/UHTW 4.750/4.750.",
    )
    customer = models.CharField("Customer", max_length=200, blank=True)
    # Project defaults for new TCNs. Created with the project; TCNs take a
    # copy, so editing the defaults never changes an existing TCN.
    default_setup = models.OneToOneField(
        "RunSetup", on_delete=models.PROTECT, related_name="default_for_project", editable=False
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-project_no"]

    def __str__(self):
        return self.project_no

    def save(self, *args, **kwargs):
        self.project_no = normalize_project_no(self.project_no)
        self.description = self.description.strip()
        self.customer = self.customer.strip()
        with transaction.atomic():
            if self.default_setup_id is None:
                self.default_setup = RunSetup.create_with_positions()
            super().save(*args, **kwargs)


def _text(verbose_name, max_length):
    return models.CharField(verbose_name, max_length=max_length, blank=True)


class RunSetup(models.Model):
    """The copyable technical block of a Test Run (M1 spec §1.2).

    Used as a project's defaults (Project.default_setup) and, from commit 5,
    as each TCN revision's own copy. Holds the seal arrangement under test,
    the optional Plug Seal, and the run conditions grouped by circuit
    (see conditions.py).
    """

    arrangement = models.CharField(
        "Seal arrangement", max_length=24, choices=Arrangement.choices, default=Arrangement.DUAL_PRESSURIZED
    )
    # Plug Seal: process-side test equipment, not part of the arrangement.
    plug_seal_present = models.BooleanField("Plug Seal installed", default=False)
    reference_drawing = _text("Reference drawing", 200)
    run_description = models.TextField("Test Run description", blank=True)

    # Common run conditions
    test_unit = _text("Test unit", 20)
    duration = _text("Duration", 50)
    speed = _text("Speed", 50)

    # Process / test side
    process_medium = _text("Process medium", 100)
    process_pressure = _text("Process pressure", 50)
    process_inlet_temperature = _text("Process inlet temperature", 50)
    process_flow = _text("Process flow", 50)

    # Mechanical-seal support circuit: barrier, buffer or flush (any arrangement)
    seal_support_medium = _text("Seal-support medium", 100)
    seal_support_pressure = _text("Seal-support pressure", 50)
    seal_support_inlet_temperature = _text("Seal-support inlet temperature", 50)
    seal_support_flow = _text("Seal-support flow", 50)

    # Plug Seal circuit (only when plug_seal_present)
    plug_medium = _text("Plug Seal medium", 100)
    plug_pressure = _text("Plug Seal pressure", 50)
    plug_inlet_temperature = _text("Plug Seal inlet temperature", 50)
    plug_flow = _text("Plug Seal flow", 50)

    monitored_parameters = models.JSONField("Parameters to log", default=list, blank=True)

    TEXT_FIELDS = (
        ["reference_drawing", "run_description"]
        + conditions.COMMON_FIELDS
        + conditions.PROCESS_FIELDS
        + conditions.SEAL_SUPPORT_FIELDS
        + conditions.PLUG_FIELDS
    )

    def __str__(self):
        return f"RunSetup {self.pk} ({self.get_arrangement_display()}{' + Plug Seal' if self.plug_seal_present else ''})"

    @classmethod
    def create_with_positions(cls, **fields):
        """Create a setup with exactly the applicable (empty) seal positions."""
        with transaction.atomic():
            setup = cls.objects.create(**fields)
            for role in setup.applicable_roles():
                setup.positions.create(role=role)
        return setup

    def applicable_roles(self):
        return applicable_roles(self.arrangement, self.plug_seal_present)

    def seal_under_test_positions(self):
        roles = seal_under_test_roles(self.arrangement)
        positions = {p.role: p for p in self.positions.all()}
        return [positions[role] for role in roles if role in positions]

    def plug_seal_position(self):
        return self.positions.filter(role=SealRole.PLUG).first()

    def normalize(self):
        """Trim text and remove repeated units (V8). Returns user notices."""
        notices = []
        for field in self.TEXT_FIELDS:
            value = getattr(self, field) or ""
            # The run description keeps its indentation; only trailing space goes.
            value = value.rstrip() if field == "run_description" else value.strip()
            stripped = conditions.strip_repeated_unit(field, value)
            if stripped != value:
                notices.append(
                    f"{self._meta.get_field(field).verbose_name}: “{value}” saved as “{stripped}” "
                    f"(the unit is printed automatically)."
                )
            setattr(self, field, stripped)
        # Sort valid codes into canonical order (V7); invalid ones are reported by clean().
        if self.arrangement in Arrangement.values and isinstance(self.monitored_parameters, list):
            applicable = applicable_monitored_parameters(self.arrangement, self.plug_seal_present)
            if set(self.monitored_parameters) <= set(applicable):
                self.monitored_parameters = canonical_order(set(self.monitored_parameters))
        return notices

    def clean(self):
        self.normalization_notices = self.normalize()
        errors = {}
        # V6: Plug Seal conditions only exist with a Plug Seal. Seal-support
        # values are valid for every arrangement, including single.
        if not self.plug_seal_present:
            filled = [f for f in conditions.PLUG_FIELDS if getattr(self, f)]
            if filled:
                errors["plug_seal_present"] = "Plug Seal conditions are filled in but no Plug Seal is installed."
        # V7
        if not isinstance(self.monitored_parameters, list):
            errors["monitored_parameters"] = "Must be a list of parameter codes."
        elif self.arrangement in Arrangement.values:
            applicable = applicable_monitored_parameters(self.arrangement, self.plug_seal_present)
            invalid = [c for c in self.monitored_parameters if c not in applicable]
            if invalid:
                errors["monitored_parameters"] = f"Not applicable to this configuration: {', '.join(invalid)}."
        if errors:
            raise ValidationError(errors)

    def validate_positions(self):
        """V5: exactly the positions required by arrangement and Plug Seal."""
        expected = self.applicable_roles()
        actual = sorted(self.positions.values_list("role", flat=True))
        if actual != sorted(expected):
            raise ValidationError(
                f"Seal positions {actual} do not match {self.get_arrangement_display()}"
                f"{' + Plug Seal' if self.plug_seal_present else ''} (expected {sorted(expected)})."
            )

    def save(self, *args, **kwargs):
        self.normalize()
        super().save(*args, **kwargs)


class SealPosition(models.Model):
    """One seal of a RunSetup (M1 spec §1.3).

    Roles test / inboard / outboard belong to the mechanical seal arrangement
    under test. Role plug is the Plug Seal: process-side simulation/test
    equipment, not a stage of a dual seal; it shares this table only because
    it is described by the same four fields.
    """

    setup = models.ForeignKey(RunSetup, on_delete=models.CASCADE, related_name="positions")
    role = models.CharField(max_length=10, choices=SealRole.choices)
    seal_type_size = _text("Seal type and size", 100)
    stationary_face = _text("Stationary seal face", 100)
    rotating_face = _text("Rotating seal face", 100)
    springs = _text("Spring(s)", 100)

    DESCRIPTIVE_FIELDS = ["seal_type_size", "stationary_face", "rotating_face", "springs"]

    class Meta:
        constraints = [models.UniqueConstraint(fields=["setup", "role"], name="unique_role_per_setup")]

    def __str__(self):
        return self.get_role_display()

    @property
    def is_plug_seal(self):
        return self.role == SealRole.PLUG

    def is_empty(self):
        return not any(getattr(self, f) for f in self.DESCRIPTIVE_FIELDS)

    def save(self, *args, **kwargs):
        for field in self.DESCRIPTIVE_FIELDS:
            setattr(self, field, (getattr(self, field) or "").strip())
        super().save(*args, **kwargs)

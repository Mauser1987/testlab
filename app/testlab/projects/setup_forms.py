"""Shared run setup form (M1 spec §6): project defaults (S5) and TCN
drafts (S7).

All four seal positions and the Process Conditions are always part of the
posted form; the ones that do not apply to the chosen configuration are kept
as hidden inputs (Process Conditions only apply with the Plug Seal).
Switching back and forth before saving therefore loses nothing, and saving
asks for confirmation before non-empty data that no longer applies is
discarded (§5.3). Choosing single installs the Plug Seal: a single seal
cannot be tested without it.
"""

from django import forms
from django.db import transaction

from . import conditions
from .arrangements import (
    ALL_MONITORED_PARAMETERS,
    PROCESS_PARAMETERS,
    SEAL_SUPPORT_PARAMETERS,
    Arrangement,
    SealRole,
    applicable_monitored_parameters,
    applicable_roles,
    canonical_order,
    parameter_label,
    plug_seal_required,
    role_parameters,
    seal_support_label,
    seal_under_test_roles,
)
from .models import RunSetup, SealPosition

RECONFIGURE = {"data-reconfigure": ""}


class RunSetupForm(forms.ModelForm):
    monitored_parameters = forms.MultipleChoiceField(
        choices=[(code, code) for code in ALL_MONITORED_PARAMETERS], required=False
    )

    class Meta:
        model = RunSetup
        fields = (
            ["arrangement", "plug_seal_present", "reference_drawing", "run_description"]
            + conditions.COMMON_FIELDS
            + conditions.PROCESS_FIELDS
            + conditions.SEAL_SUPPORT_FIELDS
            + ["monitored_parameters"]
        )
        widgets = {
            "arrangement": forms.RadioSelect(attrs=RECONFIGURE),
            "plug_seal_present": forms.CheckboxInput(attrs=RECONFIGURE),
            "run_description": forms.Textarea(attrs={"rows": 14, "cols": 100, "class": "mono"}),
            "reference_drawing": forms.TextInput(attrs={"size": 50}),
        }

    def clean(self):
        cleaned = super().clean()
        arrangement = cleaned.get("arrangement")
        # V16: a single seal is tested with the Plug Seal, whatever was posted.
        if plug_seal_required(arrangement):
            cleaned["plug_seal_present"] = True
        # Values that no longer apply are dropped here; RunSetupEditor has
        # already asked for confirmation when they were non-empty.
        if not cleaned.get("plug_seal_present"):
            for field in conditions.PROCESS_FIELDS:
                cleaned[field] = ""
        if arrangement in Arrangement.values:
            applicable = applicable_monitored_parameters(arrangement, cleaned.get("plug_seal_present"))
            cleaned["monitored_parameters"] = canonical_order(
                {code for code in cleaned.get("monitored_parameters", []) if code in applicable}
            )
        return cleaned


class SealPositionForm(forms.ModelForm):
    class Meta:
        model = SealPosition
        fields = SealPosition.DESCRIPTIVE_FIELDS


class RunSetupEditor:
    """Binds a RunSetupForm and one SealPositionForm per role."""

    def __init__(self, setup, data=None):
        self.setup = setup
        self.form = RunSetupForm(data, instance=setup)
        existing = {position.role: position for position in setup.positions.all()}
        self.position_forms = {
            role: SealPositionForm(data, instance=existing.get(role), prefix=role) for role in SealRole
        }
        arrangement = self.form["arrangement"].value()
        self.arrangement = arrangement if arrangement in Arrangement.values else setup.arrangement
        self.plug_seal_required = plug_seal_required(self.arrangement)
        self.plug_seal_present = self.plug_seal_required or bool(self.form["plug_seal_present"].value())
        self.roles = applicable_roles(self.arrangement, self.plug_seal_present)
        self.show_errors = False
        self.confirmation_required = False

    # --- display helpers for the template ---

    @property
    def seal_support_label(self):
        return seal_support_label(self.arrangement)

    @property
    def seal_under_test_columns(self):
        return [(SealRole(role).label, self.position_forms[role]) for role in seal_under_test_roles(self.arrangement)]

    @property
    def position_rows(self):
        columns = self.seal_under_test_columns
        return [
            (SealPosition._meta.get_field(field).verbose_name, [form[field] for _, form in columns])
            for field in SealPosition.DESCRIPTIVE_FIELDS
        ]

    @property
    def plug_seal_form(self):
        return self.position_forms[SealRole.PLUG] if self.plug_seal_present else None

    @property
    def hidden_position_forms(self):
        return [form for role, form in self.position_forms.items() if role not in self.roles]

    @property
    def condition_columns(self):
        """(heading, hint, fields): Process Conditions (with the Plug Seal only), then seal support."""
        columns = []
        if self.plug_seal_present:
            columns.append(("Process", "established with the Plug Seal", conditions.PROCESS_FIELDS))
        support_hint = "optional, e.g. Plan 23" if self.arrangement == Arrangement.SINGLE else ""
        columns.append((self.seal_support_label, support_hint, conditions.SEAL_SUPPORT_FIELDS))
        return columns

    @property
    def condition_rows(self):
        labels = ["Medium", "Pressure [barg]", "Inlet temperature [°C]", "Flow [l/min]"]
        return [
            (label, [self.form[fields[i]] for _, _, fields in self.condition_columns])
            for i, label in enumerate(labels)
        ]

    @property
    def hidden_condition_fields(self):
        return [] if self.plug_seal_present else [self.form[f] for f in conditions.PROCESS_FIELDS]

    @property
    def parameter_groups(self):
        checked = set(self.form["monitored_parameters"].value() or [])
        groups = [("Process", PROCESS_PARAMETERS)] if self.plug_seal_present else []
        groups.append((self.seal_support_label, SEAL_SUPPORT_PARAMETERS))
        groups += [(SealRole(role).label, role_parameters(role)) for role in SealRole if role in self.roles]
        return [
            (title, [(code, parameter_label(code), code in checked) for code in codes]) for title, codes in groups
        ]

    @property
    def hidden_parameters(self):
        """Ticked codes that do not apply now; kept until the form is saved."""
        applicable = applicable_monitored_parameters(self.arrangement, self.plug_seal_present)
        return [code for code in (self.form["monitored_parameters"].value() or []) if code not in applicable]

    # --- validation and saving ---

    def is_valid(self):
        forms_valid = [self.form.is_valid()] + [self.position_forms[role].is_valid() for role in self.roles]
        return all(forms_valid)

    def discards(self):
        """Non-empty data that saving the posted configuration would discard."""
        items = []
        for role, form in self.position_forms.items():
            if role in self.roles:
                continue
            values = [str(form[f].value() or "").strip() for f in SealPosition.DESCRIPTIVE_FIELDS]
            if any(values):
                items.append(f"{SealRole(role).label}: {', '.join(v for v in values if v)}")
        if not self.plug_seal_present:
            values = [str(self.form[f].value() or "").strip() for f in conditions.PROCESS_FIELDS]
            if any(values):
                items.append(f"Process conditions: {', '.join(v for v in values if v)}")
        return items

    @property
    def notices(self):
        return getattr(self.form.instance, "normalization_notices", [])

    @transaction.atomic
    def save(self):
        setup = self.form.save()
        setup.positions.exclude(role__in=self.roles).delete()
        for role in self.roles:
            position = self.position_forms[role].save(commit=False)
            position.setup = setup
            position.role = role
            position.save()
        setup.validate_positions()
        return setup

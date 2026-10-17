from django import forms

from testlab.execution.forms import ReadingField, plain_number
from testlab.projects.arrangements import SealRole

from . import inspection
from .acceptance import BASIS_UNITS
from .inspection import Applicability, MeasurementKind
from .models import AcceptanceItem, Assessment, ResultComponent, ResultImage, TestResult


FACE_CONDITIONS = ["New", "Reused", "Re-lapped"]  # suggestions only: the field stays free text


class ComponentForm(forms.ModelForm):
    """Identity of a component as fitted (legacy "Seal Configuration"), its face dimensions and
    its measurement plan: blank follows the Result (seal faces), or for a sleeve or backing ring
    dimensional optional and Mahr/ROUNDPAK not applicable."""

    PLAN_FIELDS = ["dimensional_applicability", "mahr_applicability", "roundpak_applicability"]

    face_od = ReadingField(label="Face OD", required=False, max_digits=10, decimal_places=4)
    face_id = ReadingField(label="Face ID", required=False, max_digits=10, decimal_places=4)

    class Meta:
        model = ResultComponent
        fields = ["part_no", "material", "condition", "face_od", "face_id", "diameter_unit",
                  "dimensional_applicability", "mahr_applicability", "roundpak_applicability"]  # fmt: skip

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        component = self.instance
        for name in self.PLAN_FIELDS:
            kind = name.removesuffix("_applicability")
            default = inspection.effective_applicability(component.component, "", getattr(component.result, name), kind)
            self.fields[name].choices = [("", f"Default ({Applicability(default).label.lower()})")] + list(
                Applicability.choices
            )
        self.fields["condition"].widget.attrs.update(list="face-conditions", title=self.fields["condition"].help_text)
        for name in ("face_od", "face_id"):
            value = getattr(component, name)
            if value is not None:
                self.initial[name] = plain_number(value)

    def clean(self):
        cleaned = super().clean()
        od, id_ = cleaned.get("face_od"), cleaned.get("face_id")
        if od is not None and id_ is not None and od <= id_:
            self.add_error("face_od", "The face OD must be larger than the ID.")
        return cleaned


ComponentFormSet = forms.modelformset_factory(ResultComponent, form=ComponentForm, extra=0)


def _pair_value(position, component):
    return f"{position}:{component}"


class AddComponentForm(forms.Form):
    component = forms.ChoiceField(label="Add component")

    def __init__(self, *args, addable, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["component"].choices = [
            (_pair_value(p, c), inspection.identity_label(p, c)) for p, c in addable
        ]

    def pair(self):
        position, component = self.cleaned_data["component"].split(":")
        return position, component


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        files = [f for f in files if f]
        if not files:
            raise forms.ValidationError("Choose one or more pictures.")
        return [super(MultipleImageField, self).clean(f, initial) for f in files]


def component_choices(components):
    return [("", "— none (whole seal) —")] + [(str(c.pk), c.label) for c in components]


class _ImageMetaForm(forms.Form):
    category = forms.ChoiceField(label="Picture", choices=ResultImage.Category.choices)
    component = forms.ChoiceField(label="Component", required=False)
    caption = forms.CharField(label="Caption / remark", required=False, max_length=300)

    def __init__(self, *args, components, **kwargs):
        super().__init__(*args, **kwargs)
        self.components = {str(c.pk): c for c in components}
        self.fields["component"].choices = component_choices(components)

    def clean_component(self):
        value = self.cleaned_data["component"]
        return self.components.get(value) if value else None


class ImageUploadForm(_ImageMetaForm):
    files = MultipleImageField(
        label="Pictures", help_text="One or more pictures; each original is stored unchanged."
    )
    field_order = ["files", "category", "component", "caption"]


class ImageEditForm(_ImageMetaForm):
    pass


class AcceptanceItemForm(forms.ModelForm):
    limit = ReadingField(label="Limit", required=False, max_digits=24, decimal_places=12)

    class Meta:
        model = AcceptanceItem
        fields = [
            "criterion", "basis", "position", "component", "comparison", "limit", "unit",
            "requirement_text", "actual_text", "assessment", "remark",
        ]  # fmt: skip
        widgets = {"remark": forms.Textarea(attrs={"rows": 2})}
        labels = {"assessment": "Engineer assessment", "comparison": "Requirement"}

    def __init__(self, *args, result, positions, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = result
        self.fields["position"].choices = [("", "—")] + [(p, SealRole(p).label) for p in positions]
        wear_components = [c for c in result.components.all() if c.is_face
                           and c.applicability(MeasurementKind.DIMENSIONAL) != Applicability.NOT_APPLICABLE]  # fmt: skip
        self.fields["component"].queryset = ResultComponent.objects.filter(pk__in=[c.pk for c in wear_components])
        self.fields["component"].label_from_instance = lambda c: c.label
        self.fields["comparison"].choices = [("", "— none —")] + AcceptanceItem.Comparison.choices
        self.fields["assessment"].choices = [("", "— calculated, else not assessed —")] + Assessment.choices
        self.fields["unit"].help_text = "The calculated actual is in ml/h, in/h or h; a limit in another unit of the same quantity is converted."
        if self.instance.pk and self.instance.limit is not None:
            self.initial["limit"] = plain_number(self.instance.limit)
        self.linked = self.instance.from_requirement
        if self.linked:  # the requirement is kept in step with its source; the engineer assesses
            for name in self.REQUIREMENT_FIELDS:
                self.fields[name].disabled = True

    REQUIREMENT_FIELDS = ["criterion", "basis", "position", "component", "comparison", "limit", "unit",
                          "requirement_text"]  # fmt: skip

    def clean(self):
        cleaned = super().clean()
        if self.linked:
            if cleaned.get("actual_text") and self.instance.basis != AcceptanceItem.Basis.MANUAL:
                self.add_error("actual_text", "The actual is calculated for this basis; leave it empty.")
            return cleaned
        basis = cleaned.get("basis")
        Basis = AcceptanceItem.Basis
        if basis == Basis.LEAKAGE_RATE and not cleaned.get("position"):
            self.add_error("position", "Choose the seal whose leakage is assessed.")
        if basis == Basis.WEAR_RATE and not cleaned.get("component"):
            self.add_error("component", "Choose the component whose face wear is assessed.")
        if basis != Basis.LEAKAGE_RATE:
            cleaned["position"] = ""
        if basis != Basis.WEAR_RATE:
            cleaned["component"] = None
        if basis in BASIS_UNITS:
            cleaned["unit"] = cleaned.get("unit") or BASIS_UNITS[basis]
            if cleaned.get("actual_text"):
                self.add_error("actual_text", "The actual is calculated for this basis; leave it empty.")
        comparison, limit = cleaned.get("comparison"), cleaned.get("limit")
        if comparison and limit is None:
            self.add_error("limit", "Enter the limit.")
        if limit is not None and not comparison:
            self.add_error("comparison", "Choose ≤ or ≥ for the limit.")
        if not comparison and not cleaned.get("requirement_text"):
            self.add_error("requirement_text", "Enter the requirement: a limit or a text.")
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        if not self.linked:
            item.position = self.cleaned_data["position"]
            item.component = self.cleaned_data["component"]
            item.unit = self.cleaned_data.get("unit", "")
        if commit:
            item.save()
        return item


class ComponentObservationsForm(forms.ModelForm):
    class Meta:
        model = ResultComponent
        fields = ["observations"]
        widgets = {"observations": forms.Textarea(attrs={"rows": 2})}


class ReportDetailsForm(forms.ModelForm):
    class Meta:
        model = TestResult
        fields = ["responsible_engineer", "objective_addition"]
        widgets = {"objective_addition": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["responsible_engineer"]
        field.queryset = field.queryset.filter(is_active=True).order_by("last_name", "first_name", "username")
        field.label_from_instance = lambda user: user.get_full_name() or user.username
        field.required = True


class NarrativeForm(forms.ModelForm):
    class Meta:
        model = TestResult
        fields = ["observations", "conclusion", "recommendation"]
        widgets = {name: forms.Textarea(attrs={"rows": 5}) for name in fields}

from django import forms

from testlab.execution.forms import ReadingField, plain_number
from testlab.projects.arrangements import SealRole

from . import inspection
from .acceptance import BASIS_UNITS
from .models import AcceptanceItem, Assessment, ResultComponent, ResultImage, TestResult


class ComponentForm(forms.ModelForm):
    """Identity of a component as fitted (legacy "Seal Configuration")."""

    class Meta:
        model = ResultComponent
        fields = ["part_no", "material", "condition"]


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


class MeasurementsForm(forms.Form):
    """Pre and Post of every applicable quantity of every component. Blank = not measured."""

    def __init__(self, *args, components, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []
        for component in components:
            stored = {m.quantity: m for m in component.measurements.all()}
            for quantity in component.quantities():
                measurement = stored.get(quantity.code)
                names = []
                for stage in ("pre", "post"):
                    name = f"m{component.pk}_{quantity.code}_{stage}"
                    field = ReadingField(label=f"{component.label} {quantity.label} {stage}", required=False,
                                         max_digits=16, decimal_places=6)
                    self.fields[name] = field
                    value = getattr(measurement, f"{stage}_value", None) if measurement else None
                    if value is not None:
                        self.initial[name] = plain_number(value)
                    names.append(name)
                self.rows.append((component, quantity, names[0], names[1], measurement))

    def bound_rows(self):
        """[(component, quantity, pre field, post field, stored measurement)] in display order."""
        return [(c, q, self[pre], self[post], m) for c, q, pre, post, m in self.rows]

    def values(self):
        return {
            (component.pk, quantity.code): (self.cleaned_data[pre], self.cleaned_data[post])
            for component, quantity, pre, post, _ in self.rows
        }


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
        wear_components = [c for c in result.components.all() if any(q.wear for q in c.quantities())]
        self.fields["component"].queryset = ResultComponent.objects.filter(pk__in=[c.pk for c in wear_components])
        self.fields["component"].label_from_instance = lambda c: c.label
        self.fields["comparison"].choices = [("", "— none —")] + AcceptanceItem.Comparison.choices
        self.fields["assessment"].choices = [("", "— calculated, else not evaluated —")] + Assessment.choices
        self.fields["unit"].help_text = "Fixed for a calculated actual."
        if self.instance.pk and self.instance.limit is not None:
            self.initial["limit"] = plain_number(self.instance.limit)

    def clean(self):
        cleaned = super().clean()
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
            cleaned["unit"] = BASIS_UNITS[basis]
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
        item.position = self.cleaned_data["position"]
        item.component = self.cleaned_data["component"]
        item.unit = self.cleaned_data.get("unit", "")
        if commit:
            item.save()
        return item


class NarrativeForm(forms.ModelForm):
    class Meta:
        model = TestResult
        fields = ["observations", "conclusion", "recommendation"]
        widgets = {name: forms.Textarea(attrs={"rows": 5}) for name in fields}

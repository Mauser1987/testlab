from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from .models import ManualLogEntry


class ReadingField(forms.DecimalField):
    """A reading: decimal point or comma ("70,05"), no thousands separators."""

    widget = forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off", "class": "reading"})

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        return super().to_python(value)


class ManualLogEntryForm(forms.Form):
    """One reading. Fields: date/time, one per measurement of the run, leakage period, note."""

    observed_at = forms.DateTimeField(
        label="Date / time",
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    leakage_hours = ReadingField(
        label="Collected over [h]", required=False, max_digits=8, decimal_places=3, min_value=Decimal("0.001"),
        help_text="Only when leakage was not collected since the previous reading.",
    )
    note = forms.CharField(
        label="Note / event", required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    category = forms.ChoiceField(
        label="Event", required=False, choices=[("", "—")] + ManualLogEntry.Category.choices,
    )

    def __init__(self, *args, columns, previous=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.columns = columns
        if not self.is_bound and "observed_at" not in self.initial:
            self.initial["observed_at"] = timezone.localtime().replace(second=0, microsecond=0)
        for column in columns:
            field = ReadingField(label=column.full_label, required=False, max_digits=12, decimal_places=4)
            if previous is not None and column.code in previous.values:
                # The previous reading as a hint, never as a value: an untyped field stays empty.
                field.widget.attrs = {**field.widget.attrs, "placeholder": plain_number(previous.values[column.code].value)}
            self.fields[column.code] = field

    def reading_fields(self):
        return [self[column.code] for column in self.columns]

    def clean(self):
        cleaned = super().clean()
        values = [cleaned.get(column.code) for column in self.columns]
        if all(v is None for v in values) and not cleaned.get("note") and not cleaned.get("category"):
            raise forms.ValidationError("Enter at least one reading, an event or a note.")
        if cleaned.get("leakage_hours") is not None and not any(
            cleaned.get(c.code) is not None for c in self.columns if c.is_leakage
        ):
            self.add_error("leakage_hours", "Only needed together with a leakage volume.")
        return cleaned


def plain_number(value):
    """70.0500 → "70.05": a stored reading shown as typed."""
    try:
        return format(value.normalize(), "f")
    except (InvalidOperation, AttributeError):
        return str(value)


class DcsUploadForm(forms.Form):
    file = forms.FileField(
        label="LabVIEW / DCS export",
        help_text="The file as exported (no extension needed). It is stored unchanged.",
    )


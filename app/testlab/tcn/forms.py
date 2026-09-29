import re

from django import forms

from .models import TcnRevision


def revision_label(tcn):
    return f"{tcn} ({tcn.get_status_display().lower()})"


class RevisionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return revision_label(obj)


class NewTcnForm(forms.Form):
    """S6: run number and source of a new TCN."""

    DEFAULTS, COPY = "defaults", "copy"

    run_no = forms.CharField(label="Run no.", max_length=3, widget=forms.TextInput(attrs={"size": 4}))
    source_type = forms.ChoiceField(
        label="Start from",
        choices=[(COPY, "Copy of TCN"), (DEFAULTS, "Project defaults")],
        widget=forms.RadioSelect,
    )
    source = RevisionChoiceField(label="TCN to copy", queryset=TcnRevision.objects.none(), required=False)

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A TCN copy stays within the project (M1).
        revisions = TcnRevision.objects.filter(test_run__project=project).select_related("test_run")
        self.fields["source"].queryset = revisions.order_by("-test_run__run_no", "-revision")
        if not revisions.exists():
            self.fields["source_type"].choices = [(self.DEFAULTS, "Project defaults")]

    def clean_run_no(self):
        value = self.cleaned_data["run_no"].strip()
        if not re.fullmatch(r"\d{1,3}", value) or not 1 <= int(value) <= 999:
            raise forms.ValidationError("Enter a run number from 1 to 999 (e.g. 4, 04 or 004).")
        return int(value)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("source_type") == self.COPY and not cleaned.get("source"):
            self.add_error("source", "Select the TCN to copy.")
        return cleaned

    @property
    def source_revision(self):
        return self.cleaned_data["source"] if self.cleaned_data["source_type"] == self.COPY else None


class TcnHeaderForm(forms.ModelForm):
    """S7 header fields of a draft, with the row version it was loaded at (V10)."""

    row_version = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = TcnRevision
        fields = ["project_description", "prepared_by", "revision_reason"]
        widgets = {
            "project_description": forms.TextInput(attrs={"size": 60}),
            "prepared_by": forms.TextInput(attrs={"size": 6}),
            "revision_reason": forms.Textarea(attrs={"rows": 3, "cols": 80}),
        }
        help_texts = {"prepared_by": "Initials, e.g. MG."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["row_version"].initial = self.instance.row_version
        if self.instance.revision == 0:
            del self.fields["revision_reason"]

    def clean_prepared_by(self):
        return self.cleaned_data["prepared_by"].upper()


class CancelTcnForm(forms.Form):
    """S10: reason for cancelling an issued TCN (V14)."""

    reason = forms.CharField(label="Reason for cancelling", widget=forms.Textarea(attrs={"rows": 3, "cols": 80}))

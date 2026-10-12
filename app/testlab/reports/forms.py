from django import forms

from .models import FinalReport


class FinalReportForm(forms.ModelForm):
    class Meta:
        model = FinalReport
        fields = FinalReport.TEXT_FIELDS
        widgets = {name: forms.Textarea(attrs={"rows": 6}) for name in FinalReport.TEXT_FIELDS}
        help_texts = {
            "introduction": "Paragraphs are separated by a blank line.",
            "field_conditions": "The conditions at site, as the report states them.",
            "test_conditions": "The conditions tested, as the report states them.",
        }

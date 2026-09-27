from django import forms

from .models import Project, normalize_project_no


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["project_no", "description", "customer"]
        widgets = {
            "description": forms.TextInput(attrs={"size": 60}),
            "customer": forms.TextInput(attrs={"size": 60}),
        }

    def clean_project_no(self):
        # Normalise before the model's unique check so "2099rsd01tl" and
        # "2099RSD01TL" are the same project.
        return normalize_project_no(self.cleaned_data["project_no"])

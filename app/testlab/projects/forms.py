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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.project_no_locked():
            # V2: shown read-only; a disabled field ignores posted values.
            field = self.fields["project_no"]
            field.disabled = True
            field.help_text = "Locked: a TCN of this project has been issued."

    def clean_project_no(self):
        # Normalise before the model's unique check so "2099rsd01tl" and
        # "2099RSD01TL" are the same project.
        return normalize_project_no(self.cleaned_data["project_no"])

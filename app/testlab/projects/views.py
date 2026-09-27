from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from .forms import ProjectForm
from .models import Project, project_no_format_warning
from .setup_forms import RunSetupEditor


class ProjectListView(ListView):
    model = Project
    context_object_name = "projects"

    def get_queryset(self):
        projects = super().get_queryset()
        self.query = self.request.GET.get("q", "").strip()
        if self.query:
            projects = projects.filter(
                Q(project_no__icontains=self.query)
                | Q(description__icontains=self.query)
                | Q(customer__icontains=self.query)
            )
        return projects

    def get_context_data(self, **kwargs):
        return super().get_context_data(query=self.query, **kwargs)


class ProjectFormMixin:
    model = Project
    form_class = ProjectForm
    # Until the project page exists (commit 6), saving returns to the project list.
    success_url = reverse_lazy("projects:list")

    def form_valid(self, form):
        if form.instance.pk is None:
            form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Project {self.object.project_no} saved.")
        warning = project_no_format_warning(self.object.project_no)
        if warning:
            messages.warning(self.request, warning)
        return response


class ProjectCreateView(ProjectFormMixin, CreateView):
    def get_success_url(self):
        # S3 → S5: continue with the project defaults.
        return reverse("projects:defaults", args=[self.object.pk])


class ProjectUpdateView(ProjectFormMixin, UpdateView):
    pass


class ProjectDefaultsView(View):
    """S5: project defaults, edited with the shared run setup form."""

    template_name = "projects/project_defaults.html"

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return self.render(request, project, RunSetupEditor(project.default_setup))

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        editor = RunSetupEditor(project.default_setup, request.POST)
        if request.POST.get("action") == "save":
            editor.show_errors = True
            if editor.is_valid():
                if editor.discards() and not request.POST.get("confirm_discard"):
                    editor.confirmation_required = True
                else:
                    with transaction.atomic():
                        editor.save()
                        project.updated_by = request.user
                        project.save(update_fields=["updated_by", "updated_at"])
                    for notice in editor.notices:
                        messages.info(request, notice)
                    messages.success(request, f"Project defaults of {project.project_no} saved.")
                    return redirect("projects:defaults", pk=project.pk)
        return self.render(request, project, editor)

    def render(self, request, project, editor):
        return render(request, self.template_name, {"project": project, "editor": editor})

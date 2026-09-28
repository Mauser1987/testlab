from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from testlab.tcn.models import TcnRevision

from .arrangements import seal_support_label
from .forms import ProjectForm
from .models import Project, project_no_format_warning
from .setup_forms import RunSetupEditor


class ProjectListView(ListView):
    model = Project
    context_object_name = "projects"

    def get_queryset(self):
        # Explicit order: Meta.ordering is not applied to aggregated querysets.
        projects = (
            super()
            .get_queryset()
            .annotate(tcn_count=Count("test_runs"), last_tcn_at=Max("test_runs__created_at"))
            .order_by("-project_no")
        )
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


class ProjectDetailView(DetailView):
    """S4: project identity, defaults summary and TCN register."""

    model = Project
    context_object_name = "project"

    def get_context_data(self, **kwargs):
        runs = self.object.test_runs.prefetch_related(
            Prefetch("revisions", queryset=TcnRevision.objects.select_related("setup"))
        )
        register = []
        for run in runs:
            current = run.current_revision()
            draft = next((r for r in run.revisions.all() if r.status == TcnRevision.Status.DRAFT), None)
            register.append(
                {
                    "tcn": current,
                    "setup": current.setup,
                    "seal_support_label": seal_support_label(current.setup.arrangement),
                    "pending_draft": draft if draft != current else None,
                }
            )
        return super().get_context_data(register=register, **kwargs)


class ProjectFormMixin:
    model = Project
    form_class = ProjectForm

    def get_success_url(self):
        return reverse("projects:detail", args=[self.object.pk])

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

"""Final Report of a project (rough version): texts, included runs, draft PDF."""

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from testlab.documents.pdf import PDF_CONTENT_TYPE, PdfConversionError
from testlab.projects.models import Project
from testlab.results.models import RecordIntegrityError

from . import assembly
from .forms import FinalReportForm
from .models import FinalReport, FinalReportRun


def chosen_runs(post, candidates):
    """The ticked Results in the order entered (ties and blanks: run order)."""
    chosen = []
    for index, result in enumerate(candidates):
        if post.get(f"include_{result.pk}"):
            try:
                order = int(post.get(f"order_{result.pk}", ""))
            except ValueError:
                order = 10_000
            chosen.append((order, index, result))
    return [result for _, _, result in sorted(chosen, key=lambda item: item[:2])]


class FinalReportView(View):
    template_name = "reports/final_report.html"

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        report = FinalReport.objects.filter(project=project).first()
        return self.render(request, project, report, FinalReportForm(instance=report))

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        report = FinalReport.objects.filter(project=project).first()
        form = FinalReportForm(request.POST, instance=report)
        if not form.is_valid():
            return self.render(request, project, report, form)
        with transaction.atomic():
            report = form.save(commit=False)
            report.project = project
            report.updated_by = request.user
            report.save()
            report.runs.all().delete()
            FinalReportRun.objects.bulk_create(
                FinalReportRun(report=report, result=result, position=position)
                for position, result in enumerate(chosen_runs(request.POST, assembly.candidates(project)), start=1)
            )
        messages.success(request, "Final Report saved. Results and issued documents are unchanged.")
        return redirect("reports:final_report", project.pk)

    def render(self, request, project, report, form):
        positions = {item.result_id: item.position for item in report.runs.all()} if report else {}
        rows = [{"result": result, "run": result.test_run, "revision": result.revision,
                 "revising": result.is_revising, "position": positions.get(result.pk)}
                for result in assembly.candidates(project)]  # fmt: skip
        context = {"project": project, "report": report, "form": form, "rows": rows,
                   "report_no": f"{project.project_no}R", "included": len(positions)}  # fmt: skip
        return render(request, self.template_name, context)


class FinalReportPreviewView(View):
    """The Final Report as a draft PDF, rendered now from the frozen records; never stored."""

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        try:
            content = assembly.render_pdf(project)
        except (assembly.AssemblyError, PdfConversionError, RecordIntegrityError) as error:
            messages.error(request, f"The Final Report could not be generated. {error}")
            return redirect("reports:final_report", project.pk)
        response = HttpResponse(content, content_type=PDF_CONTENT_TYPE)
        response["Content-Disposition"] = f'inline; filename="{project.project_no}R-FinalReport-DRAFT.pdf"'
        response["Cache-Control"] = "no-store"
        return response

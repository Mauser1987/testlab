from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from testlab.documents.render import render_docx, template_path
from testlab.documents.tcn_context import build_tcn_context, tcn_file_name
from testlab.projects.models import Project
from testlab.projects.setup_forms import RunSetupEditor

from .diff import source_changes
from .forms import NewTcnForm, TcnHeaderForm
from .models import ImmutableTcnError, TcnRevision, TcnRuleError, TestRun
from .services import (
    IssueError,
    StaleDraftError,
    create_tcn,
    default_copy_source,
    issue_errors,
    issue_tcn,
    save_draft,
)


class TcnCreateView(View):
    """S6: new TCN from the project defaults or as a copy of a TCN of this project."""

    template_name = "tcn/tcn_new.html"

    def get(self, request, project_pk):
        project = get_object_or_404(Project, pk=project_pk)
        source = default_copy_source(project)
        if "source" in request.GET:  # "Copy to new TCN" on a register row
            if not request.GET["source"].isdigit():
                raise Http404
            source = get_object_or_404(TcnRevision, pk=request.GET["source"], test_run__project=project)
        form = NewTcnForm(
            project,
            initial={
                "run_no": f"{TestRun.next_run_no(project):03d}",
                "source_type": NewTcnForm.COPY if source else NewTcnForm.DEFAULTS,
                "source": source,
            },
        )
        return render(request, self.template_name, {"project": project, "form": form})

    def post(self, request, project_pk):
        project = get_object_or_404(Project, pk=project_pk)
        form = NewTcnForm(project, request.POST)
        if form.is_valid():
            try:
                tcn = create_tcn(project, form.cleaned_data["run_no"], request.user, source=form.source_revision)
            except ValidationError as error:
                form.add_error(None, error)
            except TcnRuleError as error:
                form.add_error(None, str(error))
            else:
                origin = f"copy of {tcn.source_tcn}" if tcn.source_tcn else "from project defaults"
                messages.success(request, f"{tcn} created as draft ({origin}).")
                return redirect("tcn:edit", pk=tcn.pk)
        return render(request, self.template_name, {"project": project, "form": form})


class DraftTcnMixin:
    """Actions that exist only for draft TCNs; an issued TCN is shown read-only (S9)."""

    def get_tcn(self, pk):
        return get_object_or_404(TcnRevision.objects.select_related("test_run__project", "setup", "source_tcn"), pk=pk)

    def refuse_locked(self, request, tcn):
        messages.error(request, f"{tcn} is {tcn.get_status_display().lower()} and cannot be edited.")
        return redirect("tcn:edit", pk=tcn.pk)


class TcnEditView(DraftTcnMixin, View):
    """S7: edit a draft TCN revision (header fields + shared run setup form).

    An issued, superseded or cancelled TCN opens read-only (S9).
    """

    template_name = "tcn/tcn_edit.html"

    def get(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return render_issued(request, tcn)
        return self.render(request, tcn, TcnHeaderForm(instance=tcn), RunSetupEditor(tcn.setup))

    def post(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        header = TcnHeaderForm(request.POST, instance=tcn)
        editor = RunSetupEditor(tcn.setup, request.POST)
        conflict = None
        if request.POST.get("action") == "save":
            editor.show_errors = True
            header_valid = header.is_valid()  # validate both forms to show all errors
            if editor.is_valid() and header_valid:
                if editor.discards() and not request.POST.get("confirm_discard"):
                    editor.confirmation_required = True
                else:
                    try:
                        save_draft(tcn, header, editor, header.cleaned_data["row_version"], request.user)
                    except StaleDraftError as error:
                        conflict = str(error)
                    except ImmutableTcnError:
                        return self.refuse_locked(request, self.get_tcn(pk))
                    else:
                        for notice in editor.notices:
                            messages.info(request, notice)
                        messages.success(request, f"{tcn} saved.")
                        return redirect("tcn:edit", pk=tcn.pk)
        return self.render(request, tcn, header, editor, conflict=conflict)

    def render(self, request, tcn, header, editor, conflict=None):
        # Markers compare the saved draft with its source; None without a source TCN.
        changes = source_changes(TcnRevision.objects.select_related("setup", "source_tcn__setup").get(pk=tcn.pk))
        context = {
            "tcn": tcn,
            "project": tcn.test_run.project,
            "header": header,
            "editor": editor,
            "conflict": conflict,
            "change_list": changes,
            "changes": {change.key: change for change in changes or []},
        }
        return render(request, self.template_name, context)


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TcnPreviewView(DraftTcnMixin, View):
    """Preview DOCX of a draft (§6 S7, §9.3): rendered from the saved draft, marked DRAFT, not stored.

    Only drafts: an issued TCN's document is the stored file, never re-rendered (§9.4).
    """

    def get(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        content = render_docx(template_path("tcn.docx"), build_tcn_context(tcn))
        response = HttpResponse(content, content_type=DOCX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{tcn_file_name(tcn, draft=True)}"'
        response["Cache-Control"] = "no-store"
        return response


def render_issued(request, tcn):
    """S9: read-only view of an issued, superseded or cancelled TCN and the run's revisions.

    The content shown is the issued snapshot: exactly what the issued document prints.
    """
    revisions = tcn.test_run.revisions.select_related("issued_by")
    superseded_by = None
    if tcn.status == TcnRevision.Status.SUPERSEDED:
        superseded_by = revisions.filter(revision__gt=tcn.revision).exclude(status=TcnRevision.Status.DRAFT).first()
    context = {
        "tcn": tcn,
        "project": tcn.test_run.project,
        "snapshot": tcn.issued_snapshot,
        "revisions": revisions,
        "superseded_by": superseded_by,
    }
    return render(request, "tcn/tcn_view.html", context)


class TcnIssueView(DraftTcnMixin, View):
    """S8: issue confirmation. Issues the saved draft as it was reviewed on this page."""

    template_name = "tcn/tcn_issue.html"

    def get(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        return self.render(request, tcn)

    def post(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        try:
            row_version = int(request.POST.get("row_version", ""))
        except ValueError:
            return self.render(request, tcn, conflict="The review data was incomplete; review the TCN again.")
        try:
            tcn = issue_tcn(tcn, row_version, request.user)
        except StaleDraftError as error:
            return self.render(request, self.get_tcn(pk), conflict=f"{error} Review it again before issuing.")
        except IssueError as error:
            return self.render(request, self.get_tcn(pk), errors=error.errors)
        except ImmutableTcnError:
            return self.refuse_locked(request, self.get_tcn(pk))
        messages.success(request, f"{tcn} issued.")
        return redirect("tcn:edit", pk=tcn.pk)

    def render(self, request, tcn, conflict=None, errors=None):
        context = {
            "tcn": tcn,
            "project": tcn.test_run.project,
            "errors": issue_errors(tcn) if errors is None else errors,
            "change_list": source_changes(tcn),
            "conflict": conflict,
        }
        return render(request, self.template_name, context)


class TcnDocumentView(View):
    """Download of the issued DOCX: always the stored file, never re-rendered (§9.4)."""

    def get(self, request, pk):
        tcn = get_object_or_404(TcnRevision.objects.select_related("test_run__project"), pk=pk)
        if not tcn.is_locked or not tcn.issued_document:
            raise Http404("This TCN has no issued document.")
        storage = tcn.issued_document.storage
        if not storage.exists(tcn.issued_document.name):
            raise Http404("The issued document file is missing from the file store.")
        return FileResponse(
            storage.open(tcn.issued_document.name, "rb"),
            as_attachment=True,
            filename=tcn.issued_document.name.rsplit("/", 1)[-1],
            content_type=DOCX_CONTENT_TYPE,
        )

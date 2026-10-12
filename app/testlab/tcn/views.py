from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from testlab.documents.pdf import PDF_CONTENT_TYPE, PdfConversionError
from testlab.documents.render import tcn_template
from testlab.documents.tcn_context import build_tcn_context, tcn_file_name
from testlab.projects.models import Project
from testlab.projects.setup_forms import RunSetupEditor

from .diff import source_changes
from .forms import CancelTcnForm, NewTcnForm, TcnHeaderForm, TcnRequirementChangeForm
from .models import ImmutableTcnError, TcnRequirementChange, TcnRevision, TcnRuleError, TestRun
from .permissions import can_cancel_tcn, can_issue_tcn
from .services import (
    IssueError,
    StaleDraftError,
    cancel_error,
    cancel_tcn,
    create_revision,
    create_tcn,
    default_copy_source,
    delete_draft,
    issue_errors,
    issue_tcn,
    new_revision_error,
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

    def render(self, request, tcn, header, editor, conflict=None, requirement_form=None):
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
            "can_issue": can_issue_tcn(request.user),
            "requirement_changes": list(tcn.requirement_changes.select_related("program_requirement")),
            "requirement_form": requirement_form or TcnRequirementChangeForm(tcn=tcn),
        }
        return render(request, self.template_name, context)


class TcnPreviewView(DraftTcnMixin, View):
    """Preview PDF of a draft (§6 S7, §9.3): rendered from the saved draft, marked DRAFT, not stored.

    Only drafts: an issued TCN's document is the stored PDF, never re-rendered (§9.4).
    """

    def get(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        try:
            content = tcn_template().render_pdf(build_tcn_context(tcn))
        except PdfConversionError as error:
            messages.error(request, f"The PDF preview could not be generated. {error}")
            return redirect("tcn:edit", pk=tcn.pk)
        response = HttpResponse(content, content_type=PDF_CONTENT_TYPE)
        # Opened in the browser's PDF viewer; saving it gives the -DRAFT file name.
        response["Content-Disposition"] = f'inline; filename="{tcn_file_name(tcn, draft=True)}"'
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
        "pending_draft": revisions.filter(status=TcnRevision.Status.DRAFT).first(),
        "can_revise": new_revision_error(tcn) is None,
        "can_cancel": cancel_error(tcn) is None and can_cancel_tcn(request.user),
    }
    return render(request, "tcn/tcn_view.html", context)


class TcnIssueView(DraftTcnMixin, View):
    """S8: issue confirmation. Issues the saved draft as it was reviewed on this page."""

    template_name = "tcn/tcn_issue.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_issue_tcn(request.user):
            raise PermissionDenied("You are not allowed to issue TCNs.")
        return super().dispatch(request, *args, **kwargs)

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
    """Download of the issued PDF: always the stored file, never re-rendered (§9.4).

    Only a stored PDF is served; the controlled document is never offered in
    an editable format.
    """

    def get(self, request, pk):
        tcn = get_object_or_404(TcnRevision.objects.select_related("test_run__project"), pk=pk)
        name = tcn.issued_document.name if tcn.issued_document else ""
        if not tcn.is_locked or not name.lower().endswith(".pdf"):
            raise Http404("This TCN has no issued PDF.")
        storage = tcn.issued_document.storage
        if not storage.exists(name):
            raise Http404("The issued PDF is missing from the file store.")
        return FileResponse(
            storage.open(name, "rb"),
            as_attachment=True,
            filename=name.rsplit("/", 1)[-1],
            content_type=PDF_CONTENT_TYPE,
        )


class TcnNewRevisionView(View):
    """S9 "New revision": draft rev n+1 of the current issued revision (V13)."""

    def post(self, request, pk):
        tcn = get_object_or_404(TcnRevision, pk=pk)
        try:
            revision = create_revision(tcn, request.user)
        except TcnRuleError as error:
            messages.error(request, str(error))
            return redirect("tcn:edit", pk=tcn.pk)
        messages.success(request, f"{revision} created as draft (new revision of {tcn}).")
        return redirect("tcn:edit", pk=revision.pk)


class TcnCancelView(View):
    """S10: cancel the current issued revision with a reason (V14)."""

    template_name = "tcn/tcn_cancel.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_cancel_tcn(request.user):
            raise PermissionDenied("You are not allowed to cancel TCNs.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        tcn = get_object_or_404(TcnRevision.objects.select_related("test_run__project"), pk=pk)
        if refusal := self.refusal(request, tcn):
            return refusal
        return self.render(request, tcn, CancelTcnForm())

    def post(self, request, pk):
        tcn = get_object_or_404(TcnRevision.objects.select_related("test_run__project"), pk=pk)
        if refusal := self.refusal(request, tcn):
            return refusal
        form = CancelTcnForm(request.POST)
        if form.is_valid():
            try:
                tcn = cancel_tcn(tcn, form.cleaned_data["reason"], request.user)
            except ValidationError as error:
                form.add_error(None, error)
            except TcnRuleError as error:
                messages.error(request, str(error))
                return redirect("tcn:edit", pk=tcn.pk)
            else:
                messages.success(request, f"{tcn} cancelled.")
                return redirect("tcn:edit", pk=tcn.pk)
        return self.render(request, tcn, form)

    def refusal(self, request, tcn):
        error = cancel_error(tcn)
        if error:
            messages.error(request, error)
            return redirect("tcn:edit", pk=tcn.pk)
        return None

    def render(self, request, tcn, form):
        return render(request, self.template_name, {"tcn": tcn, "project": tcn.test_run.project, "form": form})


class TcnDeleteView(DraftTcnMixin, View):
    """Delete draft (S7): confirmation, then removed without trace (§4)."""

    template_name = "tcn/tcn_delete.html"

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
            return self.render(request, tcn, error="The confirmation data was incomplete; confirm again.")
        name, run, project = str(tcn), tcn.test_run, tcn.test_run.project
        try:
            delete_draft(tcn, row_version, request.user)
        except StaleDraftError as error:
            return self.render(request, self.get_tcn(pk), error=f"{error} Review it again before deleting.")
        except ImmutableTcnError:
            return self.refuse_locked(request, self.get_tcn(pk))
        except TcnRuleError as error:
            return self.render(request, tcn, error=str(error))
        messages.success(request, f"Draft {name} deleted.")
        remaining = run.current_revision() if TestRun.objects.filter(pk=run.pk).exists() else None
        if remaining:
            return redirect("tcn:edit", pk=remaining.pk)
        return redirect("projects:detail", pk=project.pk)

    def render(self, request, tcn, error=None):
        context = {"tcn": tcn, "project": tcn.test_run.project, "error": error}
        return render(request, self.template_name, context)


# --- Acceptance requirement changes of a draft TCN (M2E) -------------------------------------------


class TcnRequirementChangeAddView(DraftTcnMixin, View):
    def post(self, request, pk):
        tcn = self.get_tcn(pk)
        if tcn.is_locked:
            return self.refuse_locked(request, tcn)
        change = TcnRequirementChange(tcn=tcn, order=tcn.requirement_changes.count())
        form = TcnRequirementChangeForm(request.POST, instance=change, tcn=tcn)
        if form.is_valid():
            form.save()
            messages.success(request, "Acceptance requirement change added; it is in force for the run once this TCN is issued.")
            return redirect(reverse("tcn:edit", args=[tcn.pk]) + "#requirement-changes")
        return TcnEditView().render(request, tcn, TcnHeaderForm(instance=tcn), RunSetupEditor(tcn.setup),
                                    requirement_form=form)  # fmt: skip


class TcnRequirementChangeEditView(View):
    template_name = "tcn/tcn_requirement_change.html"

    def get_change(self, pk):
        return get_object_or_404(TcnRequirementChange.objects.select_related("tcn__test_run__project"), pk=pk)

    def get(self, request, pk):
        change = self.get_change(pk)
        return self.render(request, change, TcnRequirementChangeForm(instance=change, tcn=change.tcn))

    def post(self, request, pk):
        change = self.get_change(pk)
        tcn = change.tcn
        if tcn.is_locked:
            messages.error(request, f"{tcn} is {tcn.get_status_display().lower()} and cannot be edited.")
            return redirect("tcn:edit", pk=tcn.pk)
        if request.POST.get("delete"):
            change.delete()
            messages.success(request, "Acceptance requirement change deleted.")
            return redirect(reverse("tcn:edit", args=[tcn.pk]) + "#requirement-changes")
        form = TcnRequirementChangeForm(request.POST, instance=change, tcn=tcn)
        if form.is_valid():
            form.save()
            messages.success(request, "Acceptance requirement change saved.")
            return redirect(reverse("tcn:edit", args=[tcn.pk]) + "#requirement-changes")
        return self.render(request, change, form)

    def render(self, request, change, form):
        context = {"tcn": change.tcn, "project": change.tcn.test_run.project, "change": change, "form": form}
        return render(request, self.template_name, context)

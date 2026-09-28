"""TCN workflows (M1 spec §4, §7, §9.4): create from project defaults or by
copy, save a draft with optimistic locking (V10), and issue.

The domain rules themselves (snapshot ownership, same-project copies,
immutability) live in models.py; these functions only combine them into
the user's actions, each in one transaction.
"""

import hashlib
import io

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from testlab.documents.render import render_docx, template_path
from testlab.documents.tcn_context import build_tcn_context, tcn_file_name
from testlab.projects.arrangements import SealRole

from .models import ImmutableTcnError, TcnRevision, TcnRuleError, TestRun

RUN_NUMBER_USED = "Run number already used!"


class StaleDraftError(TcnRuleError):
    """The draft was saved by someone else since it was opened (V10)."""


class IssueError(TcnRuleError):
    """The TCN cannot be issued; `errors` lists the reasons (V11, V15)."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def initials(user):
    """Default "Prepared by": first letters of first and last name, e.g. Maria Geerts → MG."""
    names = [user.first_name, user.last_name]
    return "".join(name.strip()[0] for name in names if name.strip()).upper()[:10]


def default_copy_source(project):
    """Current revision of the highest run of the project, or None."""
    run = TestRun.objects.filter(project=project).order_by("-run_no").first()
    return run.current_revision() if run else None


def create_tcn(project, run_no, user, source=None):
    """Create TestRun `run_no` and its draft rev 0.

    Without `source` the run setup is a copy of the project defaults;
    otherwise a copy of `source` (a TCN revision of the same project).
    The project description always comes from the project as it is now.
    """
    if TestRun.objects.filter(project=project, run_no=run_no).exists():
        raise ValidationError({"run_no": RUN_NUMBER_USED})
    try:
        with transaction.atomic():
            run = TestRun.objects.create(project=project, run_no=run_no, created_by=user)
            return TcnRevision.objects.create(
                test_run=run,
                revision=0,
                setup=(source.setup if source else project.default_setup).clone(),
                project_description=project.description,
                prepared_by=initials(user),
                source_kind=TcnRevision.SourceKind.TCN_COPY if source else TcnRevision.SourceKind.PROJECT_DEFAULTS,
                source_tcn=source,
                created_by=user,
                updated_by=user,
            )
    except IntegrityError:
        # Another user took the number between the check and the insert.
        if TestRun.objects.filter(project=project, run_no=run_no).exists():
            raise ValidationError({"run_no": RUN_NUMBER_USED})
        raise


def save_draft(tcn, header_form, editor, expected_row_version, user):
    """Save the header fields and run setup of a draft (S7).

    Refused when the draft was saved by someone else after `expected_row_version`
    was read, or when it is no longer a draft.
    """
    with transaction.atomic():
        _claim_draft(tcn, expected_row_version, user)
        editor.save()
        tcn = header_form.save(commit=False)
        tcn.row_version = expected_row_version + 1
        tcn.updated_by = user
        tcn.save()
    return tcn


def _claim_draft(tcn, expected_row_version, user):
    """Compare-and-set on row_version: claims the next version atomically on every database.

    Refused when the draft was saved by someone else after `expected_row_version`
    was read, or when it is no longer a draft.
    """
    claimed = TcnRevision.objects.filter(
        pk=tcn.pk, status=TcnRevision.Status.DRAFT, row_version=expected_row_version
    ).update(row_version=F("row_version") + 1, updated_by=user, updated_at=timezone.now())
    if not claimed:
        current = TcnRevision.objects.select_related("updated_by").get(pk=tcn.pk)
        if current.is_locked:
            raise ImmutableTcnError(f"{current} has been issued and can no longer be edited.")
        who = current.updated_by.get_full_name() or current.updated_by.username
        when = timezone.localtime(current.updated_at).strftime("%d-%b-%Y %H:%M")
        raise StaleDraftError(f"{current} was changed by {who} at {when} — reload it to see the changes.")


# --- Issue (§4, §9.4) -----------------------------------------------------------------


def issue_errors(tcn):
    """V11: what must be filled in before `tcn` can be issued (empty list: ready)."""
    setup = tcn.setup
    errors = []
    required = [
        (tcn.project_description, "Project description"),
        (tcn.prepared_by, "Prepared by"),
        (setup.run_description, "Test Run description"),
        (setup.test_unit, "Test unit"),
    ]
    if setup.plug_seal_present:
        required.append((setup.plug_medium, "Plug Seal medium"))
    if tcn.revision >= 1:
        required.append((tcn.revision_reason, "Reason for revision"))
    errors += [f"{label} is required." for value, label in required if not value]
    positions = {p.role: p for p in setup.positions.all()}
    for role in setup.applicable_roles():
        if not getattr(positions.get(role), "seal_type_size", ""):
            errors.append(f"{SealRole(role).label}: seal type and size is required.")
    try:
        setup.validate_positions()
    except ValidationError as error:
        errors += error.messages
    return errors


def issued_document_name(tcn):
    """Storage path of the issued DOCX: projects/<project_no>/tcn/<file name> (§9.4)."""
    return f"projects/{tcn.test_run.project.project_no}/tcn/{tcn_file_name(tcn)}"


def issue_tcn(tcn, expected_row_version, user):
    """Issue a draft: the stored DOCX and snapshot become the record of the instruction.

    In one transaction: V11 check on the saved draft, render without the draft
    marking, store the file (refused if it exists, V15), store the file and
    template hashes and the render context, set issued_at/issued_by (the
    user performing the issue) and supersede the previously issued revision
    of the run. On any failure nothing is kept: the TCN stays a draft and a
    file already written is removed.
    """
    storage = TcnRevision._meta.get_field("issued_document").storage
    written = None
    try:
        with transaction.atomic():
            _claim_draft(tcn, expected_row_version, user)  # also: nobody changed it since review
            tcn = TcnRevision.objects.select_related("test_run__project", "setup").get(pk=tcn.pk)
            errors = issue_errors(tcn)
            if errors:
                raise IssueError(errors)

            context = build_tcn_context(tcn)
            context["is_draft"] = False
            template = template_path("tcn.docx").read_bytes()
            content = render_docx(io.BytesIO(template), context)

            name = issued_document_name(tcn)
            if storage.exists(name):
                raise IssueError([f"The file {name} already exists; nothing was issued."])
            written = storage.save(name, ContentFile(content))
            if written != name:  # created concurrently: the storage picked another name
                raise IssueError([f"The file {name} already exists; nothing was issued."])

            previous = tcn.test_run.revisions.filter(status=TcnRevision.Status.ISSUED).exclude(pk=tcn.pk)
            for revision in previous:  # at most one (database constraint)
                revision.status = TcnRevision.Status.SUPERSEDED
                revision.updated_by = user
                revision.save()

            tcn.status = TcnRevision.Status.ISSUED
            tcn.issued_at = timezone.now()
            tcn.issued_by = user
            tcn.issued_document.name = written
            tcn.issued_document_sha256 = hashlib.sha256(content).hexdigest()
            tcn.template_sha256 = hashlib.sha256(template).hexdigest()
            tcn.issued_snapshot = context
            tcn.updated_by = user
            tcn.save()
    except BaseException:
        if written is not None:
            storage.delete(written)
        raise
    return tcn

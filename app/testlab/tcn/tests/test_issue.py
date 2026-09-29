"""Issue & lock (M1 spec §4, §9.4, V2, V11, V15): AT-6, AT-16 (issue part), AT-17."""

import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from testlab.documents.render import template_path
from testlab.documents.tcn_context import build_tcn_context
from testlab.documents.tests.pdf_text import pdf_lines
from testlab.projects.forms import ProjectForm
from testlab.projects.models import Project
from testlab.tcn.models import ImmutableTcnError, TcnRevision
from testlab.tcn.services import IssueError, StaleDraftError, create_tcn, issue_errors, issue_tcn

from .factories import cancel, make_project, new_revision

pytestmark = pytest.mark.django_db

Status = TcnRevision.Status


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")


def ready_tcn(project, user, run_no=1, **setup_fields):
    """A draft that passes V11 (dual pressurized, both seals described)."""
    tcn = create_tcn(project, run_no, user)
    setup = tcn.setup
    setup.run_description = "• Start Test Unit"
    setup.test_unit = "B"
    setup.speed = "2980"
    for field, value in setup_fields.items():
        setattr(setup, field, value)
    setup.save()
    setup.positions.update(seal_type_size="UHTW 4.750")
    return TcnRevision.objects.get(pk=tcn.pk)


def stored_bytes(tcn):
    with tcn.issued_document.storage.open(tcn.issued_document.name, "rb") as f:
        return f.read()


def issue(tcn, user):
    return issue_tcn(tcn, tcn.row_version, user)


# --- V11 issue validation ------------------------------------------------------------


def test_ready_draft_has_no_issue_errors(project, user):
    assert issue_errors(ready_tcn(project, user)) == []


def test_issue_errors_list_what_is_missing(project, user):
    tcn = create_tcn(project, 1, user)
    tcn.prepared_by = ""
    tcn.project_description = ""
    tcn.save()
    assert issue_errors(tcn) == [
        "Project description is required.",
        "Prepared by is required.",
        "Test Run description is required.",
        "Test unit is required.",
        "Inboard Seal: seal type and size is required.",
        "Outboard Seal: seal type and size is required.",
    ]


def test_at16_issue_without_plug_medium_refused(project, user, file_storage):
    """AT-16 (issue part): a Plug Seal needs its medium before issue."""
    tcn = ready_tcn(project, user, plug_seal_present=True)
    tcn.setup.positions.create(role="plug", seal_type_size="DHTW 4.750")
    with pytest.raises(IssueError) as excinfo:
        issue(tcn, user)
    assert excinfo.value.errors == ["Plug Seal medium is required."]
    assert TcnRevision.objects.get(pk=tcn.pk).status == Status.DRAFT
    assert not [path for path in file_storage.rglob("*") if path.is_file()]

    tcn.setup.plug_medium = "Water"
    tcn.setup.save()
    assert issue(TcnRevision.objects.get(pk=tcn.pk), user).status == Status.ISSUED


def test_revision_needs_a_reason(project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = new_revision(rev_0, user)
    assert issue_errors(rev_1) == ["Reason for revision is required."]


# --- Issue ----------------------------------------------------------------------------


def test_issue_stores_document_hashes_snapshot_and_identity(project, user, other_user, file_storage):
    tcn = ready_tcn(project, user)  # created by Maria Geerts, prepared by MG
    tcn.prepared_by = "MT"
    tcn.save()
    expected_context = dict(build_tcn_context(tcn), is_draft=False)

    issued = issue(tcn, other_user)  # issued by Mark Test
    issued = TcnRevision.objects.get(pk=issued.pk)
    assert issued.status == Status.ISSUED
    assert (issued.created_by, issued.prepared_by, issued.issued_by) == (user, "MT", other_user)
    assert issued.issued_at is not None and issued.issued_at >= issued.created_at

    assert issued.issued_document.name == "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.pdf"
    assert (file_storage / issued.issued_document.name).is_file()
    content = stored_bytes(issued)
    assert issued.issued_document_sha256 == hashlib.sha256(content).hexdigest()
    assert issued.template_sha256 == hashlib.sha256(template_path("tcn.docx").read_bytes()).hexdigest()
    assert issued.issued_snapshot == expected_context

    lines = pdf_lines(content)
    assert "DRAFT — not issued" not in lines
    assert "Prepared by: MT" in " ".join(lines)


def test_issue_refused_when_draft_changed_since_review(project, user, file_storage):
    tcn = ready_tcn(project, user)
    reviewed_version = tcn.row_version
    TcnRevision.objects.filter(pk=tcn.pk).update(row_version=reviewed_version + 1)  # saved meanwhile
    with pytest.raises(StaleDraftError):
        issue_tcn(tcn, reviewed_version, user)
    assert TcnRevision.objects.get(pk=tcn.pk).status == Status.DRAFT
    assert not [path for path in file_storage.rglob("*") if path.is_file()]


def test_issue_validation_failure_changes_nothing(project, user, file_storage):
    tcn = create_tcn(project, 1, user)
    with pytest.raises(IssueError):
        issue(tcn, user)
    after = TcnRevision.objects.get(pk=tcn.pk)
    assert (after.status, after.row_version, after.issued_at) == (Status.DRAFT, 1, None)
    assert not [path for path in file_storage.rglob("*") if path.is_file()]


def test_v15_existing_file_is_never_overwritten(project, user, file_storage):
    tcn = ready_tcn(project, user)
    path = file_storage / "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"earlier file")
    with pytest.raises(IssueError, match="already exists"):
        issue(tcn, user)
    assert path.read_bytes() == b"earlier file"
    assert TcnRevision.objects.get(pk=tcn.pk).status == Status.DRAFT


def test_failure_after_writing_removes_file_and_keeps_draft(project, user, file_storage, monkeypatch):
    tcn = ready_tcn(project, user)
    original_save = TcnRevision.save

    def failing_save(self, *args, **kwargs):
        if self.status == Status.ISSUED:
            raise RuntimeError("database failure while issuing")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(TcnRevision, "save", failing_save)
    with pytest.raises(RuntimeError):
        issue(tcn, user)
    monkeypatch.undo()
    after = TcnRevision.objects.get(pk=tcn.pk)
    assert (after.status, after.issued_document.name, after.row_version) == (Status.DRAFT, "", 1)
    assert not [path for path in file_storage.rglob("*") if path.is_file()]


def test_issued_tcn_cannot_be_issued_again(project, user):
    tcn = issue(ready_tcn(project, user), user)
    with pytest.raises(ImmutableTcnError):
        issue_tcn(tcn, tcn.row_version, user)


def test_issuing_revision_supersedes_previous_and_keeps_its_file(project, user, file_storage):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_0_file = stored_bytes(rev_0)
    rev_0_snapshot = rev_0.issued_snapshot

    rev_1 = new_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    rev_1 = issue(TcnRevision.objects.get(pk=rev_1.pk), user)

    rev_0 = TcnRevision.objects.get(pk=rev_0.pk)
    assert (rev_0.status, rev_1.status) == (Status.SUPERSEDED, Status.ISSUED)
    assert rev_1.issued_document.name == "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001-rev1.pdf"
    assert rev_1.issued_snapshot["tcn_no"] == "001 rev 1"
    assert "Run/TCN No.: 001 rev 1" in " ".join(pdf_lines(stored_bytes(rev_1)))
    # Rev 0 stays exactly as issued.
    assert stored_bytes(rev_0) == rev_0_file
    assert rev_0.issued_document_sha256 == hashlib.sha256(rev_0_file).hexdigest()
    assert rev_0.issued_snapshot == rev_0_snapshot and rev_0.issued_snapshot["speed"] == "2980 rpm"
    assert rev_0.test_run_id == rev_1.test_run_id  # one Test Run, two revisions


# --- AT-6: issued TCN immutable ---------------------------------------------------------


def test_at6_issued_tcn_is_immutable(project, user):
    tcn = issue(ready_tcn(project, user), user)
    content = stored_bytes(tcn)
    for field, value in [("issued_by", None), ("issued_at", None), ("prepared_by", "XX"), ("issued_snapshot", {})]:
        changed = TcnRevision.objects.get(pk=tcn.pk)
        setattr(changed, field, value)
        with pytest.raises(ImmutableTcnError):
            changed.save()
    with pytest.raises(ImmutableTcnError):
        TcnRevision.objects.get(pk=tcn.pk).delete()
    setup = TcnRevision.objects.get(pk=tcn.pk).setup
    setup.speed = "1500"
    with pytest.raises(ImmutableTcnError):
        setup.save()
    with pytest.raises(ProtectedError):
        setup.delete()
    after = TcnRevision.objects.get(pk=tcn.pk)
    assert after.issued_by == user and after.setup.speed == "2980"
    assert stored_bytes(after) == content


# --- AT-17: project number lock ------------------------------------------------------------


def project_form(project, project_no):
    return ProjectForm(
        {"project_no": project_no, "description": project.description, "customer": ""}, instance=project
    )


def test_at17_project_no_editable_while_only_drafts(project, user):
    ready_tcn(project, user)
    form = project_form(project, "2026RSD04TL")
    assert not form.fields["project_no"].disabled
    assert form.is_valid()
    form.save()
    assert Project.objects.get(pk=project.pk).project_no == "2026RSD04TL"


@pytest.mark.parametrize("later", ["issued", "superseded", "cancelled"])
def test_at17_project_no_locked_after_first_issue(project, user, later):
    tcn = issue(ready_tcn(project, user), user)
    if later == "superseded":
        rev_1 = new_revision(tcn, user)
        rev_1.revision_reason = "x"
        rev_1.save()
        issue(TcnRevision.objects.get(pk=rev_1.pk), user)
    elif later == "cancelled":
        cancel(TcnRevision.objects.get(pk=tcn.pk), user)

    project = Project.objects.get(pk=project.pk)
    form = project_form(project, "2026RSD99TL")
    assert form.fields["project_no"].disabled
    assert form.is_valid()  # the posted number is ignored
    form.save()
    assert Project.objects.get(pk=project.pk).project_no == "2026RSD03TL"

    project.project_no = "2026RSD99TL"  # model level, not only the form
    with pytest.raises(ValidationError):
        project.full_clean()
    with pytest.raises(ValidationError):
        project.save()
    assert Project.objects.get(pk=project.pk).project_no == "2026RSD03TL"


def test_other_project_fields_stay_editable_after_issue(project, user):
    issue(ready_tcn(project, user), user)
    project = Project.objects.get(pk=project.pk)
    project.description = "Corrected description"
    project.save()
    project.project_no = "2026rsd03tl"  # same number, other case: not a change
    project.save()
    assert Project.objects.get(pk=project.pk).description == "Corrected description"

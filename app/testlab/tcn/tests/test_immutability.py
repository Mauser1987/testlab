"""AT-6 (model part): issued TCN revisions cannot change, at the domain level."""

from datetime import timedelta

import pytest
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from testlab.projects.models import SealPosition
from testlab.tcn.models import ImmutableTcnError, InvalidTransitionError, TcnRevision, TcnRuleError, TestRun

from .factories import cancel, issue, make_project, make_run, new_revision, supersede

pytestmark = pytest.mark.django_db

Status = TcnRevision.Status


@pytest.fixture
def project(user):
    return make_project(user)


@pytest.fixture
def draft(project, user):
    return make_run(project, user).revisions.get()


def locked(status, draft, user):
    """A revision in the given non-draft status."""
    issue(draft, user)
    if status == Status.SUPERSEDED:
        rev_1 = new_revision(draft, user)
        supersede(draft)
        issue(rev_1, user)
    elif status == Status.CANCELLED:
        cancel(draft, user)
    assert draft.status == status
    return TcnRevision.objects.get(pk=draft.pk)


LOCKED = [Status.ISSUED, Status.SUPERSEDED, Status.CANCELLED]


# --- Status transitions -------------------------------------------------------


def test_created_as_draft_only(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    with pytest.raises(InvalidTransitionError):
        TcnRevision.objects.create(
            test_run=run,
            status=Status.ISSUED,
            issued_at=timezone.now(),
            issued_by=user,
            setup=project.default_setup.clone(),
            source_kind=TcnRevision.SourceKind.PROJECT_DEFAULTS,
            created_by=user,
            updated_by=user,
        )


def test_allowed_transitions(draft, user):
    issue(draft, user)
    rev_1 = new_revision(draft, user)
    supersede(draft)  # issuing rev 1 supersedes rev 0 (service in commit 10)
    issue(rev_1, user)
    cancel(rev_1, user)
    assert list(draft.test_run.revisions.values_list("status", flat=True)) == ["superseded", "cancelled"]


@pytest.mark.parametrize("new_status", [Status.SUPERSEDED, Status.CANCELLED])
def test_draft_can_only_become_issued(draft, user, new_status):
    draft.status = new_status
    draft.issued_at, draft.issued_by = timezone.now(), user
    with pytest.raises(InvalidTransitionError):
        draft.save()


@pytest.mark.parametrize(
    "old_status,new_status",
    [
        (Status.ISSUED, Status.DRAFT),
        (Status.SUPERSEDED, Status.ISSUED),
        (Status.SUPERSEDED, Status.DRAFT),
        (Status.SUPERSEDED, Status.CANCELLED),
        (Status.CANCELLED, Status.ISSUED),
        (Status.CANCELLED, Status.DRAFT),
    ],
)
def test_forbidden_transitions(draft, user, old_status, new_status):
    tcn = locked(old_status, draft, user)
    tcn.status = new_status
    with pytest.raises(TcnRuleError):  # ImmutableTcnError for "back to draft"
        tcn.save()
    assert TcnRevision.objects.get(pk=tcn.pk).status == old_status


def test_transition_cannot_carry_content_changes(draft, user):
    tcn = issue(draft, user)
    tcn.status = Status.SUPERSEDED
    tcn.project_description = "changed while superseding"
    with pytest.raises(ImmutableTcnError, match="project_description"):
        tcn.save()

    tcn = TcnRevision.objects.get(pk=draft.pk)
    tcn.status = Status.CANCELLED
    tcn.cancelled_at, tcn.cancelled_by, tcn.cancel_reason = timezone.now(), user, "x"
    tcn.issued_at = timezone.now()
    with pytest.raises(ImmutableTcnError, match="issued_at"):
        tcn.save()


# --- Draft edits ---------------------------------------------------------------


def test_draft_content_is_editable(draft):
    draft.project_description = "ADNOC BAB UHTW/UHTW 4.750/4.750"
    draft.prepared_by = "MT"
    draft.save()
    draft.setup.speed = "2980"
    draft.setup.save()
    position = draft.setup.positions.first()
    position.seal_type_size = "UHTW 4.750"
    position.save()
    draft.refresh_from_db()
    assert (draft.project_description, draft.setup.speed) == ("ADNOC BAB UHTW/UHTW 4.750/4.750", "2980")


@pytest.mark.parametrize("field", ["test_run", "revision", "setup", "source_kind", "created_date"])
def test_identity_fields_fixed_even_in_draft(draft, project, user, field):
    values = {
        "test_run": TestRun.objects.create(project=project, run_no=9, created_by=user),
        "revision": 5,
        "setup": project.default_setup.clone(),
        "source_kind": TcnRevision.SourceKind.TCN_COPY,
        "created_date": timezone.localdate() - timedelta(days=3),
    }
    setattr(draft, field, values[field])
    with pytest.raises(TcnRuleError, match=field):
        draft.save()


def test_draft_bulk_update_allowed_but_not_for_status_or_identity(draft, user):
    TcnRevision.objects.filter(pk=draft.pk).update(prepared_by="MT")
    assert TcnRevision.objects.get(pk=draft.pk).prepared_by == "MT"
    with pytest.raises(TcnRuleError):
        TcnRevision.objects.filter(pk=draft.pk).update(status=Status.ISSUED, issued_at=timezone.now(), issued_by=user)
    with pytest.raises(TcnRuleError):
        TcnRevision.objects.filter(pk=draft.pk).update(revision=3)


# --- Locked revisions -----------------------------------------------------------


@pytest.mark.parametrize("status", LOCKED)
def test_locked_revision_cannot_be_saved(draft, user, status):
    tcn = locked(status, draft, user)
    before = TcnRevision.objects.filter(pk=tcn.pk).values().get()

    tcn.project_description = "rewritten"
    with pytest.raises(ImmutableTcnError):
        tcn.save()

    unchanged = TcnRevision.objects.get(pk=tcn.pk)
    with pytest.raises(ImmutableTcnError):  # even without changes: no silent re-save
        unchanged.save()

    assert TcnRevision.objects.filter(pk=tcn.pk).values().get() == before


@pytest.mark.parametrize("status", LOCKED)
def test_locked_revision_cannot_be_deleted(draft, user, status):
    tcn = locked(status, draft, user)
    with pytest.raises(ImmutableTcnError):
        tcn.delete()
    with pytest.raises(ImmutableTcnError):
        TcnRevision.objects.filter(pk=tcn.pk).delete()
    assert TcnRevision.objects.filter(pk=tcn.pk).exists()


@pytest.mark.parametrize("status", LOCKED)
def test_locked_revision_cannot_be_bulk_updated(draft, user, status):
    tcn = locked(status, draft, user)
    with pytest.raises(ImmutableTcnError):
        TcnRevision.objects.filter(pk=tcn.pk).update(prepared_by="XX")
    with pytest.raises(ImmutableTcnError):
        TcnRevision.objects.all().update(prepared_by="XX")
    assert TcnRevision.objects.get(pk=tcn.pk).prepared_by == "MG"


@pytest.mark.parametrize("status", LOCKED)
def test_locked_revision_setup_and_positions_are_frozen(draft, user, status):
    tcn = locked(status, draft, user)
    setup = tcn.setup
    setup.speed = "1500"
    with pytest.raises(ImmutableTcnError):
        setup.save()
    with pytest.raises(ProtectedError):  # referenced by the TCN revision
        setup.delete()

    position = setup.positions.first()
    position.seal_type_size = "changed"
    with pytest.raises(ImmutableTcnError):
        position.save()
    # Raised inside Django's delete transaction: isolate it in a savepoint.
    with pytest.raises(ImmutableTcnError), transaction.atomic():
        position.delete()
    with pytest.raises(ImmutableTcnError), transaction.atomic():
        setup.positions.all().delete()
    with pytest.raises(ImmutableTcnError):
        SealPosition.objects.create(setup=setup, role="plug")

    setup.refresh_from_db()
    assert setup.speed == ""
    assert setup.positions.count() == 2


def test_position_cannot_be_moved_out_of_issued_setup(draft, project, user):
    issue(draft, user)
    position = draft.setup.positions.first()
    position.setup = project.default_setup.clone()
    with pytest.raises(ImmutableTcnError):
        position.save()


def test_stale_draft_object_cannot_overwrite_issued_revision(draft, user):
    stale = TcnRevision.objects.get(pk=draft.pk)
    issue(draft, user)
    stale.project_description = "edited in an old browser tab"
    with pytest.raises(ImmutableTcnError):
        stale.save()
    with pytest.raises(ImmutableTcnError):
        stale.delete()


def test_issued_revision_unaffected_by_project_default_changes(draft, project, user):
    issue(draft, user)
    defaults = project.default_setup
    defaults.speed = "3600"
    defaults.process_medium = "Oil"
    defaults.save()
    project.description = "RENAMED"
    project.save()
    tcn = TcnRevision.objects.get(pk=draft.pk)
    assert (tcn.setup.speed, tcn.setup.process_medium) == ("", "")
    assert tcn.project_description == "TEST UHTW 4.750"


def test_new_revision_leaves_issued_revision_untouched(draft, user):
    issue(draft, user)
    rev_1 = new_revision(draft, user)
    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    assert TcnRevision.objects.get(pk=draft.pk).setup.speed == ""


def test_run_number_fixed_once_a_revision_is_issued(draft, user):
    run = draft.test_run
    run.run_no = 7
    run.save()  # only drafts: still correctable
    issue(draft, user)
    run.run_no = 8
    with pytest.raises(ImmutableTcnError):
        run.save()
    assert TestRun.objects.get(pk=run.pk).run_no == 7

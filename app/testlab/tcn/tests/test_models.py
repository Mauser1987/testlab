import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from testlab.projects.arrangements import Arrangement
from testlab.projects.models import RunSetup, SealPosition
from testlab.tcn.models import TcnRevision, TcnRuleError, TestRun

from .factories import cancel, issue, make_project, make_run, new_revision

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user)


def rev0(run):
    return run.revisions.get(revision=0)


# --- TestRun numbering -------------------------------------------------------


def test_run_no_unique_per_project(project, user):
    make_run(project, user, run_no=1)
    duplicate = TestRun(project=project, run_no=1, created_by=user)
    with pytest.raises(ValidationError) as excinfo:
        duplicate.full_clean()
    assert "Run number already used!" in str(excinfo.value)
    with pytest.raises(IntegrityError):
        duplicate.save()


def test_same_run_no_in_other_project(project, user):
    other = make_project(user, project_no="2099RSD02TL")
    make_run(project, user, run_no=1)
    make_run(other, user, run_no=1)
    assert TestRun.objects.filter(run_no=1).count() == 2


@pytest.mark.parametrize("run_no", [0, 1000])
def test_run_no_range(project, user, run_no):
    run = TestRun(project=project, run_no=run_no, created_by=user)
    with pytest.raises(ValidationError):
        run.full_clean()
    with pytest.raises(IntegrityError):  # enforced by the database too
        TestRun.objects.bulk_create([run])


def test_run_display_and_next_run_no(project, user):
    assert TestRun.next_run_no(project) == 1
    make_run(project, user, run_no=1)
    run = make_run(project, user, run_no=4)  # gaps allowed
    assert run.display_no == "004"
    assert TestRun.next_run_no(project) == 5
    assert TestRun.next_run_no(make_project(user, project_no="2099RSD02TL")) == 1


def test_tcn_numbering(project, user):
    first = rev0(make_run(project, user, run_no=2))
    assert (first.tcn_no, str(first)) == ("002", "TCN002")
    issue(first, user)
    second = new_revision(first, user)
    assert (second.tcn_no, str(second)) == ("002 rev 1", "TCN002 rev 1")


# --- Revisions ---------------------------------------------------------------


def test_revisions_stay_within_one_test_run(project, user):
    run = make_run(project, user)
    rev_0 = issue(rev0(run), user)
    rev_1 = new_revision(rev_0, user)
    assert TestRun.objects.count() == 1
    assert list(run.revisions.values_list("revision", flat=True)) == [0, 1]
    assert rev_1.test_run == run
    assert rev_1.source_tcn == rev_0


def test_revision_numbers_are_consecutive(project, user):
    run = make_run(project, user)
    issue(rev0(run), user)
    skipped = TcnRevision(
        test_run=run,
        revision=2,
        setup=rev0(run).setup.clone(),
        source_kind=TcnRevision.SourceKind.NEW_REVISION,
        source_tcn=rev0(run),
        created_by=user,
        updated_by=user,
    )
    with pytest.raises(TcnRuleError, match="next revision of TCN001 is 1"):
        skipped.save()


def test_first_revision_is_zero(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    with pytest.raises(TcnRuleError):
        TcnRevision.objects.create(
            test_run=run,
            revision=1,
            setup=project.default_setup.clone(),
            source_kind=TcnRevision.SourceKind.PROJECT_DEFAULTS,
            created_by=user,
            updated_by=user,
        )


def test_new_revision_must_come_from_same_run(project, user):
    other = issue(rev0(make_run(project, user, run_no=1)), user)
    run = make_run(project, user, run_no=2)
    issue(rev0(run), user)
    with pytest.raises(TcnRuleError, match="same Test Run"):
        TcnRevision.objects.create(
            test_run=run,
            revision=1,
            setup=other.setup.clone(),
            source_kind=TcnRevision.SourceKind.NEW_REVISION,
            source_tcn=other,
            created_by=user,
            updated_by=user,
        )


def copy_of(source, run, user):
    return TcnRevision(
        test_run=run,
        setup=source.setup.clone(),
        source_kind=TcnRevision.SourceKind.TCN_COPY,
        source_tcn=source,
        created_by=user,
        updated_by=user,
    )


def test_tcn_copy_within_project(project, user):
    source = issue(rev0(make_run(project, user, run_no=1)), user)
    run = TestRun.objects.create(project=project, run_no=2, created_by=user)
    copy_of(source, run, user).save()
    assert rev0(run).source_tcn == source


def test_tcn_copy_from_other_project_rejected(project, user):
    # Project A / TCN004 → Project B / TCN001 is not a TCN copy in M1.
    other = make_project(user, project_no="2099RSD02TL")
    source = issue(rev0(make_run(other, user, run_no=4)), user)
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    with pytest.raises(TcnRuleError, match="same project"):
        copy_of(source, run, user).save()
    assert not run.revisions.exists()


# --- RunSetup ownership (snapshot) ---------------------------------------------


def test_tcn_setup_is_independent_copy_of_project_defaults(project, user):
    defaults = project.default_setup
    defaults.arrangement = Arrangement.SINGLE
    defaults.plug_seal_present = True
    defaults.speed = "2980"
    defaults.process_medium = "Water"
    defaults.plug_medium = "Oil"
    defaults.monitored_parameters = ["process_pressure", "test_leakage"]
    defaults.save()
    defaults.positions.all().delete()
    defaults.positions.create(role="plug", seal_type_size="DHTW 4.750")
    defaults.positions.create(role="test", seal_type_size="UHTW 4.750")

    tcn = rev0(make_run(project, user))
    setup = tcn.setup
    assert setup.pk != defaults.pk
    assert (setup.arrangement, setup.plug_seal_present, setup.speed, setup.plug_medium) == (
        Arrangement.SINGLE, True, "2980", "Oil",
    )  # fmt: skip
    assert setup.monitored_parameters == ["process_pressure", "test_leakage"]
    copied = {p.role: p for p in setup.positions.all()}
    assert copied["test"].seal_type_size == "UHTW 4.750"
    assert not set(setup.positions.values_list("pk", flat=True)) & set(defaults.positions.values_list("pk", flat=True))

    # Later edits of the project defaults change nothing in the TCN.
    defaults.speed = "1500"
    defaults.monitored_parameters.append("process_flow")
    defaults.save()
    defaults.positions.filter(role="test").update(seal_type_size="CHANGED")
    setup.refresh_from_db()
    assert setup.speed == "2980"
    assert setup.monitored_parameters == ["process_pressure", "test_leakage"]
    assert setup.positions.get(role="test").seal_type_size == "UHTW 4.750"


def test_tcn_cannot_use_project_defaults_directly(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    with pytest.raises(TcnRuleError, match="copy of the project defaults"):
        TcnRevision.objects.create(
            test_run=run,
            setup=project.default_setup,
            source_kind=TcnRevision.SourceKind.PROJECT_DEFAULTS,
            created_by=user,
            updated_by=user,
        )


def test_setup_is_never_shared_between_revisions(project, user):
    first = rev0(make_run(project, user, run_no=1))
    run = TestRun.objects.create(project=project, run_no=2, created_by=user)
    with pytest.raises(IntegrityError):
        TcnRevision.objects.create(
            test_run=run,
            setup=first.setup,
            source_kind=TcnRevision.SourceKind.TCN_COPY,
            source_tcn=first,
            created_by=user,
            updated_by=user,
        )


# --- Database constraints ----------------------------------------------------
# bulk_create bypasses save() and signals, so these prove the database itself
# enforces the rule.


def unsaved(run, user, **fields):
    values = {
        "test_run": run,
        "setup": RunSetup.objects.create(),
        "source_kind": TcnRevision.SourceKind.PROJECT_DEFAULTS,
        "created_by": user,
        "updated_by": user,
    }
    values.update(fields)
    return TcnRevision(**values)


def assert_db_rejects(tcn):
    with pytest.raises(IntegrityError), transaction.atomic():
        TcnRevision.objects.bulk_create([tcn])


def test_db_one_draft_per_run(project, user):
    run = make_run(project, user)
    assert_db_rejects(unsaved(run, user, revision=1, source_kind="new_revision", source_tcn=rev0(run)))


def test_db_one_issued_per_run(project, user):
    run = make_run(project, user)
    issue(rev0(run), user)
    assert_db_rejects(
        unsaved(run, user, revision=1, source_kind="new_revision", source_tcn=rev0(run),
                status="issued", issued_at=timezone.now(), issued_by=user)
    )  # fmt: skip


def test_db_unique_revision_per_run(project, user):
    run = make_run(project, user)
    issue(rev0(run), user)
    assert_db_rejects(unsaved(run, user, status="cancelled", issued_at=timezone.now(), issued_by=user,
                              cancelled_at=timezone.now(), cancelled_by=user, cancel_reason="x"))  # fmt: skip


def test_db_rejects_unknown_status_and_source_kind(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    assert_db_rejects(unsaved(run, user, status="approved"))
    assert_db_rejects(unsaved(run, user, source_kind="legacy_import"))


def test_db_source_tcn_matches_source_kind(project, user):
    run = make_run(project, user)
    source = rev0(run)
    other = TestRun.objects.create(project=project, run_no=2, created_by=user)
    assert_db_rejects(unsaved(other, user, source_kind="tcn_copy"))  # copy without source
    assert_db_rejects(unsaved(other, user, source_kind="project_defaults", source_tcn=source))


def test_db_revision_matches_source_kind(project, user):
    run = make_run(project, user)
    source = issue(rev0(run), user)
    other = TestRun.objects.create(project=project, run_no=2, created_by=user)
    assert_db_rejects(unsaved(other, user, source_kind="new_revision", source_tcn=source))  # rev 0
    assert_db_rejects(unsaved(run, user, revision=1, source_kind="tcn_copy", source_tcn=source))


def test_db_issue_data_required_exactly_when_issued(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    assert_db_rejects(unsaved(run, user, status="issued"))
    assert_db_rejects(unsaved(run, user, status="issued", issued_at=timezone.now()))
    assert_db_rejects(unsaved(run, user, issued_at=timezone.now(), issued_by=user))  # draft with issue data


def test_db_cancel_data_required_exactly_when_cancelled(project, user):
    run = TestRun.objects.create(project=project, run_no=1, created_by=user)
    issued = {"issued_at": timezone.now(), "issued_by": user}
    cancelled = {"cancelled_at": timezone.now(), "cancelled_by": user}
    assert_db_rejects(unsaved(run, user, status="cancelled", **issued, **cancelled))  # no reason
    assert_db_rejects(unsaved(run, user, status="cancelled", **issued, cancel_reason="x"))
    assert_db_rejects(unsaved(run, user, status="issued", **issued, **cancelled, cancel_reason="x"))


# --- Deletion ----------------------------------------------------------------


def test_deleting_draft_rev0_removes_setup_positions_and_run(project, user):
    run = make_run(project, user)
    tcn = rev0(run)
    setup_id = tcn.setup_id
    tcn.delete()
    assert not TestRun.objects.filter(pk=run.pk).exists()
    assert not RunSetup.objects.filter(pk=setup_id).exists()
    assert not SealPosition.objects.filter(setup_id=setup_id).exists()
    assert RunSetup.objects.filter(pk=project.default_setup_id).exists()


def test_deleting_draft_revision_keeps_run_and_issued_revision(project, user):
    run = make_run(project, user)
    rev_0 = issue(rev0(run), user)
    rev_1 = new_revision(rev_0, user)
    setup_id = rev_1.setup_id
    rev_1.delete()
    assert list(run.revisions.all()) == [rev_0]
    assert not RunSetup.objects.filter(pk=setup_id).exists()
    assert RunSetup.objects.filter(pk=rev_0.setup_id).exists()


def test_queryset_delete_of_drafts_also_removes_owned_records(project, user):
    make_run(project, user, run_no=1)
    make_run(project, user, run_no=2)
    TcnRevision.objects.all().delete()
    assert not TestRun.objects.exists()
    assert list(RunSetup.objects.values_list("pk", flat=True)) == [project.default_setup_id]


def test_run_with_revisions_cannot_be_deleted(project, user):
    run = make_run(project, user)
    with pytest.raises(ProtectedError):
        run.delete()


def test_project_with_runs_cannot_be_deleted(project, user):
    make_run(project, user)
    with pytest.raises(ProtectedError):
        project.delete()


def test_revision_used_as_source_cannot_be_deleted(project, user):
    source = rev0(make_run(project, user, run_no=1))
    run = TestRun.objects.create(project=project, run_no=2, created_by=user)
    TcnRevision.objects.create(
        test_run=run,
        setup=source.setup.clone(),
        source_kind=TcnRevision.SourceKind.TCN_COPY,
        source_tcn=source,
        created_by=user,
        updated_by=user,
    )
    with pytest.raises(ProtectedError):
        source.delete()


def test_draft_setup_cannot_be_deleted_on_its_own(project, user):
    tcn = rev0(make_run(project, user))
    with pytest.raises(ProtectedError):
        tcn.setup.delete()


def test_cancelled_run_keeps_its_records(project, user):
    run = make_run(project, user)
    tcn = cancel(issue(rev0(run), user), user)
    assert tcn.cancel_reason == "Test cancelled by customer"
    assert TestRun.objects.filter(pk=run.pk).exists()

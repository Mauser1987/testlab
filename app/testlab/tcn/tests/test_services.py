"""Create / copy TCN and draft saving with optimistic locking (M1 spec §7, V4, V10)."""

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from testlab.projects.arrangements import Arrangement
from testlab.projects.setup_forms import RunSetupEditor
from testlab.projects.tests.test_defaults_form import post_data
from testlab.tcn.forms import TcnHeaderForm
from testlab.tcn.models import ImmutableTcnError, TcnRevision, TcnRuleError, TestRun
from testlab.tcn.services import StaleDraftError, create_tcn, default_copy_source, initials, save_draft

from .factories import issue, make_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    project = make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")
    defaults = project.default_setup
    defaults.test_unit = "TU5"
    defaults.speed = "2980"
    defaults.seal_support_pressure = "70"
    defaults.monitored_parameters = ["seal_support_pressure", "inboard_leakage"]
    defaults.save()
    defaults.positions.filter(role="inboard").update(seal_type_size="UHTW 4.750")
    return project


def test_initials(user):
    assert initials(user) == "MG"
    assert initials(User(username="x", first_name=" mark ", last_name="")) == "M"
    assert initials(User(username="x")) == ""


def test_create_from_project_defaults(project, user):
    tcn = create_tcn(project, 1, user)
    assert str(tcn) == "TCN001"
    assert (tcn.revision, tcn.status) == (0, TcnRevision.Status.DRAFT)
    assert tcn.source_kind == TcnRevision.SourceKind.PROJECT_DEFAULTS and tcn.source_tcn is None
    assert tcn.project_description == "ADNOC BAB UHTW/UHTW 4.750/4.750"
    assert tcn.prepared_by == "MG"
    assert (tcn.created_by, tcn.updated_by, tcn.test_run.created_by) == (user, user, user)
    setup = tcn.setup
    assert setup.pk != project.default_setup_id
    assert (setup.test_unit, setup.speed, setup.seal_support_pressure) == ("TU5", "2980", "70")
    assert setup.monitored_parameters == ["seal_support_pressure", "inboard_leakage"]
    assert setup.positions.get(role="inboard").seal_type_size == "UHTW 4.750"


def test_copy_takes_source_setup_and_current_project_description(project, user, other_user):
    source = create_tcn(project, 1, user)
    source.setup.run_description = "Run 1 instructions"
    source.setup.speed = "1500"
    source.setup.save()
    source.setup.positions.filter(role="outboard").update(rotating_face="C100603035 (SL WAVY)")
    project.description = "Corrected description"
    project.save()

    copy = create_tcn(project, 2, other_user, source=source)
    assert copy.source_kind == TcnRevision.SourceKind.TCN_COPY and copy.source_tcn == source
    assert copy.project_description == "Corrected description"
    assert copy.prepared_by == "MT"
    assert (copy.setup.run_description, copy.setup.speed) == ("Run 1 instructions", "1500")
    assert copy.setup.positions.get(role="outboard").rotating_face == "C100603035 (SL WAVY)"

    copy.setup.speed = "3600"
    copy.setup.save()
    source.setup.refresh_from_db()
    assert source.setup.speed == "1500"


def test_copy_of_issued_tcn_leaves_it_untouched(project, user):
    source = issue(create_tcn(project, 1, user), user)
    copy = create_tcn(project, 2, user, source=source)
    copy.setup.speed = "1500"
    copy.setup.save()
    assert TcnRevision.objects.get(pk=source.pk).setup.speed == "2980"


def test_duplicate_run_no_rejected(project, user):
    create_tcn(project, 1, user)
    with pytest.raises(ValidationError) as excinfo:
        create_tcn(project, 1, user)
    assert excinfo.value.message_dict == {"run_no": ["Run number already used!"]}
    assert TestRun.objects.count() == 1


def test_cross_project_copy_rejected_by_service(project, user):
    other = make_project(user, project_no="2099RSD02TL")
    source = create_tcn(other, 4, user)
    with pytest.raises(TcnRuleError, match="same project"):
        create_tcn(project, 1, user, source=source)
    assert not project.test_runs.exists()  # the transaction was rolled back


def test_default_copy_source_is_current_revision_of_highest_run(project, user):
    assert default_copy_source(project) is None
    create_tcn(project, 1, user)
    third = issue(create_tcn(project, 3, user), user)
    create_tcn(project, 2, user)
    assert default_copy_source(project) == third


# --- save_draft ----------------------------------------------------------------


def bind(tcn, row_version=None, **overrides):
    data = post_data(tcn.setup, **overrides)
    data.update(
        project_description=overrides.get("project_description", tcn.project_description),
        prepared_by=overrides.get("prepared_by", tcn.prepared_by),
        row_version=tcn.row_version if row_version is None else row_version,
    )
    header = TcnHeaderForm(data, instance=tcn)
    editor = RunSetupEditor(tcn.setup, data)
    assert header.is_valid() and editor.is_valid(), (header.errors, editor.form.errors)
    return header, editor


def test_save_draft_saves_header_and_setup(project, user, other_user):
    tcn = create_tcn(project, 1, user)
    header, editor = bind(tcn, prepared_by="mt", speed="1500", arrangement=Arrangement.DUAL_PRESSURIZED)
    save_draft(tcn, header, editor, 1, other_user)
    tcn = TcnRevision.objects.get(pk=tcn.pk)
    assert (tcn.prepared_by, tcn.setup.speed) == ("MT", "1500")
    assert (tcn.row_version, tcn.updated_by) == (2, other_user)


def test_save_draft_refuses_stale_version(project, user, other_user):
    tcn = create_tcn(project, 1, user)
    first = TcnRevision.objects.get(pk=tcn.pk)
    second = TcnRevision.objects.get(pk=tcn.pk)

    save_draft(first, *bind(first, speed="1500"), 1, other_user)
    header, editor = bind(second, speed="3600")
    with pytest.raises(StaleDraftError, match="changed by Mark Test"):
        save_draft(second, header, editor, 1, user)

    tcn.refresh_from_db()
    assert tcn.row_version == 2
    assert TcnRevision.objects.get(pk=tcn.pk).setup.speed == "1500"


def test_save_draft_refuses_issued_tcn(project, user):
    tcn = create_tcn(project, 1, user)
    stale = TcnRevision.objects.get(pk=tcn.pk)
    header, editor = bind(stale, speed="1500")
    issue(tcn, user)
    with pytest.raises(ImmutableTcnError):
        save_draft(stale, header, editor, 1, user)
    assert TcnRevision.objects.get(pk=tcn.pk).setup.speed == "2980"

"""Acceptance requirements: Test Program baseline, approved TCN changes, Result items with their source (M2E)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from testlab.documents.render import ChromiumTemplate
from testlab.documents.tcn_context import build_tcn_context
from testlab.documents.tests.html_text import html_lines
from testlab.projects.models import ProgramRequirement, TestProgram
from testlab.results import requirements, services
from testlab.results.models import AcceptanceItem, Assessment
from testlab.tcn.models import ImmutableTcnError, TcnRequirementChange
from testlab.tcn.services import create_revision
from testlab.tcn.tests.factories import issue

from .helpers import make_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(user):
    return make_run(user, "dual_pressurized")


@pytest.fixture
def program(run, user):
    program = TestProgram.objects.create(project=run.project, document_no="TP-7", revision="A",
                                         title="Qualification", objective="Prove it.", updated_by=user)  # fmt: skip
    ProgramRequirement.objects.create(program=program, number=1, criterion="Leakage", basis="leakage_rate",
                                      comparison="<=", limit=Decimal("10"), unit="ml/h", updated_by=user)  # fmt: skip
    ProgramRequirement.objects.create(program=program, number=2, criterion="Test duration", basis="running_hours",
                                      comparison=">=", limit=Decimal("100"), unit="h", updated_by=user)  # fmt: skip
    ProgramRequirement.objects.create(program=program, number=3, criterion="Face wear", basis="wear_rate",
                                      face="rotor", comparison="<=", limit=Decimal("0.000003"), unit="in/h",
                                      updated_by=user)  # fmt: skip
    return program


def p(program, number):
    return program.requirements.get(number=number)


def change(tcn, action, target=None, **fields):
    return TcnRequirementChange.objects.create(tcn=tcn, action=action, program_requirement=target,
                                               reason=fields.pop("reason", "Customer agreement"), **fields)  # fmt: skip


def items(result):
    return list(result.acceptance_items.order_by("order", "pk").select_related("component"))


def test_program_requirements_become_items_per_seal_and_per_face(run, program, user):
    result = services.create_result(run, user)
    requirements.sync_requirements(result, user)
    found = [(i.criterion, i.position, i.component.label if i.component else "", i.source) for i in items(result)]
    assert found == [
        ("Leakage", "inboard", "", "Test Program TP-7 rev A P1"),
        ("Leakage", "outboard", "", "Test Program TP-7 rev A P1"),
        ("Test duration", "", "", "Test Program TP-7 rev A P2"),
        ("Face wear", "", "IB Rotor", "Test Program TP-7 rev A P3"),  # rotors only (face = rotor)
        ("Face wear", "", "OB Rotor", "Test Program TP-7 rev A P3"),
    ]
    assert all(i.assessment == "" for i in items(result))  # missing until assessed


def test_draft_tcn_changes_are_pending_not_applied(run, program, user):
    tcn = run.current_revision()
    change(tcn, "replace", p(program, 1), criterion="Leakage", basis="leakage_rate", comparison="<=",
           limit=Decimal("20"), unit="ml/h")  # fmt: skip
    result = services.create_result(run, user)
    requirements.sync_requirements(result, user)
    assert {i.limit for i in items(result) if i.basis == "leakage_rate"} == {Decimal("10")}
    assert len(requirements.pending_changes(run)) == 1


def test_an_issued_tcn_change_overrides_the_program_for_the_run(run, program, user):
    tcn = run.current_revision()
    change(tcn, "replace", p(program, 1), criterion="Leakage, run-in", basis="leakage_rate", comparison="<=",
           limit=Decimal("20"), unit="ml/h", reason="Run-in test")  # fmt: skip
    change(tcn, "not_applicable", p(program, 3), reason="SiC rotors: no wear expected")
    change(tcn, "add", criterion="Torque", basis="manual", requirement_text="Breakaway torque below 50 Nm")
    issue(tcn, user)
    result = services.create_result(run, user)
    requirements.sync_requirements(result, user)
    by_criterion = {}
    for i in items(result):
        by_criterion.setdefault(i.criterion, []).append(i)
    leakage = by_criterion["Leakage, run-in"]
    assert [i.limit for i in leakage] == [Decimal("20"), Decimal("20")] and "Leakage" not in by_criterion
    assert leakage[0].source.startswith("TCN001, issued") and leakage[0].source.endswith("replaces Test Program TP-7 rev A P1")
    wear = by_criterion["Face wear"]
    assert all(i.assessment == Assessment.NOT_APPLICABLE for i in wear)  # explicit, not missing
    assert "not applicable to this run per TCN001" in wear[0].source and "SiC rotors" in wear[0].remark
    (torque,) = by_criterion["Torque"]
    assert torque.source.endswith("additional requirement") and torque.tcn_change is not None
    assert by_criterion["Test duration"][0].source == "Test Program TP-7 rev A P2"  # unchanged


def test_sync_keeps_the_engineers_assessment_and_follows_requirement_edits(run, program, user):
    result = services.create_result(run, user)
    requirements.sync_requirements(result, user)
    duration = next(i for i in items(result) if i.criterion == "Test duration")
    duration.assessment, duration.remark = Assessment.NOT_EVALUATED, "Stopped early by the customer"
    duration.save()
    requirement = p(program, 2)
    requirement.limit = Decimal("150")
    requirement.save()
    requirements.sync_requirements(result, user)
    duration.refresh_from_db()
    assert duration.limit == Decimal("150")  # the requirement follows its source while Draft
    assert (duration.assessment, duration.remark) == (Assessment.NOT_EVALUATED, "Stopped early by the customer")


def test_withdrawn_requirement_is_removed_or_kept_when_assessed(run, program, user):
    result = services.create_result(run, user)
    requirements.sync_requirements(result, user)
    wear = [i for i in items(result) if i.criterion == "Face wear"]
    wear[0].remark = "Checked"
    wear[0].save()
    p(program, 3).delete()
    notices = requirements.sync_requirements(result, user)
    left = [i for i in items(result) if i.criterion == "Face wear"]
    assert len(left) == 1 and left[0].source.startswith(requirements.WITHDRAWN) and len(notices) == 1


def test_tcn_change_is_frozen_when_issued_and_carried_into_a_new_revision(run, program, user):
    tcn = run.current_revision()
    original = change(tcn, "not_applicable", p(program, 3), reason="SiC rotors")
    issue(tcn, user)
    original.reason = "changed afterwards"
    with pytest.raises(ImmutableTcnError):
        original.save()
    with pytest.raises(ImmutableTcnError):
        original.delete()
    revision = create_revision(tcn, user)
    (copied,) = revision.requirement_changes.all()
    assert copied.pk != original.pk and copied.program_requirement == p(program, 3) and copied.reason == "SiC rotors"


def test_tcn_prints_its_requirement_changes(run, program, user):
    tcn = run.current_revision()
    change(tcn, "replace", p(program, 1), criterion="Leakage", basis="leakage_rate", comparison="<=",
           limit=Decimal("20"), unit="ml/h", reason="Run-in test")  # fmt: skip
    lines = html_lines(ChromiumTemplate.load("tcn").render_html(build_tcn_context(tcn)))
    text = " ".join(lines)
    assert "Acceptance Requirement Changes:" in lines
    assert "P1 Leakage: Replaces Program requirement: ≤ 20 ml/h (Test Program: ≤ 10 ml/h). Reason: Run-in test" in text


def test_tcn_without_changes_prints_no_section(run):
    lines = html_lines(ChromiumTemplate.load("tcn").render_html(build_tcn_context(run.current_revision())))
    assert "Acceptance Requirement Changes:" not in lines


# --- pages ------------------------------------------------------------------------------------


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_program_page_saves_title_and_numbered_requirements(logged_in, run, user):
    url = reverse("projects:program", args=[run.project.pk])
    response = logged_in.post(url, {"document_no": "TP-9", "revision": "0", "title": "Endurance", "objective": "Run."})
    assert response.status_code == 302
    add = reverse("projects:program_requirement_add", args=[run.project.pk])
    data = {"criterion": "Leakage", "basis": "leakage_rate", "position": "", "face": "", "comparison": "<=",
            "limit": "12,5", "unit": "", "requirement_text": ""}  # fmt: skip
    assert logged_in.post(add, data).status_code == 302
    assert logged_in.post(add, {**data, "criterion": "Wear", "basis": "wear_rate", "limit": "3E-6"}).status_code == 302
    first, second = TestProgram.objects.get().requirements.all()
    assert (first.ref, first.limit, first.unit) == ("P1", Decimal("12.5"), "ml/h")  # unit of the calculated actual
    assert (second.ref, second.limit, second.unit) == ("P2", Decimal("0.000003"), "in/h")
    bad = logged_in.post(add, {**data, "comparison": "", "limit": ""})
    assert bad.status_code == 200 and "Enter the requirement" in bad.content.decode()
    page = logged_in.get(url).content.decode()
    assert "Endurance" in page and "P2" in page


def test_tcn_page_adds_a_change_only_while_draft(logged_in, run, program, user):
    tcn = run.current_revision()
    url = reverse("tcn:requirement_change_add", args=[tcn.pk])
    data = {"action": "not_applicable", "program_requirement": p(program, 3).pk, "reason": "SiC rotors",
            "criterion": "", "basis": "manual", "position": "", "face": "", "comparison": "", "limit": "",
            "unit": "", "requirement_text": ""}  # fmt: skip
    assert logged_in.post(url, data).status_code == 302
    assert logged_in.post(url, data).status_code == 200  # the same requirement twice: refused
    (saved,) = tcn.requirement_changes.all()
    assert saved.action == "not_applicable" and saved.basis == "manual"
    issue(tcn, user)
    response = logged_in.post(url, {**data, "program_requirement": p(program, 1).pk})
    assert response.status_code == 302 and tcn.requirement_changes.count() == 1


def test_result_page_shows_sources_and_missing_assessments(logged_in, run, program, user):
    services.create_result(run, user)
    page = logged_in.get(reverse("results:result", args=[run.pk])).content.decode()
    assert "Test Program TP-7 rev A P1" in page and "Not assessed" in page
    assert AcceptanceItem.objects.count() == 5  # created by the page while Draft

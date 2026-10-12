"""TestResult and its components (M2B); Pre/Post values come from measurements (M2D)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from testlab.projects.models import SealPosition
from testlab.results import services
from testlab.results.models import ResultComponent, TestResult
from testlab.tcn.services import TcnRuleError, delete_draft

from .helpers import configure, face_length, make_run

pytestmark = pytest.mark.django_db


def labels(result):
    return [c.label for c in services.sorted_components(result)]


def test_result_is_one_to_one_with_the_run_and_starts_as_draft(user):
    run = make_run(user)
    result = services.create_result(run, user)
    assert result.test_run == run and run.result == result
    assert result.status == TestResult.Status.DRAFT and result.created_by == user
    with pytest.raises(services.ResultRuleError, match="already has a Result"):
        services.create_result(run, user)


def test_result_may_exist_while_the_tcn_is_a_draft(user):
    run = make_run(user)
    assert not run.has_issued_revision()
    assert services.create_result(run, user).pk


def test_dual_starts_with_inboard_and_outboard_faces(user):
    run = make_run(user, "dual_pressurized", inboard=("SiC", "SiC (SL)"), outboard=("Carbon", "SiC"))
    result = services.create_result(run, user)
    assert labels(result) == ["IB Stator", "IB Rotor", "OB Stator", "OB Rotor"]
    materials = {c.label: c.material for c in result.components.all()}
    assert materials == {"IB Stator": "SiC", "IB Rotor": "SiC (SL)", "OB Stator": "Carbon", "OB Rotor": "SiC"}


def test_single_starts_with_the_test_seal_and_offers_the_plug_seal(user):
    run = make_run(user, "single", plug_seal=True, plug=("Carbon", "TC"))
    result = services.create_result(run, user)
    assert labels(result) == ["Test Stator", "Test Rotor"]
    addable = [c for p, c in services.addable_components(result) if p == "plug"]
    assert addable == ["sleeve", "stator", "rotor", "backing_ring"]
    rotor = services.add_component(result, "plug", "rotor", user)
    assert rotor.label == "Plug Rotor" and rotor.material == "TC"  # from the TCN Plug Seal
    assert labels(result) == ["Test Stator", "Test Rotor", "Plug Rotor"]


def test_plug_faces_are_not_offered_without_a_plug_seal(user):
    result = services.create_result(make_run(user, "dual_unpressurized", plug_seal=False), user)
    assert all(position != "plug" for position, _ in services.addable_components(result))
    with pytest.raises(services.ResultRuleError, match="cannot be added"):
        services.add_component(result, "plug", "rotor", user)


def test_sleeve_is_a_cartridge_component_without_position(user):
    result = services.create_result(make_run(user), user)
    sleeve = services.add_component(result, "", "sleeve", user)
    # optional dimensional readings; Mahr/ROUNDPAK not applicable unless overridden
    assert sleeve.label == "Sleeve" and sleeve.applicable_kinds() == ["dimensional"]
    assert sleeve.applicability("dimensional") == "optional" and sleeve.applicability("mahr") == "not_applicable"
    with pytest.raises(IntegrityError), transaction.atomic():
        ResultComponent.objects.create(result=result, position="", component="rotor")


def test_component_with_evidence_cannot_be_removed(user):
    result = services.create_result(make_run(user), user)
    face_length(result, user, "IB Rotor", "0.5", "0.4999")
    rotor = next(c for c in result.components.all() if c.label == "IB Rotor")
    with pytest.raises(services.ResultRuleError, match="cannot be removed"):
        services.remove_component(rotor, user)
    stator = next(c for c in result.components.all() if c.label == "IB Stator")
    services.remove_component(stator, user)
    assert "IB Stator" not in labels(result) and ("inboard", "stator") in services.addable_components(result)


def test_result_does_not_follow_later_changes_of_project_defaults_or_tcn(user):
    run = make_run(user, "dual_pressurized", inboard=("SiC", "SiC"), outboard=("SiC", "SiC"))
    result = services.create_result(run, user)
    before = sorted((c.label, c.material) for c in result.components.all())
    # Project defaults change: other arrangement, other faces.
    defaults = run.project.default_setup
    defaults.arrangement, defaults.plug_seal_present = "single", True
    defaults.save()
    # The draft TCN is edited too.
    SealPosition.objects.filter(setup=run.current_revision().setup, role="inboard").update(stationary_face="Carbon")
    result = TestResult.objects.get(pk=result.pk)
    assert sorted((c.label, c.material) for c in result.components.all()) == before


def test_configuration_change_keeps_stored_components_and_offers_the_new_ones(user):
    run = make_run(user, "dual_pressurized")
    result = services.create_result(run, user)
    configure(run, "dual_pressurized", plug_seal=True)
    assert labels(result) == ["IB Stator", "IB Rotor", "OB Stator", "OB Rotor"]
    assert ("plug", "rotor") in services.addable_components(result)


def test_run_with_a_result_is_protected(user):
    run = make_run(user)
    services.create_result(run, user)
    tcn = run.current_revision()
    with pytest.raises(TcnRuleError, match="has a Test Result"):
        delete_draft(tcn, tcn.row_version, user)
    with pytest.raises(ProtectedError):
        run.delete()
    assert TestResult.objects.filter(test_run=run).exists()


def test_result_status_is_draft_only(user):
    result = services.create_result(make_run(user), user)
    with pytest.raises(IntegrityError), transaction.atomic():
        TestResult.objects.filter(pk=result.pk).update(status="issued")

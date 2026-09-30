import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from testlab.projects.arrangements import Arrangement
from testlab.projects.conditions import PROCESS_FIELDS, SEAL_SUPPORT_FIELDS
from testlab.projects.models import RunSetup, SealPosition

from .test_models import make_project

pytestmark = pytest.mark.django_db


def roles(setup):
    return list(setup.positions.values_list("role", flat=True))


def test_project_gets_its_own_default_setup(user):
    first = make_project(user, project_no="2099RSD01TL")
    second = make_project(user, project_no="2099RSD02TL")
    assert first.default_setup_id != second.default_setup_id
    setup = first.default_setup
    assert setup.arrangement == Arrangement.DUAL_PRESSURIZED
    assert setup.plug_seal_present is False
    assert setup.monitored_parameters == []
    assert sorted(roles(setup)) == ["inboard", "outboard"]
    setup.validate_positions()


def test_default_setup_cannot_be_deleted(user):
    project = make_project(user)
    with pytest.raises(ProtectedError):
        project.default_setup.delete()


def test_create_with_plug_seal_positions():
    setup = RunSetup.create_with_positions(arrangement=Arrangement.SINGLE, plug_seal_present=True)
    assert sorted(roles(setup)) == ["plug", "test"]
    assert setup.plug_seal_position().is_plug_seal
    assert [p.role for p in setup.seal_under_test_positions()] == ["test"]


def test_dual_with_plug_seal_keeps_plug_out_of_seal_under_test():
    setup = RunSetup.create_with_positions(arrangement=Arrangement.DUAL_UNPRESSURIZED, plug_seal_present=True)
    assert [p.role for p in setup.seal_under_test_positions()] == ["inboard", "outboard"]
    assert setup.plug_seal_position().role == "plug"


def test_validate_positions_rejects_mismatch():
    setup = RunSetup.create_with_positions(arrangement=Arrangement.SINGLE, plug_seal_present=True)
    setup.positions.create(role="inboard")
    with pytest.raises(ValidationError):
        setup.validate_positions()

    setup = RunSetup.create_with_positions(arrangement=Arrangement.DUAL_PRESSURIZED, plug_seal_present=True)
    setup.positions.filter(role="plug").delete()
    with pytest.raises(ValidationError):
        setup.validate_positions()


def test_role_unique_per_setup():
    setup = RunSetup.create_with_positions(arrangement=Arrangement.SINGLE, plug_seal_present=True)
    with pytest.raises(IntegrityError):
        SealPosition.objects.create(setup=setup, role="test")


def test_invalid_arrangement_rejected():
    setup = RunSetup(arrangement="tandem")
    with pytest.raises(ValidationError) as excinfo:
        setup.full_clean()
    assert "arrangement" in excinfo.value.message_dict


def test_single_seal_requires_plug_seal():
    """V16: a single seal cannot be tested alone."""
    setup = RunSetup(arrangement=Arrangement.SINGLE)
    with pytest.raises(ValidationError) as excinfo:
        setup.full_clean()
    assert excinfo.value.message_dict["plug_seal_present"] == [
        "A single seal cannot be tested alone: the Plug Seal is required."
    ]
    with pytest.raises(IntegrityError), transaction.atomic():
        setup.save()

    setup.plug_seal_present = True
    setup.full_clean()
    setup.save()


@pytest.mark.parametrize("arrangement", [Arrangement.DUAL_PRESSURIZED, Arrangement.DUAL_UNPRESSURIZED])
def test_plug_seal_optional_for_dual(arrangement):
    for plug in (False, True):
        RunSetup(arrangement=arrangement, plug_seal_present=plug).full_clean()


@pytest.mark.parametrize("field", PROCESS_FIELDS)
def test_process_conditions_require_plug_seal(field):
    """V6: the process conditions are established with the Plug Seal."""
    setup = RunSetup(arrangement=Arrangement.DUAL_PRESSURIZED, **{field: "10"})
    with pytest.raises(ValidationError) as excinfo:
        setup.full_clean()
    assert "no Plug Seal is installed" in excinfo.value.message_dict["plug_seal_present"][0]
    with pytest.raises(IntegrityError), transaction.atomic():
        setup.save()

    setup.plug_seal_present = True
    setup.full_clean()
    setup.save()


def test_no_plug_seal_condition_fields():
    """One process-side group: the Plug Seal has no second medium / pressure / temperature / flow."""
    fields = [f.name for f in RunSetup._meta.concrete_fields]
    assert [f for f in fields if f.startswith("plug")] == ["plug_seal_present"]


def test_configuration_display():
    assert RunSetup(arrangement=Arrangement.SINGLE, plug_seal_present=True).configuration_display == "Single"
    dual = RunSetup(arrangement=Arrangement.DUAL_PRESSURIZED)
    assert dual.configuration_display == "Dual Pressurized"
    dual.plug_seal_present = True
    assert dual.configuration_display == "Dual Pressurized + Plug Seal"


def test_single_seal_may_have_seal_support_conditions():
    setup = RunSetup(
        arrangement=Arrangement.SINGLE,
        plug_seal_present=True,
        process_medium="Water",
        seal_support_medium="Process fluid (Plan 23)",
        seal_support_pressure="15",
        seal_support_inlet_temperature="40",
        seal_support_flow="10",
    )
    setup.full_clean()
    setup.save()
    setup.refresh_from_db()
    assert setup.seal_support_medium == "Process fluid (Plan 23)"
    assert setup.seal_support_pressure == "15"
    assert setup.process_medium == "Water"  # the Process Conditions stay a separate circuit


def test_each_circuit_stores_its_own_values():
    values = {}
    for n, field in enumerate(PROCESS_FIELDS + SEAL_SUPPORT_FIELDS):
        values[field] = f"{field}-{n}" if field.endswith("medium") else str(n)
    setup = RunSetup(arrangement=Arrangement.DUAL_PRESSURIZED, plug_seal_present=True, speed="2980", **values)
    setup.full_clean()
    setup.save()
    setup.refresh_from_db()
    for field, value in values.items():
        assert getattr(setup, field) == value


def test_monitored_parameters_must_be_applicable():
    single = {"arrangement": Arrangement.SINGLE, "plug_seal_present": True}
    setup = RunSetup(**single, monitored_parameters=["inboard_leakage"])
    with pytest.raises(ValidationError) as excinfo:
        setup.full_clean()
    assert "inboard_leakage" in str(excinfo.value)

    for code in ["plug_leakage", "process_pressure"]:
        setup = RunSetup(arrangement=Arrangement.DUAL_PRESSURIZED, monitored_parameters=[code])
        with pytest.raises(ValidationError):
            setup.full_clean()

    # The former Plug Seal circuit codes are process codes now.
    for code in ["plug_pressure", "plug_inlet_temp", "plug_flow", "nonsense"]:
        setup = RunSetup(**single, monitored_parameters=[code])
        with pytest.raises(ValidationError):
            setup.full_clean()


def test_process_and_plug_seal_parameters_accepted_with_plug_seal():
    setup = RunSetup(
        arrangement=Arrangement.DUAL_UNPRESSURIZED,
        plug_seal_present=True,
        monitored_parameters=["plug_leakage", "process_flow", "process_inlet_temp", "plug_face_temp", "process_pressure"],
    )
    setup.full_clean()
    assert setup.monitored_parameters == [
        "process_pressure", "process_inlet_temp", "process_flow", "plug_face_temp", "plug_leakage",
    ]  # fmt: skip


def test_monitored_parameters_stored_in_canonical_order_without_duplicates():
    setup = RunSetup(
        arrangement=Arrangement.DUAL_PRESSURIZED,
        monitored_parameters=["outboard_leakage", "seal_support_pressure", "inboard_face_temp", "outboard_leakage"],
    )
    setup.full_clean()
    setup.save()
    setup.refresh_from_db()
    assert setup.monitored_parameters == ["seal_support_pressure", "inboard_face_temp", "outboard_leakage"]


def test_normalisation_trims_strips_units_and_reports():
    setup = RunSetup(
        arrangement=Arrangement.DUAL_PRESSURIZED,
        plug_seal_present=True,
        test_unit="  TU5 ",
        duration="min 75 hours",
        speed="2980 rpm",
        process_pressure="70 barg",
        process_inlet_temperature="TBC",
        seal_support_inlet_temperature="40°C",
        run_description="Test run:\n    • step one   \n",
    )
    setup.full_clean()
    assert setup.test_unit == "TU5"
    assert (setup.duration, setup.speed, setup.process_pressure) == ("min 75", "2980", "70")
    assert setup.process_inlet_temperature == "TBC"
    assert setup.seal_support_inlet_temperature == "40"
    assert setup.run_description == "Test run:\n    • step one"
    assert len(setup.normalization_notices) == 4
    assert any("Seal-support inlet temperature" in n and "“40°C”" in n for n in setup.normalization_notices)


def test_save_normalises_without_full_clean():
    setup = RunSetup.objects.create(plug_seal_present=True, process_pressure=" 70 barg ")
    setup.refresh_from_db()
    assert setup.process_pressure == "70"


def test_max_lengths_enforced():
    setup = RunSetup(test_unit="X" * 21)
    with pytest.raises(ValidationError) as excinfo:
        setup.full_clean()
    assert "test_unit" in excinfo.value.message_dict


def test_seal_position_text_trimmed():
    setup = RunSetup.create_with_positions(arrangement=Arrangement.SINGLE, plug_seal_present=True)
    position = setup.positions.get(role="test")
    assert position.is_empty()
    position.seal_type_size = "  UHTW 4.750 "
    position.save()
    position.refresh_from_db()
    assert position.seal_type_size == "UHTW 4.750"
    assert not position.is_empty()


def test_clone_copies_stored_values_and_positions():
    setup = RunSetup.create_with_positions(
        arrangement=Arrangement.SINGLE,
        plug_seal_present=True,
        speed="2980",
        process_medium="Water",
        monitored_parameters=["process_pressure", "test_leakage"],
    )
    setup.positions.filter(role="test").update(seal_type_size="UHTW 4.750")
    stale = RunSetup.objects.get(pk=setup.pk)
    RunSetup.objects.filter(pk=setup.pk).update(speed="1500")
    stale.test_unit = "unsaved"

    clone = stale.clone()
    assert clone.pk != setup.pk
    assert (clone.arrangement, clone.plug_seal_present, clone.speed, clone.test_unit) == (
        Arrangement.SINGLE, True, "1500", "",
    )  # fmt: skip
    assert clone.process_medium == "Water"
    assert clone.monitored_parameters == ["process_pressure", "test_leakage"]
    positions = {p.role: p for p in clone.positions.all()}
    assert sorted(positions) == ["plug", "test"]
    assert positions["test"].seal_type_size == "UHTW 4.750"
    assert not set(clone.positions.values_list("pk", flat=True)) & set(setup.positions.values_list("pk", flat=True))

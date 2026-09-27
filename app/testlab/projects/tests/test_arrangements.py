import pytest

from testlab.projects.arrangements import (
    ALL_MONITORED_PARAMETERS,
    Arrangement,
    SealRole,
    applicable_monitored_parameters,
    applicable_roles,
    canonical_order,
    seal_support_label,
    seal_under_test_roles,
)

S, DP, DU = Arrangement.SINGLE, Arrangement.DUAL_PRESSURIZED, Arrangement.DUAL_UNPRESSURIZED


def test_exactly_three_arrangements_and_plug_is_not_one():
    assert Arrangement.values == ["single", "dual_pressurized", "dual_unpressurized"]
    assert not any("plug" in value for value in Arrangement.values)


@pytest.mark.parametrize("arrangement", [S, DP, DU])
def test_plug_seal_is_never_part_of_the_seal_under_test(arrangement):
    assert SealRole.PLUG not in seal_under_test_roles(arrangement)


@pytest.mark.parametrize(
    "arrangement, plug, expected",
    [
        (S, False, ["test"]),
        (S, True, ["plug", "test"]),
        (DP, False, ["inboard", "outboard"]),
        (DP, True, ["plug", "inboard", "outboard"]),
        (DU, False, ["inboard", "outboard"]),
        (DU, True, ["plug", "inboard", "outboard"]),
    ],
)
def test_applicable_roles_in_column_order(arrangement, plug, expected):
    assert applicable_roles(arrangement, plug) == expected


def test_seal_support_labels_single_has_flush_circuit():
    assert seal_support_label(S) == "Flush"
    assert seal_support_label(DP) == "Barrier"
    assert seal_support_label(DU) == "Buffer"


def test_monitored_parameters_for_single_include_seal_support():
    codes = applicable_monitored_parameters(S, False)
    assert codes == [
        "process_pressure", "process_inlet_temp", "process_outlet_temp", "process_flow",
        "seal_support_pressure", "seal_support_inlet_temp", "seal_support_outlet_temp", "seal_support_flow",
        "test_face_temp", "test_leakage",
    ]  # fmt: skip


def test_monitored_parameters_dual_with_plug_in_canonical_order():
    assert applicable_monitored_parameters(DP, True)[8:] == [
        "plug_pressure", "plug_inlet_temp", "plug_flow",
        "plug_face_temp", "plug_leakage",
        "inboard_face_temp", "inboard_leakage",
        "outboard_face_temp", "outboard_leakage",
    ]  # fmt: skip


@pytest.mark.parametrize("arrangement", [S, DP, DU])
def test_plug_seal_circuit_parameters_only_with_plug_seal(arrangement):
    circuit = ["plug_pressure", "plug_inlet_temp", "plug_flow"]
    assert not set(circuit) & set(applicable_monitored_parameters(arrangement, False))
    assert set(circuit) <= set(applicable_monitored_parameters(arrangement, True))


def test_plug_seal_circuit_parameters_follow_run_setup_field_names():
    # plug_inlet_temp ↔ RunSetup.plug_inlet_temperature, as process_inlet_temp ↔ process_inlet_temperature
    from testlab.projects.models import RunSetup

    for code in ["plug_pressure", "plug_inlet_temp", "plug_flow"]:
        assert code in ALL_MONITORED_PARAMETERS
        RunSetup._meta.get_field(code.replace("_temp", "_temperature"))


def test_all_codes_unique():
    assert len(ALL_MONITORED_PARAMETERS) == len(set(ALL_MONITORED_PARAMETERS))


def test_canonical_order():
    assert canonical_order(["outboard_leakage", "process_flow", "inboard_face_temp"]) == [
        "process_flow",
        "inboard_face_temp",
        "outboard_leakage",
    ]

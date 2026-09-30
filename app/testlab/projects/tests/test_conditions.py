import pytest

from testlab.projects.conditions import (
    COMMON_FIELDS,
    PROCESS_FIELDS,
    SEAL_SUPPORT_FIELDS,
    field_unit,
    strip_repeated_unit,
)


def test_circuits_have_separate_fields_and_speed_is_common_only():
    groups = [COMMON_FIELDS, PROCESS_FIELDS, SEAL_SUPPORT_FIELDS]
    all_fields = [f for group in groups for f in group]
    assert len(all_fields) == len(set(all_fields))
    assert "speed" in COMMON_FIELDS
    assert not [f for f in all_fields if "speed" in f and f != "speed"]
    # One process-side group: the Plug Seal has no conditions of its own.
    assert not [f for f in all_fields if f.startswith("plug")]
    for group in (PROCESS_FIELDS, SEAL_SUPPORT_FIELDS):
        assert [field_unit(f) for f in group] == [None, "barg", "°C", "l/min"]


@pytest.mark.parametrize(
    "field, typed, stored",
    [
        ("process_pressure", "70 barg", "70"),
        ("process_pressure", "70 bar g", "70"),
        ("seal_support_pressure", "70BARG", "70"),
        ("process_inlet_temperature", "40°C", "40"),
        ("process_inlet_temperature", "40 C", "40"),
        ("seal_support_inlet_temperature", "60 - 40 °C", "60 - 40"),
        ("speed", "2980 rpm", "2980"),
        ("duration", "min 75 hours", "min 75"),
        ("duration", "50 h", "50"),
        ("duration", "100hrs", "100"),
        ("process_flow", "TBD l/min", "TBD"),
        ("seal_support_pressure", "5 barg", "5"),
        # kept as typed
        ("process_flow", "TBD", "TBD"),
        ("process_inlet_temperature", "TBC", "TBC"),
        ("seal_support_inlet_temperature", "60 - 40", "60 - 40"),
        ("process_flow", "Approx. 35-50", "Approx. 35-50"),
        ("speed", "rpm", "rpm"),
        ("process_medium", "Water 40 C", "Water 40 C"),
        ("test_unit", "TU 5 h", "TU 5 h"),
    ],
)
def test_strip_repeated_unit(field, typed, stored):
    assert strip_repeated_unit(field, typed) == stored

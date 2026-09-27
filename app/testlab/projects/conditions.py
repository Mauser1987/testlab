"""Run condition fields, grouped by physically separate circuit (M1 spec §1.2).

No circuit shares a field with another, and none is assumed to share fluid,
pressure, temperature or flow with another. Values are free text as typed
("min 75", "TBD", "60 - 40"); the unit is printed by TestLab.
"""

import re

# Common to the whole Test Run. Speed applies to the whole shaft, so the
# Plug Seal has no speed of its own.
COMMON_FIELDS = ["test_unit", "duration", "speed"]
PROCESS_FIELDS = ["process_medium", "process_pressure", "process_inlet_temperature", "process_flow"]
# Mechanical-seal support circuit: barrier, buffer or flush (any arrangement).
SEAL_SUPPORT_FIELDS = [
    "seal_support_medium",
    "seal_support_pressure",
    "seal_support_inlet_temperature",
    "seal_support_flow",
]
# Plug Seal circuit; only used when a Plug Seal is present.
PLUG_FIELDS = ["plug_medium", "plug_pressure", "plug_inlet_temperature", "plug_flow"]

# Printed unit per field and the typed spellings of it that are removed (V8).
_UNIT_SPELLINGS = {
    "hours": r"hours?|hrs?|h",
    "rpm": r"rpm",
    "barg": r"bar\s*g|bar\s*\(g\)",
    "°C": r"°\s*C|º\s*C|deg\s*C|C",
    "l/min": r"l\s*/\s*min|lpm",
}


def field_unit(field):
    if field == "duration":
        return "hours"
    if field == "speed":
        return "rpm"
    for suffix, unit in (("_pressure", "barg"), ("_inlet_temperature", "°C"), ("_flow", "l/min")):
        if field.endswith(suffix):
            return unit
    return None


def strip_repeated_unit(field, value):
    """Remove a trailing unit that repeats the printed unit ("70 barg" → "70").

    The unit must follow a digit or a space, so "TBC" or "TBD" are kept.
    """
    unit = field_unit(field)
    if unit is None:
        return value
    match = re.fullmatch(rf"(.*?[\d\s])\s*(?:{_UNIT_SPELLINGS[unit]})\s*", value, re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return value

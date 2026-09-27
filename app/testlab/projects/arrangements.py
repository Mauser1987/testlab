"""Seal arrangement and Plug Seal rules (M1 spec §5).

Two separate things are configured on a RunSetup:

* the **seal arrangement under test** — single (Test seal) or dual
  pressurized / unpressurized (Inboard + Outboard seal); and
* optionally a **Plug Seal** — process-side simulation/test equipment on the
  same shaft with its own operating circuit. It is *not* a stage of a dual
  seal and is therefore never an arrangement value. It is stored as a
  SealPosition with role ``plug`` only because it has the same descriptive
  fields.
"""

from django.db import models


class Arrangement(models.TextChoices):
    SINGLE = "single", "Single"
    DUAL_PRESSURIZED = "dual_pressurized", "Dual Pressurized"
    DUAL_UNPRESSURIZED = "dual_unpressurized", "Dual Unpressurized"


class SealRole(models.TextChoices):
    # Order is the column order on screen and in documents.
    PLUG = "plug", "Plug Seal"
    TEST = "test", "Test Seal"
    INBOARD = "inboard", "Inboard Seal"
    OUTBOARD = "outboard", "Outboard Seal"


# Roles of the mechanical seal arrangement under test; the Plug Seal is never one of them.
SEAL_UNDER_TEST_ROLES = {
    Arrangement.SINGLE: [SealRole.TEST],
    Arrangement.DUAL_PRESSURIZED: [SealRole.INBOARD, SealRole.OUTBOARD],
    Arrangement.DUAL_UNPRESSURIZED: [SealRole.INBOARD, SealRole.OUTBOARD],
}

ROLE_SHORT_LABELS = {
    SealRole.PLUG: "Plug",
    SealRole.TEST: "Test",
    SealRole.INBOARD: "IB",
    SealRole.OUTBOARD: "OB",
}

# Label of the mechanical-seal support circuit. A single seal may have a
# flush/support circuit (e.g. Plan 23); single does not mean "no circuit".
SEAL_SUPPORT_LABELS = {
    Arrangement.SINGLE: "Flush",
    Arrangement.DUAL_PRESSURIZED: "Barrier",
    Arrangement.DUAL_UNPRESSURIZED: "Buffer",
}


def seal_under_test_roles(arrangement):
    return list(SEAL_UNDER_TEST_ROLES[Arrangement(arrangement)])


def applicable_roles(arrangement, plug_seal_present):
    """Seal positions present for a configuration, in column order (§5.1)."""
    roles = seal_under_test_roles(arrangement)
    if plug_seal_present:
        roles.insert(0, SealRole.PLUG)
    return roles


def seal_support_label(arrangement):
    return SEAL_SUPPORT_LABELS[Arrangement(arrangement)]


# Monitored parameters (§5.4). Canonical order: circuits (process, seal
# support, Plug Seal), then per seal position; within each, Excel log order.
PROCESS_PARAMETERS = ["process_pressure", "process_inlet_temp", "process_outlet_temp", "process_flow"]
SEAL_SUPPORT_PARAMETERS = [
    "seal_support_pressure",
    "seal_support_inlet_temp",
    "seal_support_outlet_temp",
    "seal_support_flow",
]

# Plug Seal circuit, normally logged continuously by the DCS/LabVIEW system.
# Codes only: they identify the parameter for the log sheet and later results.
PLUG_SEAL_CIRCUIT_PARAMETERS = ["plug_pressure", "plug_inlet_temp", "plug_flow"]


def role_parameters(role):
    return [f"{role}_face_temp", f"{role}_leakage"]


ALL_MONITORED_PARAMETERS = (
    PROCESS_PARAMETERS
    + SEAL_SUPPORT_PARAMETERS
    + PLUG_SEAL_CIRCUIT_PARAMETERS
    + [code for role in SealRole for code in role_parameters(role)]
)


def applicable_monitored_parameters(arrangement, plug_seal_present):
    """Codes that may be ticked for a configuration, in canonical order."""
    roles = applicable_roles(arrangement, plug_seal_present)
    plug_codes = PLUG_SEAL_CIRCUIT_PARAMETERS if plug_seal_present else []
    role_codes = [code for role in SealRole if role in roles for code in role_parameters(role)]
    return PROCESS_PARAMETERS + SEAL_SUPPORT_PARAMETERS + plug_codes + role_codes


_PARAMETER_LABELS = {
    "pressure": "Pressure [barg]",
    "inlet_temp": "Inlet temp. [°C]",
    "outlet_temp": "Outlet temp. [°C]",
    "flow": "Flow [l/min]",
    "face_temp": "Face temp. [°C]",
    "leakage": "Leakage [ml]",
}


def parameter_label(code):
    """Checkbox label of a code within its group, e.g. "plug_inlet_temp" → "Inlet temp. [°C]"."""
    for suffix, label in _PARAMETER_LABELS.items():
        if code.endswith("_" + suffix):
            return label
    raise ValueError(code)


def canonical_order(codes):
    return sorted(codes, key=ALL_MONITORED_PARAMETERS.index)

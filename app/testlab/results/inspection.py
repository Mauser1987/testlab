"""Physical components of a seal and what is measured on them (M2B).

Measurements and pictures belong to a physical identity, not to columns
such as ``ib_rotor_waviness``. An identity is a seal position plus a
component:

* position — the SealRole of the run configuration (Test Seal for single,
  Inboard / Outboard for dual, Plug Seal when installed), or none for a part
  of the whole cartridge (the shared sleeve of a dual seal);
* component — Rotor (rotating seal face), Stator (stationary seal face) or
  Sleeve. The legacy Test Run Report uses exactly these words ("IB Rotor",
  "Inner Seal Stator (14)", "Sleeve (1)"); the TCN calls the faces
  "rotating seal face" and "stationary seal face".

The components offered follow the run's configuration (offered_components);
a new Result starts with the faces of the seal under test
(default_components). Plug Seal faces and the sleeve are added when they
are inspected: nothing is forced onto a component that is not inspected.

Measurement quantities keep the legacy report's terms and units. Δ = Post −
Pre is calculated for every quantity, with no interpretation. Only face
length has a wear meaning: material removed from the face shortens it, so
wear = Pre − Post (positive = worn). Waviness, taper and roughness can
change either way; their Δ is not called wear.
"""

from dataclasses import dataclass

from django.db import models

from testlab.projects.arrangements import ROLE_SHORT_LABELS, SealRole, seal_under_test_roles


class Component(models.TextChoices):
    # Order is the display order within a position (legacy report: stator, then rotor).
    SLEEVE = "sleeve", "Sleeve"
    STATOR = "stator", "Stator"
    ROTOR = "rotor", "Rotor"


COMPONENT_DESCRIPTIONS = {
    Component.STATOR: "stationary seal face",
    Component.ROTOR: "rotating seal face",
    Component.SLEEVE: "shaft sleeve",
}

FACES = (Component.STATOR, Component.ROTOR)

# Position order on screen: the seal under test, then the Plug Seal (test equipment).
POSITION_ORDER = ["", SealRole.TEST, SealRole.INBOARD, SealRole.OUTBOARD, SealRole.PLUG]


def identity_label(position, component):
    """e.g. "IB Rotor", "OB Stator", "Plug Rotor", "Test Rotor", "Sleeve"."""
    name = Component(component).label
    return f"{ROLE_SHORT_LABELS[SealRole(position)]} {name}" if position else name


def sort_key(position, component):
    return POSITION_ORDER.index(position), list(Component.values).index(component)


def offered_components(arrangement, plug_seal_present):
    """(position, component) pairs that can be inspected in this configuration, in display order."""
    offered = [("", Component.SLEEVE)]
    offered += [(role, face) for role in seal_under_test_roles(arrangement) for face in FACES]
    if plug_seal_present:
        offered += [(SealRole.PLUG, face) for face in FACES]
    return offered


def default_components(arrangement):
    """Components a new Result starts with: the faces of the seal under test."""
    return [(role, face) for role in seal_under_test_roles(arrangement) for face in FACES]


@dataclass(frozen=True)
class Quantity:
    code: str
    label: str
    unit: str
    components: tuple  # Component values it applies to
    wear: bool = False  # a decrease is material removed: wear = Pre − Post
    description: str = ""


QUANTITIES = [
    Quantity("face_waviness", "Face waviness", "µm", FACES),
    Quantity("face_taper", "Face taper", "µm", FACES),
    Quantity(
        "face_length", "Face length", "in", FACES, wear=True,
        description="Wear = Pre − Post (material removed from the face).",
    ),
    Quantity("roughness_ra", "Roughness Ra", "µm", FACES),
]
_BY_CODE = {q.code: q for q in QUANTITIES}


def quantity(code):
    return _BY_CODE[code]


def quantities_for(component):
    return [q for q in QUANTITIES if component in q.components]


def delta(pre, post):
    """Post − Pre, or None when either is missing."""
    return None if pre is None or post is None else post - pre


def wear(code, pre, post):
    """Material removed (Pre − Post) for a wear quantity; None otherwise or when a value is missing."""
    if not quantity(code).wear or pre is None or post is None:
        return None
    return pre - post

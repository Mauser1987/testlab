"""Physical components of a seal and what is measured on them (M2B).

Measurements and pictures belong to a physical identity, not to columns
such as ``ib_rotor_waviness``. An identity is a seal position plus a
component:

* position — the SealRole of the run configuration (Test Seal for single,
  Inboard / Outboard for dual, Plug Seal when installed), or none for a part
  of the whole cartridge (the shared sleeve of a dual seal);
* component — Rotor (rotating seal face), Stator (stationary seal face),
  Sleeve or Backing ring. The legacy Test Run Report uses exactly these
  words ("IB Rotor", "Inner Seal Stator (14)", "Sleeve (1)"); the TCN calls
  the faces "rotating seal face" and "stationary seal face".

The components offered follow the run's configuration (offered_components);
a new Result starts with the faces of the seal under test
(default_components). Plug Seal faces, sleeves and backing rings are
optional components, added only when they are inspected: nothing is forced
onto a component that is not inspected, and a component not added is
neither missing nor reported.

What is measured on a component (M2D): measurement kinds (Mahr profile,
ROUNDPAK flatness, dimensional), each required, optional or not applicable
— per Result for the seal faces, overridable per component. On a sleeve or
backing ring dimensional readings are optional and Mahr/ROUNDPAK not
applicable unless the engineer sets otherwise. Δ = Post − Pre is calculated
for every quantity, with no interpretation. Only the face length of a seal
face has a wear meaning: material removed from the face shortens it, so
wear = Pre − Post (positive = material removed). Flatness, taper and
roughness can change either way; their Δ is not called wear, and neither is
a dimension of a sleeve or backing ring.
"""

from dataclasses import dataclass

from django.db import models

from testlab.projects.arrangements import ROLE_SHORT_LABELS, SealRole, seal_under_test_roles


class Component(models.TextChoices):
    # Order is the display order within a position (legacy report: stator, then rotor).
    SLEEVE = "sleeve", "Sleeve"
    STATOR = "stator", "Stator"
    ROTOR = "rotor", "Rotor"
    BACKING_RING = "backing_ring", "Backing ring"


COMPONENT_DESCRIPTIONS = {
    Component.STATOR: "stationary seal face",
    Component.ROTOR: "rotating seal face",
    Component.SLEEVE: "shaft sleeve",
    Component.BACKING_RING: "backing ring",
}

FACES = (Component.STATOR, Component.ROTOR)
OPTIONAL_PARTS = (Component.SLEEVE, Component.BACKING_RING)

# Position order on screen: the seal under test, then the Plug Seal (test equipment).
POSITION_ORDER = ["", SealRole.TEST, SealRole.INBOARD, SealRole.OUTBOARD, SealRole.PLUG]


def identity_label(position, component):
    """e.g. "IB Rotor", "OB Stator", "Plug Rotor", "Test Rotor", "Sleeve"."""
    name = Component(component).label
    return f"{ROLE_SHORT_LABELS[SealRole(position)]} {name}" if position else name


def sort_key(position, component):
    return POSITION_ORDER.index(position), list(Component.values).index(component)


def offered_components(arrangement, plug_seal_present):
    """(position, component) pairs that can be inspected in this configuration, in display order.

    Sleeves and backing rings belong to the seal they are part of; a sleeve
    may also be the shared sleeve of the cartridge (no position).
    """
    roles = seal_under_test_roles(arrangement) + ([SealRole.PLUG] if plug_seal_present else [])
    offered = [("", Component.SLEEVE)]
    offered += [(role, part) for role in roles for part in (*FACES, *OPTIONAL_PARTS)]
    return sorted(offered, key=lambda pair: sort_key(*pair))


def default_components(arrangement):
    """Components a new Result starts with: the faces of the seal under test."""
    return [(role, face) for role in seal_under_test_roles(arrangement) for face in FACES]


class MeasurementKind(models.TextChoices):
    """How a seal-face quantity is measured (M2D): one instrument file type, or a dimensional reading."""

    DIMENSIONAL = "dimensional", "Face length (dimensional)"
    MAHR = "mahr", "Mahr profile / roughness"
    ROUNDPAK = "roundpak", "ROUNDPAK flatness"


KIND_SOURCES = {MeasurementKind.DIMENSIONAL: "Manual", MeasurementKind.MAHR: "Mahr", MeasurementKind.ROUNDPAK: "ROUNDPAK"}


class Stage(models.TextChoices):
    PRE = "pre", "Pre-test"
    POST = "post", "Post-test"


class Applicability(models.TextChoices):
    """Required: missing until measured. Optional: reported when measured, never missing.
    Not applicable: nothing expected, nothing shown (not the same as missing)."""

    REQUIRED = "required", "Required"
    OPTIONAL = "optional", "Optional"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


def kind_label(component, kind):
    """A kind as named for a component: "Face length (dimensional)" on a seal face, "Dimensional" otherwise."""
    if kind == MeasurementKind.DIMENSIONAL and component not in FACES:
        return "Dimensional"
    return MeasurementKind(kind).label


@dataclass(frozen=True)
class Quantity:
    code: str
    label: str
    unit: str
    kind: str  # MeasurementKind it comes from
    wear: bool = False  # a decrease is material removed: wear = Pre − Post
    description: str = ""


# Pre/Post summary, in the legacy report's column order. Each quantity comes from one kind of
# measurement only; profile P–V (Mahr) is not a summary quantity. The taper is shown from both
# instruments (M2F-a): Mahr first, the more accurate one; ROUNDPAK from its two radial traces.
QUANTITIES = [
    Quantity(
        "face_flatness", "Face flatness (circular trace)", "µm", MeasurementKind.ROUNDPAK,
        description="ROUNDPAK instrument flatness FLTt of one circular trace, as exported; not a map of the whole face.",
    ),
    Quantity(
        "face_taper", "Face taper (Mahr)", "µm", MeasurementKind.MAHR,
        description="Signed opposing-scan taper of the Mahr profiles: negative ID high (Convex), positive OD high "
                    "(Concave), Flat within the flat limit (± 0.25 HLB). The more accurate taper.",
    ),
    Quantity(
        "face_taper_roundpak", "Face taper (ROUNDPAK)", "µm", MeasurementKind.ROUNDPAK,
        description="Signed taper of the two ROUNDPAK radial traces 180° apart (mean slope × radial width), same "
                    "sign and flat limit as the Mahr taper.",
    ),
    Quantity(
        "face_length", "Face length", "in", MeasurementKind.DIMENSIONAL, wear=True,
        description="Wear = Pre − Post (material removed from the face).",
    ),
    Quantity(
        "roughness_ra", "Roughness Ra", "µm", MeasurementKind.MAHR,
        description="Mean of the instrument's Ra of the left and right scans (same face, nearby spots).",
    ),
]  # fmt: skip
# A dimension of a sleeve or backing ring: Δ only, no wear meaning.
DIMENSION = Quantity(
    "dimension", "Dimension", "in", MeasurementKind.DIMENSIONAL,
    description="As measured (feature named with the reading); Δ = Post − Pre, not interpreted as wear.",
)  # fmt: skip
_BY_CODE = {q.code: q for q in [*QUANTITIES, DIMENSION]}


def quantity(code):
    return _BY_CODE[code]


def quantities_for(component):
    """Summary quantities of a component: face length on a seal face, a plain dimension on other parts."""
    if component in FACES:
        return QUANTITIES
    return [DIMENSION if q.code == "face_length" else q for q in QUANTITIES]


def quantities_of(kind):
    return [q for q in QUANTITIES if q.kind == kind]


def delta(pre, post):
    """Post − Pre, or None when either is missing."""
    return None if pre is None or post is None else post - pre


def wear(code, pre, post):
    """Material removed (Pre − Post) for a wear quantity; None otherwise or when a value is missing."""
    if not quantity(code).wear or pre is None or post is None:
        return None
    return pre - post


def effective_applicability(component, override, result_default, kind=None):
    """A component's own choice; else the Result's default for a seal face; on a sleeve or backing
    ring dimensional readings are optional and everything else not applicable."""
    if override:
        return override
    if component in FACES:
        return result_default
    if component in OPTIONAL_PARTS and kind == MeasurementKind.DIMENSIONAL:
        return Applicability.OPTIONAL
    return Applicability.NOT_APPLICABLE

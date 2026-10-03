"""Component identities and measurement catalogue (M2B)."""

from decimal import Decimal

from testlab.projects.arrangements import Arrangement, SealRole
from testlab.results import inspection
from testlab.results.inspection import Component


def labels(pairs):
    return [inspection.identity_label(p, c) for p, c in pairs]


def test_single_offers_the_test_seal_faces_and_the_plug_seal():
    offered = inspection.offered_components(Arrangement.SINGLE, True)
    assert labels(offered) == ["Sleeve", "Test Stator", "Test Rotor", "Plug Stator", "Plug Rotor"]
    assert labels(inspection.default_components(Arrangement.SINGLE)) == ["Test Stator", "Test Rotor"]


def test_dual_offers_inboard_and_outboard_faces_without_plug():
    offered = inspection.offered_components(Arrangement.DUAL_PRESSURIZED, False)
    assert labels(offered) == ["Sleeve", "IB Stator", "IB Rotor", "OB Stator", "OB Rotor"]
    assert not any(position == SealRole.PLUG for position, _ in offered)


def test_dual_with_plug_seal_offers_plug_faces_but_does_not_start_with_them():
    offered = inspection.offered_components(Arrangement.DUAL_UNPRESSURIZED, True)
    assert (SealRole.PLUG, Component.ROTOR) in offered and (SealRole.PLUG, Component.STATOR) in offered
    defaults = inspection.default_components(Arrangement.DUAL_UNPRESSURIZED)
    assert labels(defaults) == ["IB Stator", "IB Rotor", "OB Stator", "OB Rotor"]


def test_measurements_apply_to_faces_only():
    face_codes = [q.code for q in inspection.quantities_for(Component.ROTOR)]
    assert face_codes == ["face_waviness", "face_taper", "face_length", "roughness_ra"]
    assert inspection.quantities_for(Component.SLEEVE) == []
    assert inspection.quantity("face_length").unit == "in"  # legacy report unit, wear in in/h
    assert inspection.quantity("face_waviness").unit == "µm"


def test_delta_is_post_minus_pre_and_needs_both_values():
    assert inspection.delta(Decimal("0.323"), Decimal("0.389")) == Decimal("0.066")
    assert inspection.delta(Decimal("0.586"), Decimal("0.249")) == Decimal("-0.337")
    assert inspection.delta(None, Decimal("1")) is None and inspection.delta(Decimal("1"), None) is None


def test_wear_only_for_face_length_and_with_the_wear_sign():
    # Legacy report, OB Stator face length 1.25037 → 1.25025 in: 0.00012 in removed.
    assert inspection.wear("face_length", Decimal("1.25037"), Decimal("1.25025")) == Decimal("0.00012")
    assert inspection.wear("face_waviness", Decimal("0.7"), Decimal("0.6")) is None  # a change, not wear
    assert inspection.wear("face_length", Decimal("1.25"), None) is None

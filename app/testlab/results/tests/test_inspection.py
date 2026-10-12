"""Component identities and measurement catalogue (M2B)."""

from decimal import Decimal

from testlab.projects.arrangements import Arrangement, SealRole
from testlab.results import inspection
from testlab.results.inspection import Applicability, Component


def labels(pairs):
    return [inspection.identity_label(p, c) for p, c in pairs]


def test_single_offers_the_test_seal_faces_and_the_plug_seal():
    offered = inspection.offered_components(Arrangement.SINGLE, True)
    assert labels(offered) == [
        "Sleeve", "Test Sleeve", "Test Stator", "Test Rotor", "Test Backing ring",
        "Plug Sleeve", "Plug Stator", "Plug Rotor", "Plug Backing ring",
    ]  # fmt: skip
    assert labels(inspection.default_components(Arrangement.SINGLE)) == ["Test Stator", "Test Rotor"]


def test_dual_offers_inboard_and_outboard_faces_without_plug():
    offered = inspection.offered_components(Arrangement.DUAL_PRESSURIZED, False)
    assert labels(offered) == [
        "Sleeve", "IB Sleeve", "IB Stator", "IB Rotor", "IB Backing ring",
        "OB Sleeve", "OB Stator", "OB Rotor", "OB Backing ring",
    ]  # fmt: skip
    assert not any(position == SealRole.PLUG for position, _ in offered)


def test_dual_with_plug_seal_offers_plug_faces_but_does_not_start_with_them():
    offered = inspection.offered_components(Arrangement.DUAL_UNPRESSURIZED, True)
    assert (SealRole.PLUG, Component.ROTOR) in offered and (SealRole.PLUG, Component.STATOR) in offered
    defaults = inspection.default_components(Arrangement.DUAL_UNPRESSURIZED)
    assert labels(defaults) == ["IB Stator", "IB Rotor", "OB Stator", "OB Rotor"]


def test_summary_quantities_each_come_from_one_kind_of_measurement():
    assert [(q.code, q.kind) for q in inspection.QUANTITIES] == [
        ("face_flatness", "roundpak"), ("face_taper", "mahr"), ("face_taper_roundpak", "roundpak"),
        ("face_length", "dimensional"), ("roughness_ra", "mahr"),
    ]  # both tapers (M2F-a): Mahr first, the more accurate
    assert inspection.quantity("face_length").unit == "in"  # legacy report unit, wear in in/h
    assert inspection.quantity("face_flatness").label == "Face flatness (circular trace)"  # not "waviness"
    assert [q.wear for q in inspection.QUANTITIES] == [False, False, False, True, False]


def test_applicability_override_else_result_default_for_faces_only():
    required, na = Applicability.REQUIRED, Applicability.NOT_APPLICABLE
    assert inspection.effective_applicability(Component.ROTOR, "", required) == required
    assert inspection.effective_applicability(Component.ROTOR, na, required) == na
    assert inspection.effective_applicability(Component.STATOR, required, na) == required
    assert inspection.effective_applicability(Component.SLEEVE, "", required) == na
    assert inspection.effective_applicability(Component.SLEEVE, required, na) == required


def test_delta_is_post_minus_pre_and_needs_both_values():
    assert inspection.delta(Decimal("0.323"), Decimal("0.389")) == Decimal("0.066")
    assert inspection.delta(Decimal("0.586"), Decimal("0.249")) == Decimal("-0.337")
    assert inspection.delta(None, Decimal("1")) is None and inspection.delta(Decimal("1"), None) is None


def test_wear_only_for_face_length_and_with_the_wear_sign():
    # Legacy report, OB Stator face length 1.25037 → 1.25025 in: 0.00012 in removed.
    assert inspection.wear("face_length", Decimal("1.25037"), Decimal("1.25025")) == Decimal("0.00012")
    assert inspection.wear("face_flatness", Decimal("0.7"), Decimal("0.6")) is None  # a change, not wear
    assert inspection.wear("face_length", Decimal("1.25"), None) is None

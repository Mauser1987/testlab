"""Optional inspection components: sleeves and backing rings (M2E)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from testlab.results import measurement_summary, seal_faces, services
from testlab.results.models import ResultComponent

from .helpers import make_run

pytestmark = pytest.mark.django_db

S = measurement_summary


@pytest.fixture
def result(user):
    return services.create_result(make_run(user, "dual_pressurized"), user)


def statuses(component):
    return {(kind, stage): S.slot_status(component, kind, stage) for kind in ("dimensional", "mahr", "roundpak")
            for stage in ("pre", "post")}  # fmt: skip


def test_not_mandatory_by_default_and_offered_per_seal(result):
    labels = [c.label for c in result.components.all()]
    assert not any("Sleeve" in label or "Backing ring" in label for label in labels)  # not added: nothing missing
    offered = [ResultComponent(position=p, component=c).label for p, c in services.addable_components(result)]
    assert {"Sleeve", "IB Sleeve", "OB Sleeve", "IB Backing ring", "OB Backing ring"} <= set(offered)


def test_states_not_applicable_optional_required_missing_and_measured(result, user):
    ring = services.add_component(result, "inboard", "backing_ring", user)
    found = statuses(ring)
    assert found[("dimensional", "pre")] == S.OPTIONAL  # optional, not measured: never missing
    assert found[("mahr", "pre")] == S.NOT_APPLICABLE and found[("roundpak", "post")] == S.NOT_APPLICABLE
    ring.dimensional_applicability = "required"
    ring.save()
    assert S.slot_status(ring, "dimensional", "pre") == S.MISSING
    seal_faces.create_dimensional(ring, "pre", Decimal("3.502"), user, unit="mm", feature="Thickness")
    assert S.slot_status(ring, "dimensional", "pre") == S.COMPLETED
    assert S.slot_status(ring, "dimensional", "post") == S.MISSING


def test_mahr_and_roundpak_are_never_required_automatically(result, user):
    sleeve = services.add_component(result, "", "sleeve", user)
    assert sleeve.applicability("mahr") == "not_applicable" and sleeve.applicability("roundpak") == "not_applicable"
    with pytest.raises(seal_faces.MeasurementError, match="not applicable"):
        seal_faces.create_mahr(sleeve, "pre", None, None, user)
    sleeve.mahr_applicability = "optional"  # the engineer may still measure it
    sleeve.save()
    assert sleeve.applicable_kinds() == ["dimensional", "mahr"]
    assert S.slot_status(sleeve, "mahr", "pre") == S.OPTIONAL


def test_a_dimension_names_its_feature_and_has_no_wear_meaning(result, user):
    sleeve = services.add_component(result, "outboard", "sleeve", user)
    with pytest.raises(seal_faces.MeasurementError, match="Name the measured feature"):
        seal_faces.create_dimensional(sleeve, "pre", Decimal("2.5"), user)
    seal_faces.create_dimensional(sleeve, "pre", Decimal("2.5000"), user, feature="OD at the seal seat")
    seal_faces.create_dimensional(sleeve, "post", Decimal("2.4990"), user, feature="OD at the seal seat")
    (group,) = S.summary([sleeve])
    (row,) = group.rows
    assert row.label == "Dimension: OD at the seal seat" and row.quantity.code == "dimension"
    assert row.delta == Decimal("-0.0010") and row.wear is None and not row.quantity.wear


def test_summary_has_no_empty_rows_for_optional_parts(result, user):
    ring = services.add_component(result, "inboard", "backing_ring", user)
    assert S.summary([ring]) == []  # added, nothing measured: no rows, nothing missing
    assert S.completeness([ring]).slots == [] and S.completeness([ring]).complete


def test_pictures_and_observations_of_an_optional_part(client, result, user):
    ring = services.add_component(result, "outboard", "backing_ring", user)
    client.force_login(user)
    url = reverse("results:component_observations", args=[ring.pk])
    response = client.post(url, {f"c{ring.pk}-observations": "Fretting at the pin."})
    assert response.status_code == 302 and response["Location"].endswith(f"#component-{ring.pk}")
    ring.refresh_from_db()
    assert ring.observations == "Fretting at the pin."
    page = client.get(reverse("results:result", args=[result.test_run.pk])).content.decode()
    assert "OB Backing ring" in page and "optional component" in page and "Fretting at the pin." in page
    assert "Optional, not added" in page and "IB Backing ring" in page


def test_add_measurement_page_for_a_sleeve_asks_feature_and_unit(client, result, user):
    sleeve = services.add_component(result, "inboard", "sleeve", user)
    client.force_login(user)
    url = reverse("results:measurement_add", args=[sleeve.pk])
    page = client.get(url, {"kind": "dimensional", "stage": "pre"}).content.decode()
    assert "Measured feature" in page and "Face length [in]" not in page and "Dimensional" in page
    response = client.post(url, {"kind": "dimensional", "stage": "pre", "feature": "Length", "value": "40,02",
                                 "unit": "mm"})  # fmt: skip
    assert response.status_code == 302
    reading = sleeve.face_measurements.get().dimensional
    assert (reading.feature, reading.value, reading.unit, reading.quantity) == ("Length", Decimal("40.02"), "mm", "dimension")


def test_existing_cartridge_sleeve_records_stay_valid(result, user):
    sleeve = ResultComponent.objects.create(result=result, position="", component="sleeve")  # as stored before M2E
    assert sleeve.label == "Sleeve" and sleeve.applicability("dimensional") == "optional"
    seal_faces.create_dimensional(sleeve, "pre", Decimal("2"), user, feature="OD")
    assert S.slot_status(sleeve, "dimensional", "pre") == S.COMPLETED

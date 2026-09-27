"""S5 project defaults form and arrangement switching (M1 spec §5.3, §6; AT-9 defaults part)."""

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from testlab.projects.arrangements import SealRole
from testlab.projects.models import RunSetup, SealPosition

from .test_models import make_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user, project_no="2099RSD01TL")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def url(project):
    return reverse("projects:defaults", args=[project.pk])


def post_data(setup, action="save", **overrides):
    """The data the browser posts for `setup` unchanged (incl. hidden inputs)."""
    data = {"action": action, "arrangement": setup.arrangement, "monitored_parameters": list(setup.monitored_parameters)}
    if setup.plug_seal_present:
        data["plug_seal_present"] = "on"
    for field in RunSetup.TEXT_FIELDS:
        data[field] = getattr(setup, field)
    positions = {p.role: p for p in setup.positions.all()}
    for role in SealRole:
        for field in SealPosition.DESCRIPTIVE_FIELDS:
            data[f"{role}-{field}"] = getattr(positions[role], field) if role in positions else ""
    for key, value in overrides.items():
        if key == "plug_seal_present" and not value:
            data.pop("plug_seal_present", None)
        elif key == "plug_seal_present":
            data["plug_seal_present"] = "on"
        else:
            data[key] = value
    return data


def roles(setup):
    return sorted(setup.positions.values_list("role", flat=True))


def fill_dual(setup):
    """TCN001-like dual pressurized defaults (2026RSD03TL)."""
    RunSetup.objects.filter(pk=setup.pk).update(
        seal_support_medium="ISO VG 32",
        seal_support_pressure="70",
        seal_support_inlet_temperature="60",
        monitored_parameters=["seal_support_pressure", "inboard_face_temp", "inboard_leakage", "outboard_leakage"],
    )
    setup.positions.filter(role="inboard").update(seal_type_size="UHTW 4.750", springs="668838NL (10)")
    setup.positions.filter(role="outboard").update(seal_type_size="UHTW 4.750", rotating_face="C100603035 (SL WAVY)")
    setup.refresh_from_db()


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def test_page_shows_seal_under_test_and_plug_seal_separately(logged_in, project):
    content = logged_in.get(url(project)).content.decode()
    assert "Seal under test" in content
    assert "Plug Seal (process-side test equipment)" in content
    assert "Inboard Seal" in content and "Outboard Seal" in content
    assert "Barrier" in content
    # Plug Seal not installed: its fields are only kept as hidden inputs
    assert 'type="hidden" name="plug-seal_type_size"' in content
    assert 'type="hidden" name="plug_medium"' in content


def test_save_defaults(logged_in, project):
    setup = project.default_setup
    data = post_data(
        setup,
        run_description="Dynamic test:\n    • 75 h at 2980 rpm",
        test_unit="TU5",
        duration="min 75 hours",
        speed="2980",
        process_medium="Water",
        process_pressure="70 barg",
        seal_support_medium="ISO VG 32",
        **{"inboard-seal_type_size": "UHTW 4.750", "outboard-springs": "668838NL (10)"},
        monitored_parameters=["outboard_leakage", "seal_support_pressure"],
    )
    response = logged_in.post(url(project), data)
    assert response.status_code == 302
    setup.refresh_from_db()
    assert setup.run_description == "Dynamic test:\n    • 75 h at 2980 rpm"
    assert (setup.duration, setup.process_pressure) == ("min 75", "70")
    assert setup.monitored_parameters == ["seal_support_pressure", "outboard_leakage"]
    assert setup.positions.get(role="inboard").seal_type_size == "UHTW 4.750"
    assert setup.positions.get(role="outboard").springs == "668838NL (10)"
    texts = messages_of(response)
    assert any("“70 barg” saved as “70”" in t for t in texts)
    assert "Project defaults of 2099RSD01TL saved." in texts
    project.refresh_from_db()
    assert project.updated_by_id is not None


def test_update_rerenders_without_saving(logged_in, project):
    setup = project.default_setup
    response = logged_in.post(url(project), post_data(setup, action="update", arrangement="single"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Test Seal" in content
    assert "Flush" in content and "(optional, e.g. Plan 23)" in content
    setup.refresh_from_db()
    assert setup.arrangement == "dual_pressurized"
    assert roles(setup) == ["inboard", "outboard"]


def test_dual_to_single_with_seal_data_requires_confirmation(logged_in, project):
    setup = project.default_setup
    fill_dual(setup)
    data = post_data(setup, arrangement="single", **{"test-seal_type_size": "UMPW 2.625"})

    response = logged_in.post(url(project), data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Saving this configuration will discard:" in content
    assert "Inboard Seal: UHTW 4.750, 668838NL (10)" in content
    assert "Outboard Seal: UHTW 4.750, C100603035 (SL WAVY)" in content
    assert "Tick “Discard this data” to save" in content
    setup.refresh_from_db()
    assert setup.arrangement == "dual_pressurized"

    response = logged_in.post(url(project), {**data, "confirm_discard": "1"})
    assert response.status_code == 302
    setup.refresh_from_db()
    assert setup.arrangement == "single"
    assert roles(setup) == ["test"]
    assert setup.positions.get().seal_type_size == "UMPW 2.625"
    # Seal-support values are kept; single seals may have a flush circuit.
    assert (setup.seal_support_medium, setup.seal_support_pressure, setup.seal_support_inlet_temperature) == (
        "ISO VG 32",
        "70",
        "60",
    )
    assert setup.monitored_parameters == ["seal_support_pressure"]


def test_single_to_dual_with_plug_seal(logged_in, project):
    setup = project.default_setup
    logged_in.post(url(project), post_data(setup, arrangement="single"))
    setup.refresh_from_db()
    assert roles(setup) == ["test"]

    response = logged_in.post(url(project), post_data(setup, arrangement="dual_pressurized", plug_seal_present=True))
    assert response.status_code == 302
    setup.refresh_from_db()
    assert roles(setup) == ["inboard", "outboard", "plug"]
    assert [p.role for p in setup.seal_under_test_positions()] == ["inboard", "outboard"]
    assert setup.plug_seal_position() is not None


def test_dual_pressurized_to_unpressurized_keeps_everything(logged_in, project):
    setup = project.default_setup
    fill_dual(setup)
    response = logged_in.post(url(project), post_data(setup, arrangement="dual_unpressurized"))
    assert response.status_code == 302
    setup.refresh_from_db()
    assert setup.arrangement == "dual_unpressurized"
    assert setup.positions.get(role="inboard").seal_type_size == "UHTW 4.750"
    assert setup.seal_support_pressure == "70"
    assert "Buffer" in logged_in.get(url(project)).content.decode()


def test_plug_seal_conditions_saved_and_shown(logged_in, project):
    setup = project.default_setup
    data = post_data(
        setup,
        plug_seal_present=True,
        plug_medium="Water",
        plug_pressure="5 barg",
        plug_inlet_temperature="40",
        plug_flow="10",
        process_medium="Crude oil",
        process_pressure="70",
        **{"plug-seal_type_size": "DHTW 4.750"},
        monitored_parameters=["plug_pressure", "plug_flow", "plug_leakage"],
    )
    response = logged_in.post(url(project), data)
    assert response.status_code == 302
    setup.refresh_from_db()
    assert (setup.plug_medium, setup.plug_pressure, setup.plug_inlet_temperature, setup.plug_flow) == (
        "Water",
        "5",
        "40",
        "10",
    )
    assert (setup.process_medium, setup.process_pressure) == ("Crude oil", "70")
    assert setup.monitored_parameters == ["plug_pressure", "plug_flow", "plug_leakage"]
    assert setup.plug_seal_position().seal_type_size == "DHTW 4.750"
    content = logged_in.get(url(project)).content.decode()
    assert "Plug Seal circuit" in content
    assert 'name="plug_medium" value="Water"' in content


def test_removing_plug_seal_with_conditions_requires_confirmation(logged_in, project):
    setup = project.default_setup
    logged_in.post(
        url(project),
        post_data(setup, plug_seal_present=True, plug_medium="Water", monitored_parameters=["plug_pressure"]),
    )
    setup.refresh_from_db()
    assert setup.plug_seal_present

    data = post_data(setup, plug_seal_present=False)
    response = logged_in.post(url(project), data)
    assert response.status_code == 200
    assert "Plug Seal conditions: Water" in response.content.decode()
    setup.refresh_from_db()
    assert setup.plug_medium == "Water"

    response = logged_in.post(url(project), {**data, "confirm_discard": "1"})
    assert response.status_code == 302
    setup.refresh_from_db()
    assert not setup.plug_seal_present
    assert setup.plug_medium == ""
    assert setup.monitored_parameters == []
    assert roles(setup) == ["inboard", "outboard"]


def test_removing_empty_positions_needs_no_confirmation(logged_in, project):
    setup = project.default_setup
    response = logged_in.post(url(project), post_data(setup, arrangement="single"))
    assert response.status_code == 302


def test_update_keeps_values_that_no_longer_apply(logged_in, project):
    setup = project.default_setup
    fill_dual(setup)
    data = post_data(setup, action="update", arrangement="single")
    content = logged_in.post(url(project), data).content.decode()
    assert 'type="hidden" name="inboard-seal_type_size" value="UHTW 4.750"' in content
    assert '<input type="hidden" name="monitored_parameters" value="inboard_leakage">' in content
    assert "Saving this configuration will discard:" in content  # early warning

    # switching back before saving restores everything
    back = post_data(setup, action="save")
    back.update({k: v for k, v in data.items() if k.startswith(("inboard-", "outboard-"))})
    assert logged_in.post(url(project), back).status_code == 302
    setup.refresh_from_db()
    assert setup.positions.get(role="inboard").springs == "668838NL (10)"


def test_invalid_values_are_reported_and_nothing_saved(logged_in, project):
    setup = project.default_setup
    response = logged_in.post(url(project), post_data(setup, test_unit="X" * 21, arrangement="single"))
    assert response.status_code == 200
    assert "Ensure this value has at most 20 characters" in response.content.decode()
    setup.refresh_from_db()
    assert setup.arrangement == "dual_pressurized"


def test_non_applicable_parameter_codes_are_dropped(logged_in, project):
    setup = project.default_setup
    response = logged_in.post(
        url(project), post_data(setup, arrangement="single", monitored_parameters=["inboard_leakage", "test_leakage"])
    )
    assert response.status_code == 302
    setup.refresh_from_db()
    assert setup.monitored_parameters == ["test_leakage"]


def test_defaults_are_per_project(logged_in, user, project):
    other = make_project(user, project_no="2099RSD02TL")
    logged_in.post(url(project), post_data(project.default_setup, speed="2980"))
    other.default_setup.refresh_from_db()
    assert other.default_setup.speed == ""

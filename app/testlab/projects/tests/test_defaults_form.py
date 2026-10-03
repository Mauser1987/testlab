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
    # Plug Seal not installed: its fields and the process conditions are only kept as hidden inputs
    assert 'type="hidden" name="plug-seal_type_size"' in content
    assert 'type="hidden" name="process_medium"' in content
    assert "No process conditions: they are established with the Plug Seal, which is not installed." in content
    assert "(optional for a dual seal)" in content


def test_process_conditions_shown_only_with_plug_seal(logged_in, project):
    setup = project.default_setup
    content = logged_in.post(url(project), post_data(setup, action="update", plug_seal_present=True)).content.decode()
    assert '<input type="text" name="process_medium"' in content
    assert "(established with the Plug Seal)" in content
    assert '<legend>Process</legend>' in content and 'value="process_pressure"' in content
    assert "Plug Seal circuit" not in content and "plug_medium" not in content

    content = logged_in.get(url(project)).content.decode()
    assert '<legend>Process</legend>' not in content and 'value="process_pressure"' not in content


def test_save_defaults(logged_in, project):
    setup = project.default_setup
    data = post_data(
        setup,
        run_description="Dynamic test:\n    • 75 h at 2980 rpm",
        test_unit="TU5",
        duration="min 75 hours",
        speed="2980",
        plug_seal_present=True,
        process_medium="Water",
        process_pressure="70 barg",
        seal_support_medium="ISO VG 32",
        **{"inboard-seal_type_size": "UHTW 4.750", "outboard-springs": "668838NL (10)", "plug-seal_type_size": "DHTW"},
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
    # Single: the Plug Seal is installed automatically and cannot be removed.
    assert "required: a single seal is tested with the Plug Seal" in content
    assert '<input type="hidden" name="plug_seal_present" value="on">' in content
    assert '<input type="text" name="plug-seal_type_size"' in content
    assert '<input type="text" name="process_medium"' in content
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
    assert setup.plug_seal_present  # installed with single, without asking
    assert roles(setup) == ["plug", "test"]
    assert setup.positions.get(role="test").seal_type_size == "UMPW 2.625"
    # Seal-support values are kept; single seals may have a flush circuit.
    assert (setup.seal_support_medium, setup.seal_support_pressure, setup.seal_support_inlet_temperature) == (
        "ISO VG 32",
        "70",
        "60",
    )
    assert setup.monitored_parameters == ["seal_support_pressure"]


def test_single_cannot_be_saved_without_plug_seal(logged_in, project):
    """V16: whatever is posted, single is saved with the Plug Seal."""
    setup = project.default_setup
    data = post_data(setup, arrangement="single", plug_seal_present=False)
    assert "plug_seal_present" not in data
    assert logged_in.post(url(project), data).status_code == 302
    setup.refresh_from_db()
    assert (setup.arrangement, setup.plug_seal_present) == ("single", True)
    assert roles(setup) == ["plug", "test"]


def test_single_to_dual_keeps_plug_seal_and_process_conditions(logged_in, project):
    setup = project.default_setup
    logged_in.post(url(project), post_data(setup, arrangement="single", process_medium="Water"))
    setup.refresh_from_db()
    assert roles(setup) == ["plug", "test"]

    response = logged_in.post(url(project), post_data(setup, arrangement="dual_pressurized"))
    assert response.status_code == 302
    setup.refresh_from_db()
    assert setup.plug_seal_present and setup.process_medium == "Water"
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


def test_process_conditions_with_plug_seal_saved_and_shown(logged_in, project):
    """Dual + Plug Seal: the Plug Seal's operating conditions are the process conditions; barrier stays separate."""
    setup = project.default_setup
    data = post_data(
        setup,
        plug_seal_present=True,
        process_medium="Water",
        process_pressure="5 barg",
        process_inlet_temperature="40",
        process_flow="10",
        seal_support_medium="ISO VG 32",
        seal_support_pressure="70",
        **{"plug-seal_type_size": "DHTW 4.750"},
        monitored_parameters=["process_pressure", "process_flow", "plug_leakage", "seal_support_pressure"],
    )
    response = logged_in.post(url(project), data)
    assert response.status_code == 302
    setup.refresh_from_db()
    assert (setup.process_medium, setup.process_pressure, setup.process_inlet_temperature, setup.process_flow) == (
        "Water",
        "5",
        "40",
        "10",
    )
    assert (setup.seal_support_medium, setup.seal_support_pressure) == ("ISO VG 32", "70")
    assert setup.monitored_parameters == ["process_pressure", "process_flow", "seal_support_pressure", "plug_leakage"]
    assert setup.plug_seal_position().seal_type_size == "DHTW 4.750"
    content = logged_in.get(url(project)).content.decode()
    assert 'name="process_medium" value="Water"' in content
    assert '<input type="checkbox" name="monitored_parameters" value="plug_leakage" checked>' in content


def test_removing_plug_seal_with_process_conditions_requires_confirmation(logged_in, project):
    setup = project.default_setup
    logged_in.post(
        url(project),
        post_data(setup, plug_seal_present=True, process_medium="Water", monitored_parameters=["process_pressure"]),
    )
    setup.refresh_from_db()
    assert setup.plug_seal_present and setup.process_medium == "Water"

    data = post_data(setup, plug_seal_present=False)
    response = logged_in.post(url(project), data)
    assert response.status_code == 200
    assert "Process conditions: Water" in response.content.decode()
    setup.refresh_from_db()
    assert setup.process_medium == "Water"

    response = logged_in.post(url(project), {**data, "confirm_discard": "1"})
    assert response.status_code == 302
    setup.refresh_from_db()
    assert not setup.plug_seal_present
    assert setup.process_medium == ""
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


@pytest.mark.parametrize(("arrangement", "panel"), [("dual_pressurized", "Barrier"), ("dual_unpressurized", "Buffer")])
def test_diff_seal_pressure_checkbox_for_dual_seals(logged_in, project, arrangement, panel):
    setup = project.default_setup
    logged_in.post(url(project), post_data(setup, arrangement=arrangement, monitored_parameters=["seal_support_diff_pressure"]))
    setup.refresh_from_db()
    assert setup.monitored_parameters == ["seal_support_diff_pressure"]
    content = logged_in.get(url(project)).content.decode()
    legend = content.index(f"<legend>{panel}</legend>", content.index("Parameters to log"))
    box = content.index('value="seal_support_diff_pressure" checked')
    assert legend < box < content.index("</fieldset>", legend)
    assert "Diff. seal pressure [bar]" in content


def test_diff_seal_pressure_dropped_for_single(logged_in, project):
    setup = project.default_setup
    setup.monitored_parameters = ["seal_support_diff_pressure"]
    setup.save()
    logged_in.post(url(project), post_data(setup, arrangement="single", monitored_parameters=["seal_support_diff_pressure"]))
    setup.refresh_from_db()
    assert setup.arrangement == "single" and setup.monitored_parameters == []

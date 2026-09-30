"""tcn/diff.py: differences against the source TCN (M1 spec §6 S7, §7)."""

import pytest

from testlab.projects.arrangements import Arrangement
from testlab.projects.templatetags.setup_form import was
from testlab.tcn.diff import Change, source_changes
from testlab.tcn.services import create_tcn

from .factories import issue, make_project, new_revision

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(user):
    project = make_project(user)
    defaults = project.default_setup
    defaults.speed = "2980"
    defaults.seal_support_pressure = "70"
    defaults.run_description = "Line 1\nLine 2"
    defaults.monitored_parameters = ["seal_support_pressure", "inboard_leakage"]
    defaults.save()
    defaults.positions.filter(role="inboard").update(seal_type_size="UHTW 4.750", stationary_face="C100603033")
    return create_tcn(project, 1, user)


@pytest.fixture
def copy(source, user):
    return create_tcn(source.test_run.project, 2, user, source=source)


def keys(tcn):
    return [change.key for change in source_changes(tcn)]


def test_no_comparison_without_source_tcn(source):
    assert source_changes(source) is None


def test_fresh_copy_has_no_differences(copy):
    assert source_changes(copy) == []


def test_header_and_setup_changes_in_form_order(copy):
    copy.prepared_by = "MT"
    copy.save()
    setup = copy.setup
    setup.speed = "1500"
    setup.run_description = "Line 1\nLine 2 changed"
    setup.save()
    setup.positions.filter(role="inboard").update(stationary_face="C0618722SL")

    changes = source_changes(copy)
    assert [c.key for c in changes] == ["prepared_by", "run_description", "speed", "inboard-stationary_face"]
    assert changes[0] == Change("prepared_by", "Prepared by", "MG", "MT")
    assert changes[2] == Change("speed", "Speed", "2980", "1500")
    assert changes[3] == Change(
        "inboard-stationary_face", "Inboard Seal: Stationary seal face", "C100603033", "C0618722SL"
    )


def test_seal_support_label_follows_arrangement(copy):
    setup = copy.setup
    setup.seal_support_pressure = "15"
    setup.save()
    (change,) = source_changes(copy)
    assert change.label == "Barrier pressure"

    setup.arrangement = Arrangement.SINGLE
    setup.plug_seal_present = True
    setup.save()
    labels = {c.key: c.label for c in source_changes(copy)}
    assert labels["seal_support_pressure"] == "Flush pressure"
    assert labels["arrangement"] == "Seal arrangement"


def test_arrangement_switch_reports_removed_positions_with_data(copy):
    setup = copy.setup
    setup.arrangement = Arrangement.SINGLE
    setup.plug_seal_present = True
    setup.monitored_parameters = ["seal_support_pressure"]
    setup.save()
    setup.positions.all().delete()
    setup.positions.create(role="plug")
    setup.positions.create(role="test")

    changes = {c.key: c for c in source_changes(copy)}
    assert changes["arrangement"].old == "Dual Pressurized" and changes["arrangement"].new == "Single"
    assert changes["inboard-seal_type_size"].new == "" and changes["inboard-stationary_face"].old == "C100603033"
    # Empty positions on either side are not differences.
    assert "outboard-seal_type_size" not in changes and "test-seal_type_size" not in changes
    assert changes["plug_seal_present"].new == "Installed"
    assert changes["monitored_parameters"] == Change(
        "monitored_parameters", "Parameters to log", "Flush Pressure [barg], IB Leakage [ml]", "Flush Pressure [barg]"
    )


def test_plug_seal_added(copy):
    setup = copy.setup
    setup.plug_seal_present = True
    setup.process_medium = "Water"
    setup.monitored_parameters = ["process_pressure", "plug_leakage"]
    setup.save()
    setup.positions.create(role="plug", seal_type_size="DHTW 4.750")
    changes = {c.key: c for c in source_changes(copy)}
    assert changes["plug_seal_present"].old == "Not installed" and changes["plug_seal_present"].new == "Installed"
    assert changes["process_medium"] == Change("process_medium", "Process medium", "", "Water")
    assert changes["plug-seal_type_size"].new == "DHTW 4.750"
    assert changes["monitored_parameters"].new == "Process Pressure [barg], Plug Leakage [ml]"
    assert not [key for key in changes if key.startswith("plug_") and key != "plug_seal_present"]


def test_new_revision_compares_with_issued_revision(source, user):
    issue(source, user)
    rev_1 = new_revision(source, user)
    rev_1.setup.speed = "3600"
    rev_1.setup.save()
    assert keys(rev_1) == ["speed"]


def test_marker_filter():
    changes = {
        "speed": Change("speed", "Speed", "2980", "1500"),
        "run_description": Change("run_description", "Test Run description", "a\nb", "c"),
    }
    assert was("speed", changes) == '<span class="was">changed — was: 2980</span>'
    assert "<details" in was("run_description", changes) and "<pre>a\nb</pre>" in was("run_description", changes)
    assert was("duration", changes) == ""
    assert was("speed", None) == ""
    empty = {"speed": Change("speed", "Speed", "", "1500")}
    assert "was: (empty)" in was("speed", empty)
    escaped = {"speed": Change("speed", "Speed", "<b>", "1")}
    assert "&lt;b&gt;" in was("speed", escaped)

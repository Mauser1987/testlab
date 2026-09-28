"""build_tcn_context and rendering rules (M1 spec §9.2, §9.3)."""

import datetime
import io

import pytest
from docx import Document
from docx.oxml.ns import qn

from testlab.documents.render import render_docx, template_path
from testlab.documents.tcn_context import (
    build_tcn_context,
    format_date,
    run_description_lines,
    tcn_file_name,
    with_unit,
)
from testlab.projects.arrangements import Arrangement
from testlab.tcn.services import create_tcn
from testlab.tcn.tests.factories import issue, make_project, new_revision

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user, project_no="2099RSD01TL", description="TEST UHTW 4.750")


def tcn_with(project, user, arrangement=Arrangement.DUAL_PRESSURIZED, plug=False, **fields):
    setup = project.default_setup
    setup.arrangement = arrangement
    setup.plug_seal_present = plug
    for field, value in fields.items():
        setattr(setup, field, value)
    setup.save()
    setup.positions.all().delete()
    for role in setup.applicable_roles():
        setup.positions.create(role=role, seal_type_size=f"{role} type")
    return create_tcn(project, project.test_runs.count() + 1, user)


def column(heading, medium, pressure, inlet_temperature, flow):
    return {
        "heading": heading,
        "medium": medium,
        "pressure": pressure,
        "inlet_temperature": inlet_temperature,
        "flow": flow,
    }


def headings(columns):
    return [column["heading"] for column in columns]


def test_units_only_with_a_value():
    assert with_unit("duration", "min 75") == "min 75 hours"
    assert with_unit("speed", "2980") == "2980 rpm"
    assert with_unit("process_pressure", "70") == "70 barg"
    assert with_unit("seal_support_inlet_temperature", "60 - 40") == "60 - 40°C"
    assert with_unit("plug_flow", "TBD") == "TBD l/min"
    assert with_unit("speed", "") == ""
    assert with_unit("process_flow", "", empty="NA") == "NA"


def test_date_and_file_names(project, user):
    assert format_date(datetime.date(2026, 6, 16)) == "16-Jun-2026"
    tcn = issue(tcn_with(project, user), user)
    assert tcn_file_name(tcn) == "2099RSD01TL-TCN001.docx"
    assert tcn_file_name(new_revision(tcn, user), draft=True) == "2099RSD01TL-TCN001-rev1-DRAFT.docx"


def test_run_description_levels():
    text = "• Step\n - one space\n    - four spaces\n\t- tab\n     - five spaces\n\n• Next"
    assert run_description_lines(text) == [
        {"text": "• Step", "level": 0},
        {"text": "- one space", "level": 1},
        {"text": "- four spaces", "level": 1},
        {"text": "- tab", "level": 1},
        {"text": "- five spaces", "level": 2},
        {"text": "", "level": 0},
        {"text": "• Next", "level": 0},
    ]


def test_dual_pressurized_columns(project, user):
    context = build_tcn_context(tcn_with(project, user, seal_support_medium="Water", seal_support_pressure="70"))
    assert headings(context["seal_columns"]) == ["Inboard Seal", "Outboard Seal"]
    process, barrier = context["condition_columns"]
    assert process == column("Process Fluid", "NA", "NA", "NA", "NA")
    # Seal support: empty values print blank, not NA (E8).
    assert barrier == column("Barrier Fluid", "Water", "70 barg", "", "")


def test_dual_unpressurized_shows_empty_buffer_column(project, user):
    context = build_tcn_context(tcn_with(project, user, Arrangement.DUAL_UNPRESSURIZED))
    assert headings(context["condition_columns"]) == ["Process Fluid", "Buffer Fluid"]


def test_single_seal_flush_column_only_when_filled(project, user):
    context = build_tcn_context(tcn_with(project, user, Arrangement.SINGLE))
    assert headings(context["seal_columns"]) == ["Test Seal"]
    assert headings(context["condition_columns"]) == ["Process Fluid"]

    tcn = tcn_with(project, user, Arrangement.SINGLE, seal_support_medium="Process fluid (Plan 23)")
    context = build_tcn_context(tcn)
    assert headings(context["condition_columns"]) == ["Process Fluid", "Flush Fluid"]
    assert context["condition_columns"][1]["pressure"] == ""


def test_plug_seal_columns_first_and_na_when_empty(project, user):
    context = build_tcn_context(tcn_with(project, user, Arrangement.SINGLE, plug=True, plug_pressure="35"))
    assert headings(context["seal_columns"]) == ["Plug Seal", "Test Seal"]
    assert context["seal_columns"][0]["seal_type_size"] == "plug type"
    plug = context["condition_columns"][-1]
    assert plug == column("Plug Seal Fluid", "NA", "35 barg", "NA", "NA")


def test_header_values_and_draft_flag(project, user):
    tcn = tcn_with(project, user, test_unit="B", reference_drawing="F00321662")
    context = build_tcn_context(tcn)
    assert (context["project_no"], context["tcn_no"], context["is_draft"]) == ("2099RSD01TL", "001", True)
    assert (context["project_description"], context["prepared_by"]) == ("TEST UHTW 4.750", "MG")
    assert (context["test_unit"], context["reference_drawing"]) == ("B", "F00321662")
    assert context["created_date"] == format_date(tcn.created_date)
    issue(tcn, user)
    context = build_tcn_context(new_revision(tcn, user))
    assert context["tcn_no"] == "001 rev 1"


def test_context_comes_from_tcn_snapshot_not_project_defaults(project, user):
    """Project defaults → TCN snapshot → document: later default edits never reach the document."""
    tcn = tcn_with(project, user, speed="2980", process_medium="Water")
    before = build_tcn_context(tcn)

    defaults = project.default_setup
    defaults.speed = "1500"
    defaults.process_medium = "Oil"
    defaults.arrangement = Arrangement.SINGLE
    defaults.save()
    defaults.positions.update(seal_type_size="changed")
    project.description = "RENAMED IN PROJECT"
    project.save()

    after = build_tcn_context(type(tcn).objects.get(pk=tcn.pk))
    assert after == before
    assert after["speed"] == "2980 rpm" and after["project_description"] == "TEST UHTW 4.750"


def grid_widths(docx_bytes, table_index):
    table = Document(io.BytesIO(docx_bytes)).tables[table_index]
    return [int(col.get(qn("w:w"))) for col in table._tbl.tblGrid.findall(qn("w:gridCol"))]


def test_loop_columns_keep_the_template_widths(project, user):
    template_seal_grid = grid_widths(template_path("tcn.docx").read_bytes(), 1)
    for arrangement, plug, count in [
        (Arrangement.SINGLE, False, 1),
        (Arrangement.DUAL_PRESSURIZED, False, 2),
        (Arrangement.DUAL_PRESSURIZED, True, 3),
    ]:
        tcn = tcn_with(project, user, arrangement, plug)
        rendered = render_docx(template_path("tcn.docx"), build_tcn_context(tcn))
        assert grid_widths(rendered, 1) == template_seal_grid[: 1 + count]

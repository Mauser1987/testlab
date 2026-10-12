"""TCN document regressions (M1 spec §9, §11): AT-2, AT-3, AT-16 (document part).

Run against the text of the rendered TCN document template (the Chromium
template bundle); the PDF itself is checked in test_chromium_render.py.
"""

from pathlib import Path

import pytest
from django.conf import settings

from testlab.documents.render import ChromiumTemplate, template_path
from testlab.documents.tcn_context import build_tcn_context, format_date
from testlab.projects.arrangements import Arrangement
from testlab.tcn.services import create_tcn
from testlab.tcn.tests import data_2026rsd03tl
from testlab.tcn.tests.factories import make_project
from testlab.tcn.tests.test_at5_copy_chain import load_defaults

from . import data_2025rsd02tl
from .html_text import html_lines, normalized

pytestmark = pytest.mark.django_db

FIXTURES = Path(settings.APP_DIR) / "tests" / "fixtures"
DRAFT_MARK = "DRAFT — not issued"


@pytest.fixture
def tcn001(db, user):
    """2026RSD03TL TCN001 (AT-2 data)."""
    row = data_2026rsd03tl.ROWS[1]
    project = make_project(user, project_no="2026RSD03TL", description=row["ProjName"])
    load_defaults(project, 1)
    return create_tcn(project, 1, user)


@pytest.fixture
def render():
    """Lines of the rendered TCN document template: render(tcn, **context_overrides)."""

    def render(tcn, **overrides):
        context = build_tcn_context(tcn)
        context.update(overrides)
        # Chromium fills in the page number and count; the template holds only "Page  of ".
        lines = html_lines(ChromiumTemplate.load("tcn").render_html(context))
        return [line.replace(" Page of ", " ") for line in lines]

    return render


def test_template_is_configurable(settings, tmp_path):
    settings.TESTLAB_TEMPLATE_DIR = tmp_path
    assert template_path("tcn") == tmp_path / "tcn"


def test_at2_tcn001_regression(user, render):
    """AT-2: 2026RSD03TL TCN001 through the services equals TCN001.pdf (except the date format)."""
    row = data_2026rsd03tl.ROWS[1]
    project = make_project(user, project_no="2026RSD03TL", description=row["ProjName"])
    load_defaults(project, 1)
    tcn = create_tcn(project, 1, user)  # prepared by MG (Maria Geerts)

    expected = (FIXTURES / "tcn001_expected.txt").read_text(encoding="utf-8").splitlines()
    # Documented difference (§15 Q-D): date format 16-Jun-2026 instead of 6/16/2026.
    created = f"Created: {format_date(tcn.created_date)}"
    expected = [created if line.startswith("Created:") else line for line in expected]

    issued_look = render(tcn, is_draft=False)
    assert normalized(issued_look) == normalized(expected)
    for key in [
        "Project No.: 2026RSD03TL", "Run/TCN No.: 001", "ADNOC BAB UHTW/UHTW 4.750/4.750",
        "F00321662 / D0527190-2 revB", "Inboard Seal", "Outboard Seal", "C100603035 (SL WAVY)",
        "668838NL (10)", "min 75 hours", "2980 rpm", "Process Fluid", "Barrier Fluid", "NA", "70 barg",
        "60°C", "TBD l/min", "Prepared by: MG",
    ]:  # fmt: skip
        assert key in normalized(issued_look)

    # The draft preview is the same document with the draft marking under the header.
    draft = render(tcn)
    assert draft.index(DRAFT_MARK) == 1  # right under the header line
    assert [line for line in draft if line != DRAFT_MARK] == issued_look


def test_at2_run_description_indent_levels(tcn001):
    """Run description lines keep their characters; leading spaces become indent classes."""
    html = ChromiumTemplate.load("tcn").render_html(build_tcn_context(tcn001))
    assert '<p class="run-line level-0">• Pre-test work required on stationary and rotating seal faces.</p>' in html
    assert '<p class="run-line level-1">- Waviness measurement on 1 location</p>' in html
    assert "{%" not in html and "{{" not in html


def single_plug_project(user):
    """2025RSD02TL TCN001 (Excel arrangement 1): IB columns = Plug Seal, OB columns = Test Seal."""
    row = data_2025rsd02tl.ROW
    assert data_2025rsd02tl.ARRANGEMENT == "1"
    project = make_project(user, project_no="2025RSD02TL", description=row["ProjName"])
    setup = project.default_setup
    setup.arrangement = Arrangement.SINGLE
    setup.plug_seal_present = True
    setup.run_description = row["TestRunDescription"]
    setup.test_unit, setup.speed, setup.duration = row["TestUnit"], row["Speed"], row["Duration"]
    setup.reference_drawing = row["RefDwg"]
    setup.process_medium, setup.process_pressure = row["Product"], row["ProdPress"]
    setup.process_inlet_temperature, setup.process_flow = row["ProdTemp"], row["ProdFlow"]  # typed "40°C"
    setup.save()
    setup.positions.all().delete()
    for role, prefix in [("plug", "IB"), ("test", "OB")]:
        setup.positions.create(
            role=role,
            seal_type_size=row[prefix + "SealType"],
            stationary_face=row[prefix + "StatFace"],
            rotating_face=row[prefix + "RotFace"],
            springs=row[prefix + "Spring"],
        )
    return project


def test_at3_single_with_plug_seal_regression(user, render):
    tcn = create_tcn(single_plug_project(user), 1, user)
    lines = render(tcn, is_draft=False)
    text = normalized(lines)

    assert "Plug Seal Test Seal" in lines
    assert "Seal Type and Size: DHTW 4.750 DHTW 4.750" in lines
    assert "Stationary Seal Face C0625623AP C0625623AP" in lines
    assert "Rotating Seal Face: C0625624SL - WAVY C0625624SL - WAVY" in lines
    assert "Spring(s): 668818NL (18) 668818NL (16)" in lines
    # The Excel "Product" values are the conditions established with the Plug Seal: one Process
    # column, no separate Plug Seal column; no Flush column (seal support empty).
    assert "Process Fluid" in lines
    assert "Test Medium: Water" in lines
    assert "Pressure: 80 barg" in lines
    assert "Inlet Temperature: 40°C" in lines and "40°C°C" not in text
    assert "Flow: TBD l/min" in lines
    assert "Flush" not in text and "Plug Seal Fluid" not in text
    assert "Duration: 50 hours" in lines and "Speed: 1100 rpm" in lines
    assert "• Pre-test work Job & Plug seal, required on stationary and rotating seal faces." in lines


def test_at16_plug_seal_process_and_barrier_one_speed(user, render):
    """AT-16 (document part): dual + Plug Seal prints the process conditions (established with
    the Plug Seal) and the barrier conditions, each with its own values; no Plug Seal Fluid
    column; speed once."""
    project = make_project(user)
    setup = project.default_setup
    setup.plug_seal_present = True
    setup.speed = "2980"
    values = {
        "process": ("Crude oil", "40", "80", "12"),
        "seal_support": ("ISO VG 32", "70", "60", "8"),
    }
    for circuit, (medium, pressure, temperature, flow) in values.items():
        setattr(setup, f"{circuit}_medium", medium)
        setattr(setup, f"{circuit}_pressure", pressure)
        setattr(setup, f"{circuit}_inlet_temperature", temperature)
        setattr(setup, f"{circuit}_flow", flow)
    setup.save()
    setup.positions.create(role="plug")
    lines = render(create_tcn(project, 1, user))

    assert "Plug Seal Inboard Seal Outboard Seal" in lines
    assert "Process Fluid Barrier Fluid" in lines
    assert "Test Medium: Crude oil ISO VG 32" in lines
    assert "Pressure: 40 barg 70 barg" in lines
    assert "Inlet Temperature: 80°C 60°C" in lines
    assert "Flow: 12 l/min 8 l/min" in lines
    assert not [line for line in lines if "Plug Seal Fluid" in line]
    assert [line for line in lines if line.startswith("Speed:")] == ["Speed: 2980 rpm"]


def test_text_is_escaped_not_interpreted(user, render):
    project = make_project(user, description="A & B <C> {{ project_no }}")
    tcn = create_tcn(project, 1, user)
    tcn.setup.run_description = "• Step {% if x %} & <b>bold</b>"
    tcn.setup.save()
    lines = render(tcn)
    assert "A & B <C> {{ project_no }}" in lines
    assert "• Step {% if x %} & <b>bold</b>" in lines

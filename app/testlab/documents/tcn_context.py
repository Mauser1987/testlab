"""Render context of the TCN document (M1 spec §9.2, §9.3).

The only place that knows the TCN's labels, units, NA rule and column sets.
It reads the TCN revision and its own run setup (the snapshot taken when
the TCN was created) — never the project defaults. The project number is
read from the project: it cannot change once a TCN has been issued (§3, V2).

Returns plain strings and lists, so the Word template needs no logic
beyond loops.
"""

import re

from django.utils import dateformat

from testlab.projects import conditions
from testlab.projects.arrangements import Arrangement, SealRole, seal_support_label

# As on the Excel TCN: temperature without a space ("60°C"), others with one.
_UNIT_SPACING = {"°C": ""}


def build_tcn_context(tcn):
    setup = tcn.setup
    return {
        "project_no": tcn.test_run.project.project_no,
        "tcn_no": tcn.tcn_no,
        "is_draft": tcn.status == tcn.Status.DRAFT,
        "project_description": tcn.project_description,
        "run_description_lines": run_description_lines(setup.run_description),
        "reference_drawing": setup.reference_drawing,
        "seal_columns": seal_columns(setup),
        "test_unit": setup.test_unit,
        "duration": with_unit("duration", setup.duration),
        "speed": with_unit("speed", setup.speed),
        "condition_columns": condition_columns(setup),
        "prepared_by": tcn.prepared_by,
        "created_date": format_date(tcn.created_date),
    }


def tcn_file_name(tcn, draft=False):
    """e.g. 2026RSD03TL-TCN001.docx, 2026RSD03TL-TCN001-rev1.docx (§4); previews end in -DRAFT."""
    revision = f"-rev{tcn.revision}" if tcn.revision else ""
    suffix = "-DRAFT" if draft else ""
    return f"{tcn.test_run.project.project_no}-TCN{tcn.test_run.display_no}{revision}{suffix}.docx"


def format_date(value):
    """dd-Mmm-yyyy, e.g. 16-Jun-2026 (§15 Q-D); independent of the server locale."""
    return dateformat.format(value, "d-M-Y")


def with_unit(field, value, empty=""):
    """Value followed by its printed unit; `empty` when there is no value (E8, E9)."""
    if not value:
        return empty
    unit = conditions.field_unit(field)
    if unit is None:
        return value
    return f"{value}{_UNIT_SPACING.get(unit, ' ')}{unit}"


def run_description_lines(text):
    """One entry per line; leading whitespace becomes an indent level 0–2 (§9.3)."""
    lines = []
    for line in text.splitlines():
        indent = re.match(r"[ \t]*", line).group()
        width = len(indent.expandtabs(4))
        level = 0 if width == 0 else 1 if width <= 4 else 2
        lines.append({"text": line.strip(), "level": level})
    return lines


def seal_columns(setup):
    """Seal Information columns: Plug Seal (if installed), then the seal(s) under test."""
    positions = {p.role: p for p in setup.positions.all()}
    columns = []
    for role in setup.applicable_roles():
        position = positions.get(role)
        column = {"heading": SealRole(role).label}
        for field in ["seal_type_size", "stationary_face", "rotating_face", "springs"]:
            column[field] = getattr(position, field, "")
        columns.append(column)
    return columns


def condition_columns(setup):
    """Test Conditions columns: Process, seal support, Plug Seal (§5.2, §9.3)."""
    columns = [_condition_column("Process Fluid", setup, conditions.PROCESS_FIELDS, empty="NA")]
    support_filled = any(getattr(setup, field) for field in conditions.SEAL_SUPPORT_FIELDS)
    if setup.arrangement != Arrangement.SINGLE or support_filled:
        heading = f"{seal_support_label(setup.arrangement)} Fluid"
        columns.append(_condition_column(heading, setup, conditions.SEAL_SUPPORT_FIELDS, empty=""))
    if setup.plug_seal_present:
        columns.append(_condition_column("Plug Seal Fluid", setup, conditions.PLUG_FIELDS, empty="NA"))
    return columns


def _condition_column(heading, setup, fields, empty):
    medium, pressure, inlet_temperature, flow = fields
    return {
        "heading": heading,
        "medium": getattr(setup, medium) or empty,
        "pressure": with_unit(pressure, getattr(setup, pressure), empty),
        "inlet_temperature": with_unit(inlet_temperature, getattr(setup, inlet_temperature), empty),
        "flow": with_unit(flow, getattr(setup, flow), empty),
    }

"""AT-5 (diff part): re-create 2026RSD03TL TCN002–004 by copying.

Starting from TCN001 (project defaults = the workbook row of run 001), each
next TCN is created with "Copy to new TCN" and only the fields that really
differ in the workbook are edited through the S7 form. Each result must
equal its workbook row, and the markers must show exactly the edited fields.
"""

import pytest
from django.urls import reverse

from testlab.projects.arrangements import Arrangement
from testlab.tcn.diff import source_changes
from testlab.tcn.models import TcnRevision

from . import data_2026rsd03tl as workbook
from .factories import make_project
from .test_views import edit_data, edit_url

pytestmark = pytest.mark.django_db

SETUP_COLUMNS = {
    "TestRunDescription": "run_description",
    "TestUnit": "test_unit",
    "Speed": "speed",
    "RefDwg": "reference_drawing",
    "Duration": "duration",
    "Bar/Buf": "seal_support_medium",
    "Bar/BufPress": "seal_support_pressure",
    "Bar/BufTemp": "seal_support_inlet_temperature",
    "Bar/BufFlow": "seal_support_flow",
}
POSITION_COLUMNS = {
    "SealType": "seal_type_size",
    "StatFace": "stationary_face",
    "RotFace": "rotating_face",
    "Spring": "springs",
}
ROLES = {"IB": "inboard", "OB": "outboard"}


def as_row(tcn):
    """The TCN in the workbook's DataBase columns."""
    setup = tcn.setup
    row = {"ProjName": tcn.project_description, "By": tcn.prepared_by}
    row.update({column: getattr(setup, field) for column, field in SETUP_COLUMNS.items()})
    positions = {p.role: p for p in setup.positions.all()}
    for prefix, role in ROLES.items():
        for suffix, field in POSITION_COLUMNS.items():
            row[prefix + suffix] = getattr(positions[role], field)
    return row


def expected_row(run_no):
    # Stored text is trimmed at the end (V8); the workbook keeps a trailing newline.
    return {column: value.rstrip() for column, value in workbook.ROWS[run_no].items()}


def load_defaults(project, run_no):
    row = workbook.ROWS[run_no]
    setup = project.default_setup
    setup.arrangement = workbook.ARRANGEMENT
    setup.monitored_parameters = workbook.MONITORED_PARAMETERS
    for column, field in SETUP_COLUMNS.items():
        setattr(setup, field, row[column])
    setup.save()
    for prefix, role in ROLES.items():
        setup.positions.filter(role=role).update(
            **{field: row[prefix + suffix] for suffix, field in POSITION_COLUMNS.items()}
        )


def copy_next(client, project, run_no):
    """Copy to new TCN from the proposed source (the previous TCN)."""
    form = client.get(reverse("tcn:create", args=[project.pk])).context["form"]
    assert form.initial["run_no"] == f"{run_no:03d}"
    response = client.post(
        reverse("tcn:create", args=[project.pk]),
        {"run_no": form.initial["run_no"], "source_type": "copy", "source": form.initial["source"].pk},
    )
    assert response.status_code == 302
    return TcnRevision.objects.get(test_run__project=project, test_run__run_no=run_no)


def edit(client, tcn, **fields):
    response = client.post(edit_url(tcn), edit_data(tcn, **fields))
    assert response.status_code == 302, response.content.decode()
    return TcnRevision.objects.get(pk=tcn.pk)


def test_at5_recreate_2026rsd03tl_tcn002_to_004(client, user, other_user):
    maria, mark = user, other_user  # initials MG and MT, as in the workbook's "By"
    row = workbook.ROWS
    project = make_project(maria, project_no="2026RSD03TL", description=row[1]["ProjName"])
    load_defaults(project, 1)
    client.force_login(maria)

    # TCN001 from the project defaults: nothing to edit, nothing to compare.
    response = client.post(reverse("tcn:create", args=[project.pk]), {"run_no": "1", "source_type": "defaults"})
    tcn001 = TcnRevision.objects.get(test_run__run_no=1)
    assert as_row(tcn001) == expected_row(1)
    assert tcn001.setup.arrangement == Arrangement.DUAL_PRESSURIZED
    assert tcn001.setup.monitored_parameters == workbook.MONITORED_PARAMETERS
    assert client.get(response["Location"]).context["change_list"] is None

    # 002 ← 001: run description.
    tcn002 = edit(client, copy_next(client, project, 2), run_description=row[2]["TestRunDescription"])
    assert as_row(tcn002) == expected_row(2)
    assert [c.key for c in source_changes(tcn002)] == ["run_description"]

    # 003 ← 002: run description, prepared by MT, IB/OB stationary and rotating faces.
    tcn003 = edit(
        client,
        copy_next(client, project, 3),
        run_description=row[3]["TestRunDescription"],
        prepared_by="MT",
        **{
            "inboard-stationary_face": row[3]["IBStatFace"],
            "inboard-rotating_face": row[3]["IBRotFace"],
            "outboard-stationary_face": row[3]["OBStatFace"],
            "outboard-rotating_face": row[3]["OBRotFace"],
        },
    )
    assert as_row(tcn003) == expected_row(3)
    assert [c.key for c in source_changes(tcn003)] == [
        "prepared_by",
        "run_description",
        "inboard-stationary_face",
        "inboard-rotating_face",
        "outboard-stationary_face",
        "outboard-rotating_face",
    ]

    # 004 ← 003, created by Mark Test (prepared by defaults to MT): run description, barrier temperature.
    client.force_login(mark)
    tcn004 = edit(
        client,
        copy_next(client, project, 4),
        run_description=row[4]["TestRunDescription"],
        seal_support_inlet_temperature=row[4]["Bar/BufTemp"],
    )
    assert as_row(tcn004) == expected_row(4)
    changes = source_changes(tcn004)
    assert [c.key for c in changes] == ["run_description", "seal_support_inlet_temperature"]
    assert (changes[1].label, changes[1].old, changes[1].new) == ("Barrier inlet temperature", "60", "60 - 40")

    # The page shows exactly these markers.
    content = client.get(edit_url(tcn004)).content.decode()
    assert "2 differences from TCN003" in content
    assert content.count('class="was"') == 2
    assert "changed — was: 60</span>" in content

    # Earlier TCNs are unchanged by the later copies and edits.
    for run_no, tcn in [(1, tcn001), (2, tcn002), (3, tcn003)]:
        assert as_row(TcnRevision.objects.get(pk=tcn.pk)) == expected_row(run_no)

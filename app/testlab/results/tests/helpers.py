"""Test helpers for the Result (M2B)."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from testlab.execution import manual_log
from testlab.projects.models import SealPosition
from testlab.tcn.services import create_tcn
from testlab.tcn.tests.factories import make_project

AMS = ZoneInfo("Europe/Amsterdam")
START = datetime(2026, 6, 29, 9, 0, tzinfo=AMS)


def make_run(user, arrangement="dual_pressurized", plug_seal=False, project_no="2026RSD03TL", **faces):
    """A run whose draft TCN has the given configuration; faces: {role: (stationary, rotating)}."""
    project = make_project(user, project_no=project_no, description="ADNOC BAB")
    run = create_tcn(project, 1, user).test_run
    configure(run, arrangement, plug_seal, **faces)
    return run


def configure(run, arrangement, plug_seal=False, **faces):
    setup = run.current_revision().setup
    setup.arrangement = arrangement
    setup.plug_seal_present = plug_seal
    setup.save()
    setup.positions.all().delete()
    for role in setup.applicable_roles():
        stationary, rotating = faces.get(role, ("", ""))
        SealPosition.objects.create(setup=setup, role=role, stationary_face=stationary, rotating_face=rotating)
    return setup


def log(run, user, hours, **values):
    """A manual log reading `hours` after START; values by measurement code."""
    columns = manual_log.log_columns(run)
    cleaned = {
        "observed_at": START + timedelta(hours=hours),
        "note": values.pop("note", ""),
        "category": values.pop("category", ""),
        "leakage_hours": values.pop("leakage_hours", None),
    }
    cleaned.update({code: Decimal(str(value)) for code, value in values.items()})
    return manual_log.save_entry(run, cleaned, columns, user)

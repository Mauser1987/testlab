"""Migrations 0003–0005: face lengths typed in the M2B table become dimensional measurements."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

OTHERS = [("projects", "0006_remove_plug_seal_conditions"), ("tcn", "0001_initial"),
          ("execution", "0002_manuallogentry_category")]  # fmt: skip
BEFORE = [("results", "0002_resultplot"), *OTHERS]
AFTER = [("results", "0005_delete_inspectionmeasurement"), *OTHERS]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def old_apps():
    apps = migrate(BEFORE)
    yield apps
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_face_lengths_are_kept_typed_instrument_values_are_dropped(old_apps):
    apps = old_apps
    user = apps.get_model("auth", "User").objects.create(username="mgeerts")
    setup = apps.get_model("projects", "RunSetup").objects.create()
    project = apps.get_model("projects", "Project").objects.create(
        project_no="2026RSD03TL", description="TEST", default_setup=setup, created_by=user, updated_by=user
    )
    run = apps.get_model("tcn", "TestRun").objects.create(project=project, run_no=1, created_by=user)
    result = apps.get_model("results", "TestResult").objects.create(test_run=run, created_by=user, updated_by=user)
    stator = apps.get_model("results", "ResultComponent").objects.create(
        result=result, position="outboard", component="stator"
    )
    Old = apps.get_model("results", "InspectionMeasurement")
    Old.objects.create(component=stator, quantity="face_length", pre_value=Decimal("1.25037"),
                       post_value=Decimal("1.25025"), unit="in", updated_by=user)  # fmt: skip
    Old.objects.create(component=stator, quantity="face_waviness", pre_value=Decimal("0.7"), unit="µm",
                       updated_by=user)  # fmt: skip

    apps = migrate(AFTER)
    measurements = apps.get_model("results", "FaceMeasurement").objects.order_by("stage")
    assert [(m.stage, m.kind, m.status, m.reported) for m in measurements] == [
        ("post", "dimensional", "reviewed", True), ("pre", "dimensional", "reviewed", True),
    ]  # fmt: skip
    readings = apps.get_model("results", "DimensionalReading").objects.order_by("value")
    assert [(r.value, r.unit) for r in readings] == [(Decimal("1.25025"), "in"), (Decimal("1.25037"), "in")]
    assert all(m.reviewed_by_id == user.pk for m in measurements)
    result = apps.get_model("results", "TestResult").objects.get()
    assert result.mahr_applicability == "required"  # existing Results: every kind expected

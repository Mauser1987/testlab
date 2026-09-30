"""Migrations 0005/0006: Plug Seal conditions merged into the Process Conditions."""

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

data_migration = importlib.import_module("testlab.projects.migrations.0005_merge_plug_seal_conditions_into_process")

BEFORE = [("projects", "0004_project_default_setup_required"), ("tcn", "0001_initial")]
AFTER = [("projects", "0006_remove_plug_seal_conditions"), ("tcn", "0001_initial")]


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


def make_setup(apps, roles, **fields):
    setup = apps.get_model("projects", "RunSetup").objects.create(**fields)
    for role in roles:
        apps.get_model("projects", "SealPosition").objects.create(setup=setup, role=role)
    return setup


def make_project(apps, project_no, setup):
    User = apps.get_model("auth", "User")
    user, _ = User.objects.get_or_create(username="mgeerts")
    return apps.get_model("projects", "Project").objects.create(
        project_no=project_no, description="TEST", default_setup=setup, created_by=user, updated_by=user
    )


def make_tcn(apps, project, setup, status="draft"):
    user = apps.get_model("auth", "User").objects.get(username="mgeerts")
    run = apps.get_model("tcn", "TestRun").objects.create(project=project, run_no=1, created_by=user)
    issued = {"issued_at": "2026-06-16T10:00:00Z", "issued_by": user} if status != "draft" else {}
    return apps.get_model("tcn", "TcnRevision").objects.create(
        test_run=run,
        setup=setup,
        status=status,
        source_kind="project_defaults",
        issued_snapshot={"condition_columns": ["as issued"]} if issued else None,
        issued_document_sha256="ab" * 32 if issued else "",
        created_by=user,
        updated_by=user,
        **issued,
    )


def test_plug_values_move_to_process_and_codes_are_renamed(old_apps):
    RunSetup = old_apps.get_model("projects", "RunSetup")
    moved = make_setup(
        old_apps,
        ["plug", "inboard", "outboard"],
        arrangement="dual_pressurized",
        plug_seal_present=True,
        process_medium="Water",  # equal to the plug value: kept once
        plug_medium="Water",
        plug_pressure="35",
        plug_inlet_temperature="45",
        process_flow="12",  # no plug value: kept
        seal_support_medium="ISO VG 32",
        monitored_parameters=["plug_pressure", "process_pressure", "plug_flow", "plug_leakage", "seal_support_flow"],
    )
    project = make_project(old_apps, "2099RSD01TL", moved)
    issued = make_setup(
        old_apps, ["plug", "test"], arrangement="single", plug_seal_present=True, plug_medium="Oil", plug_flow="5"
    )
    tcn = make_tcn(old_apps, project, issued, status="issued")
    single = make_setup(old_apps, ["test"], arrangement="single", monitored_parameters=["test_leakage"])
    dual = make_setup(old_apps, ["inboard", "outboard"], seal_support_pressure="70")

    new_apps = migrate(AFTER)
    RunSetup = new_apps.get_model("projects", "RunSetup")
    positions = new_apps.get_model("projects", "SealPosition").objects

    moved = RunSetup.objects.get(pk=moved.pk)
    assert (moved.process_medium, moved.process_pressure, moved.process_inlet_temperature, moved.process_flow) == (
        "Water", "35", "45", "12",
    )  # fmt: skip
    assert moved.seal_support_medium == "ISO VG 32"
    assert moved.monitored_parameters == ["process_pressure", "process_flow", "seal_support_flow", "plug_leakage"]
    assert not [f.name for f in RunSetup._meta.fields if f.name.startswith("plug_") and f.name != "plug_seal_present"]

    # Issued TCN: its working setup follows the new model; the issued record is untouched.
    issued = RunSetup.objects.get(pk=issued.pk)
    assert (issued.process_medium, issued.process_flow) == ("Oil", "5")
    tcn = new_apps.get_model("tcn", "TcnRevision").objects.get(pk=tcn.pk)
    assert tcn.issued_snapshot == {"condition_columns": ["as issued"]} and tcn.issued_document_sha256 == "ab" * 32

    # A single seal is tested with the Plug Seal.
    single = RunSetup.objects.get(pk=single.pk)
    assert single.plug_seal_present
    assert sorted(positions.filter(setup=single).values_list("role", flat=True)) == ["plug", "test"]
    assert single.monitored_parameters == ["test_leakage"]

    dual = RunSetup.objects.get(pk=dual.pk)
    assert (dual.plug_seal_present, dual.seal_support_pressure) == (False, "70")


def test_rows_needing_a_decision_stop_the_migration_and_change_nothing(old_apps):
    RunSetup = old_apps.get_model("projects", "RunSetup")
    conflict = make_setup(
        old_apps,
        ["plug", "inboard", "outboard"],
        plug_seal_present=True,
        process_pressure="40",
        plug_pressure="35",
        plug_medium="Water",
    )
    make_project(old_apps, "2099RSD01TL", conflict)
    no_plug = make_setup(
        old_apps, ["inboard", "outboard"], process_medium="Water", monitored_parameters=["process_flow"]
    )
    make_project(old_apps, "2099RSD02TL", no_plug)
    single = make_setup(old_apps, ["test"], arrangement="single")

    with pytest.raises(data_migration.ProcessConditionsConflict) as excinfo:
        migrate(AFTER)
    report = str(excinfo.value)
    assert "nothing was changed" in report
    assert f"RunSetup {conflict.pk} (project defaults of 2099RSD01TL): pressure differs — Process “40”, Plug Seal “35”." in report
    assert (
        f"RunSetup {no_plug.pk} (project defaults of 2099RSD02TL): process conditions without a Plug Seal — "
        "process_medium “Water”, process_flow." in report
    )

    # Rolled back: the old fields and values are still there, nothing half-migrated.
    old_apps = migrate(BEFORE)
    RunSetup = old_apps.get_model("projects", "RunSetup")
    conflict = RunSetup.objects.get(pk=conflict.pk)
    assert (conflict.process_pressure, conflict.plug_pressure, conflict.plug_medium) == ("40", "35", "Water")
    assert (conflict.process_medium, conflict.plug_medium) == ("", "Water")
    assert not RunSetup.objects.get(pk=single.pk).plug_seal_present

    # After the engineer's decision the migration runs.
    RunSetup.objects.filter(pk=conflict.pk).update(plug_pressure="40")
    RunSetup.objects.filter(pk=no_plug.pk).update(plug_seal_present=True)
    old_apps.get_model("projects", "SealPosition").objects.create(setup_id=no_plug.pk, role="plug")
    RunSetup = migrate(AFTER).get_model("projects", "RunSetup")
    conflict = RunSetup.objects.get(pk=conflict.pk)
    assert (conflict.process_medium, conflict.process_pressure) == ("Water", "40")

from django.db import migrations

# Frozen copy of the rule at the time of this migration: the default
# project setup is dual pressurized without Plug Seal (M1 spec §7).
DEFAULT_ROLES = ["inboard", "outboard"]


def create_default_setups(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    RunSetup = apps.get_model("projects", "RunSetup")
    SealPosition = apps.get_model("projects", "SealPosition")
    for project in Project.objects.filter(default_setup__isnull=True):
        setup = RunSetup.objects.create(arrangement="dual_pressurized", plug_seal_present=False)
        for role in DEFAULT_ROLES:
            SealPosition.objects.create(setup=setup, role=role)
        project.default_setup = setup
        project.save(update_fields=["default_setup"])


class Migration(migrations.Migration):
    dependencies = [("projects", "0002_run_setup_and_seal_positions")]

    operations = [migrations.RunPython(create_default_setups, migrations.RunPython.noop)]

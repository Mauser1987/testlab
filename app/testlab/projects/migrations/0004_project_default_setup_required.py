import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_create_project_default_setups")]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="default_setup",
            field=models.OneToOneField(
                editable=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="default_for_project",
                to="projects.runsetup",
            ),
        ),
    ]

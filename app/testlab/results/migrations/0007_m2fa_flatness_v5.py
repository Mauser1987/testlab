"""M2F-a: engines mahr-2 / roundpak-2 (Seal_Face_Flatness_Claude_v5.html).

Stored results are not recalculated. Existing Mahr analyses get skip_points
= 0, the setting they were calculated with, so a deliberate recalculation of
a Draft reproduces their numbers; new ones default to 5 (v5). The ROUNDPAK
full-width rise becomes the radial taper (same formula and sign); existing
rows stay unclassified (flat limit None).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("results", "0006_final_report_and_optional_components"),
    ]

    operations = [
        migrations.RemoveField(model_name="mahranalysis", name="geometry_confirmed"),
        migrations.AddField(
            model_name="mahranalysis",
            name="skip_points",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Skip first points"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="mahranalysis",
            name="skip_points",
            field=models.PositiveSmallIntegerField(default=5, verbose_name="Skip first points"),
        ),
        migrations.AddField(
            model_name="mahranalysis",
            name="flat_limit_hlb",
            field=models.FloatField(default=0.25, verbose_name="Flat limit (± HLB)"),
        ),
        migrations.AlterField(
            model_name="mahranalysis",
            name="pv_view",
            field=models.CharField(default="common", max_length=10, verbose_name="Profile view"),
        ),
        migrations.RenameField(model_name="roundpakanalysis", old_name="rise_um", new_name="taper_um"),
        migrations.AddField(
            model_name="roundpakanalysis",
            name="tilt_slope",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="roundpakanalysis",
            name="classification",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="roundpakanalysis",
            name="flat_limit_hlb",
            field=models.FloatField(blank=True, null=True, verbose_name="Flat limit (± HLB)"),
        ),
    ]

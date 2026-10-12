"""Face lengths typed into the M2B Pre/Post table become dimensional measurements (M2D).

Each stored Pre or Post face length becomes a reviewed, reported
DimensionalReading of its component, attributed to whoever last saved it.
The other typed quantities (waviness, taper, roughness) have no instrument
file behind them and are dropped: they are measured from the instrument
files from now on (decision of 2026-10-04).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    InspectionMeasurement = apps.get_model("results", "InspectionMeasurement")
    FaceMeasurement = apps.get_model("results", "FaceMeasurement")
    DimensionalReading = apps.get_model("results", "DimensionalReading")
    for old in InspectionMeasurement.objects.filter(quantity="face_length"):
        for stage, value in (("pre", old.pre_value), ("post", old.post_value)):
            if value is None:
                continue
            measurement = FaceMeasurement.objects.create(
                component_id=old.component_id, stage=stage, kind="dimensional", status="reviewed", reported=True,
                in_report_detail=False, report_figures=[], remark="Entered in the Pre/Post table (M2B).",
                created_by_id=old.updated_by_id, updated_by_id=old.updated_by_id,
                reviewed_by_id=old.updated_by_id, reviewed_at=old.updated_at,
            )
            DimensionalReading.objects.create(measurement=measurement, quantity="face_length", value=value,
                                              unit=old.unit or "in")


class Migration(migrations.Migration):
    dependencies = [("results", "0003_seal_face_measurements")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

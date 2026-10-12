from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("results", "0004_face_length_to_dimensional_readings")]

    operations = [migrations.DeleteModel(name="InspectionMeasurement")]

"""Test data of the Test Run Report (M2C): complete dual and single + Plug Seal runs."""

import io
import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from testlab.execution import datasets
from testlab.execution.tests.test_labview import NAME, export
from testlab.results import images, plots, services
from testlab.results.models import AcceptanceItem, ResultImage
from testlab.results.tests.helpers import START, log, make_run


def picture(name, size=(1200, 800), color="steelblue", fmt="JPEG"):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return SimpleUploadedFile(name, out.getvalue())


def png(size=(1200, 600)):
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def component(result, label):
    return next(c for c in result.components.all() if c.label == label)


def dual_run(user, readings=6):
    """Dual pressurized run 001 of 2026RSD03TL with every kind of evidence."""
    run = make_run(user, "dual_pressurized", inboard=("C100603033 (SIC30)", "C100603035 (SL Wavy)"),
                   outboard=("C100603033 (SIC30)", "C100603038 (SL Wavy)"))  # fmt: skip
    project = run.project
    project.customer = "ADNOC"
    project.save()
    setup = run.current_revision().setup
    setup.test_unit, setup.duration, setup.speed = "B", "72", "2980"
    setup.seal_support_medium, setup.seal_support_pressure, setup.seal_support_inlet_temperature = "Demi water", "70", "60"
    setup.reference_drawing = "UHTW 4.750 cartridge"
    setup.run_description = "Run on water at site conditions.\n    Leakage collected per seal."
    setup.save()
    setup.positions.update(seal_type_size="UHTW 4.750")
    # Readings at 0, 1, 4, 9, 16, 25 h (unequal intervals): leakage volumes (ml) since the previous reading.
    log(run, user, 0, speed=0, seal_support_pressure="70.05", inboard_leakage=5, note="Start recording", category="start")
    for n in range(1, readings):
        log(run, user, n * n, speed=2980 + n, seal_support_pressure=f"{69 + n * 0.5}", inboard_face_temp=60 + n,
            inboard_leakage=10 * n, outboard_leakage=4 * n)  # fmt: skip
    log(run, user, readings * readings, note="Cooling-water flow reduced", category="adjustment")
    result = services.create_result(run, user)
    ib_stator, ob_stator = component(result, "IB Stator"), component(result, "OB Stator")
    ib_stator.part_no, ib_stator.condition = "C100603033", "New"
    ib_stator.save()
    services.save_measurements(result, {
        (ib_stator.pk, "face_waviness"): (Decimal("0.323"), Decimal("0.389")),
        (ib_stator.pk, "face_length"): (Decimal("1.25037"), Decimal("1.25025")),
        (ob_stator.pk, "face_taper"): (Decimal("0.586"), None),
    }, user)  # fmt: skip
    images.add_image(result, picture("section.png", fmt="PNG", size=(1600, 700)), user,
                     ResultImage.Category.CROSS_SECTION, None, "Cross section of the new parts")  # fmt: skip
    images.add_image(result, picture("ib-rotor-pre.jpg"), user, ResultImage.Category.PRE_TEST,
                     component(result, "IB Rotor"), "IB rotor before")  # fmt: skip
    images.add_image(result, picture("ib-rotor-post.jpg", color="gray"), user, ResultImage.Category.POST_TEST,
                     component(result, "IB Rotor"), "IB rotor after")  # fmt: skip
    images.add_image(result, picture("ob-stator-post.jpg", size=(600, 900)), user, ResultImage.Category.POST_TEST,
                     ob_stator, "OB stator after")  # fmt: skip
    dataset = datasets.import_dataset(run, SimpleUploadedFile(NAME, export()), user)
    dataset.recording_started_at = START  # t = 0 of the run: the first reading
    dataset.save()
    definition = json.dumps({"signals": [{"column": 1, "axis": "y"}], "time_range": None, "caption": "Barrier inlet temperature"})
    plots.add_plot(result, dataset, definition, png(), user)
    definition = json.dumps({"signals": [{"column": 3, "axis": "y"}], "time_range": None, "caption": "Motor speed"})
    plots.add_plot(result, dataset, definition, png(), user)
    for order, (criterion, basis, fields) in enumerate([
        ("IB leakage", "leakage_rate", {"position": "inboard", "comparison": "<=", "limit": Decimal("15"), "unit": "ml/h"}),
        ("Test duration", "logged_hours", {"comparison": ">=", "limit": Decimal("72"), "unit": "h"}),
        ("IB stator wear", "wear_rate", {"component": ib_stator, "comparison": "<=", "limit": Decimal("0.0000025"), "unit": "in/h"}),
        ("Face condition", "manual", {"requirement_text": "No damage", "actual_text": "No damage seen", "assessment": "pass",
                                      "remark": "Visual inspection."}),
    ]):  # fmt: skip
        AcceptanceItem.objects.create(result=result, order=order, criterion=criterion, basis=basis, updated_by=user, **fields)
    result.observations = "Stable for the first 24 h.\n\nLeakage steady."
    result.conclusion = "The wavy faces performed acceptably."
    result.recommendation = ""
    result.save()
    return run


def single_plug_run(user, project_no="2025RSD02TL", readings=4):
    """Single seal with Plug Seal, every parameter logged: the manual-log table needs more than one table."""
    run = make_run(user, "single", plug_seal=True, project_no=project_no,
                   test=("SiC", "Carbon"), plug=("SiC", "SiC"))  # fmt: skip
    setup = run.current_revision().setup
    setup.process_medium, setup.process_pressure, setup.speed = "Crude oil", "40", "3600"
    setup.save()
    codes = ["speed", "torque", "process_pressure", "process_inlet_temp", "process_outlet_temp", "process_flow",
             "seal_support_pressure", "seal_support_inlet_temp", "seal_support_outlet_temp", "seal_support_flow",
             "plug_face_temp", "test_face_temp"]  # fmt: skip
    for n in range(readings):
        values = {code: 10 + n for code in codes}
        log(run, user, n, plug_leakage=3 + n, test_leakage=1 + n, **values)
    result = services.create_result(run, user)
    services.add_component(result, "plug", "rotor", user)
    test_rotor = component(result, "Test Rotor")
    services.save_measurements(result, {(test_rotor.pk, "face_length"): (Decimal("0.5"), Decimal("0.4999"))}, user)
    images.add_image(result, picture("plug-rotor-post.jpg"), user, ResultImage.Category.POST_TEST,
                     component(result, "Plug Rotor"))  # fmt: skip
    return run

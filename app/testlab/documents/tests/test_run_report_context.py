"""Test Run Report context (M2C): what the report shows and where it comes from. No Chromium needed."""

import json

import pytest
from django.urls import reverse

from testlab.documents import pdf, run_report_context
from testlab.documents.run_report_context import build_run_report_context, report_assets, run_report_file_name
from testlab.results import services
from testlab.results.tests.helpers import log, make_run

from .report_data import dual_run, single_plug_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(user):
    return dual_run(user)


@pytest.fixture
def context(run):
    return build_run_report_context(run)


def rows_by_parameter(context, heading):
    group = next(g for g in context["conditions"] if g["heading"] == heading)
    return {row["parameter"]: row for row in group["rows"]}


def test_context_is_plain_data_ready_for_a_snapshot(context):
    assert json.loads(json.dumps(context)) == context


def test_identification_from_project_tcn_and_logged_period(context):
    ident = context["identification"]
    assert (ident["project_no"], ident["customer"], ident["run_no"], ident["tcn_no"]) == ("2026RSD03TL", "ADNOC", "001", "TCN001")
    assert ident["tcn_status"] == "Draft" and ident["test_unit"] == "B" and ident["arrangement"] == "Dual Pressurized"
    assert [s["seal_type_size"] for s in ident["seals"]] == ["UHTW 4.750", "UHTW 4.750"]
    # t = 0 is the DCS recording start (the test export), the end the last evidence
    assert ident["start_source"] == "start of the LabVIEW recording" and ident["logged_hours"]
    assert context["is_draft"] is True


def test_description_comes_from_the_tcn(context):
    assert context["description"]["project"] == "ADNOC BAB"
    assert [line["text"] for line in context["description"]["run_lines"]] == [
        "Run on water at site conditions.", "Leakage collected per seal."
    ]


def test_configuration_seals_from_tcn_and_components_as_fitted(context):
    configuration = context["configuration"]
    assert configuration["reference_drawing"] == "UHTW 4.750 cartridge"
    assert [s["heading"] for s in configuration["seals"]] == ["Inboard Seal", "Outboard Seal"]
    ib_stator = next(c for c in configuration["components"] if c["label"] == "IB Stator")
    assert (ib_stator["part_no"], ib_stator["material"], ib_stator["condition"]) == ("C100603033", "C100603033 (SIC30)", "New")
    ob_rotor = next(c for c in configuration["components"] if c["label"] == "OB Rotor")
    assert ob_rotor["part_no"] == "—"  # missing value of an existing row


def test_conditions_put_instructed_beside_actual(context):
    common = rows_by_parameter(context, "Test run")
    assert common["Speed"]["instructed"] == "2980" and common["Speed"]["actual"] == "0 – 2985" and common["Speed"]["count"] == 6
    assert common["Test unit"]["instructed"] == "B" and common["Test unit"]["actual"] == "—"
    assert common["Duration"]["instructed"] == "72" and common["Duration"]["note"] == "logged period, clock time"
    assert common["Duration"]["criteria"][0]["requirement"] == "≥ 72 h"
    assert "Torque" not in common  # neither instructed nor logged
    barrier = rows_by_parameter(context, "Barrier")
    assert barrier["Medium"]["instructed"] == "Demi water"
    assert barrier["Pressure"]["instructed"] == "70" and barrier["Pressure"]["actual"] == "69.5 – 71.5"
    assert barrier["Inlet temp."]["instructed"] == "60" and barrier["Inlet temp."]["actual"] == "—"  # never logged
    inboard = rows_by_parameter(context, "Inboard Seal")
    assert inboard["Leakage, average"]["actual"] == "6.0"
    assert inboard["Leakage, average"]["criteria"] == [{"requirement": "≤ 15 ml/h", "assessment": "pass", "label": "Pass"}]


def test_leakage_is_total_volume_over_total_period_never_a_mean_of_rates(context):
    inboard, outboard = context["leakage"]
    # 10 + 20 + 30 + 40 + 50 ml over 1 + 3 + 5 + 7 + 9 h = 6.0 ml/h; the mean of the interval rates would be 6.8
    assert (inboard["total"], inboard["rated"], inboard["hours"], inboard["average"]) == ("155", "150", "25.00", "6.0")
    assert inboard["unrated"] == "5" and "collection period unknown" in inboard["unrated_notes"][0]
    assert inboard["criteria"][0]["assessment"] == "pass"
    assert (outboard["total"], outboard["average"], outboard["criteria"]) == ("60", "2.4", [])


def test_saved_plots_in_their_order_with_their_source(context, run):
    assert [p["caption"] for p in context["plots"]] == ["Barrier inlet temperature", "Motor speed"]
    first = context["plots"][0]
    assert first["number"] == 1 and first["dataset"] == run.dcs_datasets.get().original_name
    assert first["window"] == "whole recording" and first["signals"] == "(T04) LBI [T [C]] (left)"
    assert {a["path"] for a in context["assets"]} >= {p["src"] for p in context["plots"]}


def test_measurements_with_calculated_delta_only_what_was_measured(context):
    rows = {m["component"]: m["rows"] for m in context["measurements"]}
    assert set(rows) == {"IB Stator", "OB Stator"}
    waviness, length = rows["IB Stator"]
    assert (waviness["quantity"], waviness["pre"], waviness["post"], waviness["delta"], waviness["unit"]) == (
        "Face waviness", "0.323", "0.389", "+0.066", "µm")
    assert length["delta"] == "−0.00012"
    assert rows["OB Stator"][0]["post"] == "—" and rows["OB Stator"][0]["delta"] == "—"


def test_wear_only_for_face_length(context):
    assert [(w["component"], w["quantity"], w["wear"]) for w in context["wear"]] == [("IB Stator", "Face length", "0.00012")]
    wear = context["wear"][0]
    assert wear["hours"] == "25.00" and wear["rate"] == "4.8E-6"
    assert wear["criteria"][0]["assessment"] == "fail"


def test_cross_section_and_paired_pictures(context):
    pictures = context["pictures"]
    assert [p["caption"] for p in pictures["cross_sections"]] == ["Cross section of the new parts"]
    (pair_group,) = pictures["comparisons"]
    assert pair_group["label"] == "IB Rotor"
    (pair,) = pair_group["pairs"]
    assert (pair["pre"]["caption"], pair["post"]["caption"]) == ("IB rotor before", "IB rotor after")
    (single,) = pictures["single_stage"]  # OB Stator: post-test only, no empty placeholder
    assert single["stage"] == "Post-test" and single["rows"][0][0]["label"] == "OB Stator"
    assert single["rows"][0][0]["picture"]["orientation"] == "portrait"


def test_assets_are_the_stored_pictures_and_plots(context, run):
    files = report_assets(context)
    assert set(files) == {a["path"] for a in context["assets"]} and len(files) == 6
    result = run.result
    plot = result.plots.order_by("order").first()
    with plot.image.open("rb") as stored:
        assert files[f"assets/plot-{plot.pk}.png"] == stored.read()
    picture_asset = next(a for a in context["assets"] if a["kind"] == "picture")
    assert picture_asset["sha256"] == result.images.get(pk=picture_asset["id"]).sha256  # traceable to the original


def test_events_are_entries_with_an_event_or_note(context):
    assert [(e["ref"], e["category"], e["note"]) for e in context["events"]] == [
        ("E1", "Start / restart", "Start recording"), ("E2", "Adjustment", "Cooling-water flow reduced"),
    ]
    assert context["events"][1]["elapsed"] == "36.00"


def test_acceptance_records_with_engineer_and_calculated_assessments(context):
    rows = {a["criterion"]: a for a in context["acceptance"]}
    assert list(rows) == ["IB leakage", "Test duration", "IB stator wear", "Face condition"]
    assert (rows["IB leakage"]["actual"], rows["IB leakage"]["label"], rows["IB leakage"]["by"]) == ("6.0 ml/h", "Pass", "calculated")
    assert (rows["Test duration"]["label"], rows["Test duration"]["by"]) == ("Not evaluated", "to be assessed")  # never automatic
    assert (rows["Face condition"]["actual"], rows["Face condition"]["by"], rows["Face condition"]["remark"]) == (
        "No damage seen", "engineer", "Visual inspection.")


def test_narrative_as_written_and_empty_parts_omitted(context):
    narrative = context["narrative"]
    assert narrative["observations"] == [["Stable for the first 24 h."], ["Leakage steady."]]
    assert narrative["conclusion"] == [["The wavy faces performed acceptably."]] and narrative["recommendation"] == []
    assert context["sections"]["conclusion"] == 10


def test_manual_log_table_holds_only_logged_measurements(context):
    (table,) = context["log"]["tables"]
    labels = [(c["label"], c["unit"]) for c in table["columns"]]
    assert labels == [("Speed", "rpm"), ("Pressure", "barg"), ("Face temp.", "°C"), ("Period", "h"),
                      ("Inboard", "ml"), ("Inboard rate", "ml/h"), ("Outboard", "ml"), ("Outboard rate", "ml/h")]  # fmt: skip
    assert len(table["rows"]) == 7 and table["rows"][0]["event"] == "E1"
    second = table["rows"][1]
    assert second["cells"] == ["2981", "69.5", "61", "1.00", "10", "10.0", "4", "4.0"]
    assert [row["elapsed"] for row in table["rows"]][:3] == ["0.00", "1.00", "4.00"]  # chronological


def test_wide_manual_log_is_split_into_tables_repeating_date_and_time(user):
    context = build_run_report_context(single_plug_run(user))
    tables = context["log"]["tables"]
    assert len(tables) == 2
    assert all(len(t["columns"]) <= run_report_context.LOG_COLUMNS_PER_TABLE for t in tables)
    assert sum(len(t["columns"]) for t in tables) == 12 + 1 + 4
    assert all(len(t["rows"]) == 4 and t["rows"][0]["date"] for t in tables)
    assert tables[1]["groups"][0]["heading"] != tables[0]["groups"][-1]["heading"]  # split between groups


def test_single_with_plug_seal(user):
    context = build_run_report_context(single_plug_run(user))
    headings = [g["heading"] for g in context["conditions"]]
    assert headings == ["Test run", "Process fluid", "Flush", "Plug Seal", "Test Seal"]
    assert rows_by_parameter(context, "Process fluid")["Medium"]["instructed"] == "Crude oil"
    assert [s["seal"] for s in context["leakage"]] == ["Plug Seal", "Test Seal"]
    assert [c["label"] for c in context["configuration"]["components"]] == ["Test Stator", "Test Rotor", "Plug Rotor"]
    assert context["wear"][0]["component"] == "Test Rotor"
    assert context["pictures"]["single_stage"][0]["rows"][0][0]["label"] == "Plug Rotor"


def test_run_without_result_reports_tcn_and_log_only(user):
    run = make_run(user, "dual_pressurized")
    log(run, user, 0, speed=2980, inboard_leakage=0)
    context = build_run_report_context(run)
    assert context["has_result"] is False and context["log"]["tables"]
    assert context["plots"] == [] and context["acceptance"] == [] and context["assets"] == []
    assert set(context["sections"]) == {"description", "conditions", "leakage"}  # no seal data, no components


def test_empty_result_omits_empty_sections(user):
    run = make_run(user, "dual_pressurized")
    services.create_result(run, user)
    context = build_run_report_context(run)
    assert context["log"]["tables"] == [] and context["leakage"] == [] and context["events"] == []
    for absent in ["leakage", "plots", "events", "measurements", "pictures", "acceptance", "conclusion"]:
        assert absent not in context["sections"]
    assert context["sections"]["configuration"] == 2  # the components of the new Result


def test_report_belongs_to_its_own_run(user, run):
    other = make_run(user, "dual_pressurized", project_no="2026RSD04TL")
    context = build_run_report_context(other)
    assert context["identification"]["project_no"] == "2026RSD04TL"
    assert context["plots"] == [] and context["log"]["tables"] == [] and context["assets"] == []


def test_file_name(run):
    assert run_report_file_name(run) == "2026RSD03TL-Run001-TestRunReport-DRAFT.pdf"


# --- preview view ----------------------------------------------------------------------------


def test_preview_needs_login(client, run):
    response = client.get(reverse("results:report_preview", args=[run.pk]))
    assert response.status_code == 302 and "/login/" in response["Location"]


def test_preview_of_unknown_run_is_404(client, user):
    client.force_login(user)
    assert client.get(reverse("results:report_preview", args=[999])).status_code == 404


def test_preview_renders_the_runs_report(client, user, run, monkeypatch):
    calls = []

    class FakeTemplate:
        def render_pdf(self, context, assets):
            calls.append((context, assets))
            return b"%PDF-1.7 fake"

    monkeypatch.setattr("testlab.results.views.run_report_template", lambda: FakeTemplate())
    client.force_login(user)
    response = client.get(reverse("results:report_preview", args=[run.pk]))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'inline; filename="2026RSD03TL-Run001-TestRunReport-DRAFT.pdf"'
    assert response["Cache-Control"] == "no-store"
    (context, assets), = calls
    assert context["identification"]["run_no"] == run.display_no and context["is_draft"] and len(assets) == 6


def test_preview_failure_returns_to_the_result_with_the_reason(client, user, run, monkeypatch):
    class Broken:
        def render_pdf(self, context, assets):
            raise pdf.PdfConversionError("Chromium for Playwright is not installed.")

    monkeypatch.setattr("testlab.results.views.run_report_template", lambda: Broken())
    client.force_login(user)
    response = client.get(reverse("results:report_preview", args=[run.pk]), follow=True)
    assert "not installed" in response.content.decode()
    assert response.redirect_chain[-1][0] == reverse("results:result", args=[run.pk])


def test_result_page_offers_preview_report(client, user, run):
    client.force_login(user)
    page = client.get(reverse("results:result", args=[run.pk])).content.decode()
    assert "Preview Report" in page and reverse("results:report_preview", args=[run.pk]) in page

"""Report profiles (M2F-B1): Customer vs Engineering presentation of one record.

present() only selects from the record: every number shown is the record's own, whatever the profile.
The rendered HTML (the same template the PDF prints) is checked for the explanations each profile keeps.
"""

import json

import pytest

from testlab.documents import report_profiles
from testlab.documents.render import run_report_template
from testlab.documents.report_profiles import present
from testlab.documents.run_report_context import build_run_report_context

from .html_text import html_lines
from .report_data import dual_run

pytestmark = pytest.mark.django_db

RUNNING_NOTE = "Periods without evidence of the shaft state, and missing DCS data, are unknown"
LEAKAGE_METHOD = "Average dynamic leakage = Σ volumes of the collections made with the shaft running throughout"
ACCEPTANCE_NOTE = "Requirements come from the Test Program; an approved (issued) TCN change"
CONDITIONS_FULL = "Readings with the shaft stopped are in the complete logs and plots."
CONDITIONS_SHORT = "Actual: lowest – highest with the shaft running, start-up and stop transients included"


@pytest.fixture
def record(user):
    return build_run_report_context(dual_run(user))


def text(context):
    return "\n".join(html_lines(run_report_template().render_html(context)))


def test_customer_omits_the_internal_explanations_engineering_keeps_them(record):
    customer, engineering = text(present(record, "customer")), text(present(record, "engineering"))
    for paragraph in (RUNNING_NOTE, LEAKAGE_METHOD, ACCEPTANCE_NOTE, CONDITIONS_FULL, "Source: entered on the Test Result"):
        assert paragraph in engineering and paragraph not in customer, paragraph
    assert CONDITIONS_SHORT in customer  # a short reading of the actual ranges is always given
    assert "Annex A. Manually Logged Data" in engineering and "Annex A" not in customer
    assert "Customer report" in customer and "Engineering report" in engineering


def test_leakage_detail_rows_only_in_engineering(record):
    seal = next(s for s in record["leakage"] if s["mixed"] or s["excluded"] or s["static_average"])
    customer, engineering = text(present(record, "customer")), text(present(record, "engineering"))
    marker = f"{seal['seal']}, not in the average" if seal["excluded"] else f"{seal['seal']}, mixed-period collection"
    assert marker in engineering and marker not in customer


def table_values(context):
    """Every number the profiles must share: conditions, leakage, acceptance, Pre/Post summary, wear."""
    return {
        "conditions": [(r["parameter"], r["instructed"], r["actual"]) for g in context["conditions"]["groups"]
                       for r in g["rows"]],
        "leakage": [(s["seal"], s["total"], s["dynamic_volume"], s["dynamic_hours"], s["average"],
                     [(c["requirement"], c["assessment"]) for c in s["criteria"]]) for s in context["leakage"]],
        "acceptance": [(a["criterion"], a["requirement"], a["actual"], a["assessment"], a["remark"])
                       for a in context["acceptance"]],
        "summary": {(g["component"], r["quantity"]): (r["pre"]["value"], r["post"]["value"], r["delta"], r["wear"])
                    for g in context["measurements"] for r in g["rows"]},
        "wear": [(w["component"], w["wear"], w["rate"]) for w in context["wear"]],
        "running": (context["identification"]["running_hours"], context["identification"]["logged_hours"]),
    }  # fmt: skip


def test_profiles_show_identical_numbers_from_the_same_record(record):
    before = json.dumps(record, sort_keys=True)
    expected = table_values(record)
    customer, engineering = table_values(present(record, "customer")), table_values(present(record, "engineering"))
    assert customer == engineering == expected
    assert json.dumps(record, sort_keys=True) == before  # present() never changes the record


def test_locked_content_cannot_be_hidden_by_a_stored_selection(record):
    stored = {"flags": {"acceptance_table": False, "leakage_table": False, "qualifications": False,
                        "conclusion": False}}  # not switches: ignored
    context = present(record, "customer", stored)
    assert table_values(context) == table_values(record)
    assert context["narrative"] == record["narrative"]
    assert report_profiles.clean(stored) == {}


def test_coverage_qualification_when_the_leakage_details_are_hidden(record, settings):
    settings.TESTLAB_LEAKAGE_COVERAGE_WARNING_PCT = 100.0  # every seal with uncovered running time qualifies
    seals = [s for s in record["leakage"] if s["coverage_pct"] is not None and s["coverage_pct"] < 100]
    assert seals, "the sample needs a seal with uncovered running time"
    customer = present(record, "customer")
    assert len(customer["qualifications"]["leakage"]) == len(seals)
    assert "the average dynamic leakage applies to the covered time only" in customer["qualifications"]["leakage"][0]
    assert "the average dynamic leakage applies to the covered time only" in text(customer)
    # Shown with the details instead: the Engineering report lists the uncovered time itself.
    assert present(record, "engineering")["qualifications"]["leakage"] == []
    settings.TESTLAB_LEAKAGE_COVERAGE_WARNING_PCT = 0.0
    assert present(record, "customer")["qualifications"]["leakage"] == []


def test_unknown_shaft_state_and_provisional_data_are_always_stated(record):
    record = {**record, "identification": {**record["identification"], "unknown_hours": "1.50", "provisional": True,
                                          "start": "29-Jun-2026 08:00", "running_provisional": True}}  # fmt: skip
    found = present(record, "customer", {"flags": {"running_basis_note": False}})["qualifications"]["identification"]
    assert any("1.50 h of the logged period have no evidence of the shaft state" in q for q in found)
    assert any("t = 0 is the first manual log reading" in q for q in found)
    assert any("running intervals are not confirmed" in q for q in found)
    engineering = present(record, "engineering")["qualifications"]["identification"]
    assert not any("1.50 h" in q for q in engineering)  # stated in the running explanation instead
    assert any("not confirmed" in q for q in engineering)  # provisional: always


def slot_of(record, kind):
    return next(b["slot"] for b in record["measurement_details"] if b["kind"] == kind)


def test_face_measurements_summary_detail_figures_and_remark_per_slot(record):
    slot = slot_of(record, "roundpak")
    component_id = int(slot.split(":")[0])
    customer = present(record, "customer")
    assert customer["measurement_details"] == [] and customer["measurement_remarks"] == []
    rows = lambda c: [(g["component"], r["quantity"]) for g in c["measurements"] for r in g["rows"]  # noqa: E731
                      if g["component_id"] == component_id]
    assert ("IB Stator", "Face flatness (circular trace)") in rows(customer)
    chosen = present(record, "customer", {"slots": {slot: {"detail": True, "figures": ["roundpak_polar"]}}})
    (block,) = chosen["measurement_details"]
    assert block["slot"] == slot and [f["code"] for f in block["figures"]] == ["roundpak_polar"]
    hidden = present(record, "engineering", {"slots": {slot: {"summary": False, "detail": False}}})
    assert ("IB Stator", "Face flatness (circular trace)") not in rows(hidden)
    assert ("IB Stator", "Face taper (Mahr)") in rows(hidden)  # other slots of the component keep their rows
    assert slot not in [b["slot"] for b in hidden["measurement_details"]]


def test_measurement_remark_is_optional_in_the_customer_report(record):
    block = next(b for b in record["measurement_details"] if b["kind"] == "roundpak")
    record["measurement_details"][record["measurement_details"].index(block)]["sources"]["post"]["remark"] = "Lapped"
    assert present(record, "customer")["measurement_remarks"] == []
    shown = present(record, "customer", {"slots": {block["slot"]: {"remark": True}}})["measurement_remarks"]
    assert shown == [{"label": f"{block['title']} · Post-test", "text": "Lapped"}]
    engineering = present(record, "engineering")
    kept = next(b for b in engineering["measurement_details"] if b["slot"] == block["slot"])
    assert kept["sources"]["post"]["remark"] == "Lapped" and engineering["measurement_remarks"] == []


def test_pictures_and_plots_one_by_one(record):
    plot_ids = [p["id"] for p in record["plots"]]
    picture = record["pictures"]["comparisons"][0]["pairs"][0]["pre"]
    stored = {"pictures": {str(picture["id"]): False}, "plots": {str(plot_ids[0]): False}}
    context = present(record, "engineering", stored)
    shown = [p["id"] for p in report_profiles._all_pictures(context)]
    assert picture["id"] not in shown and len(shown) == len(report_profiles._all_pictures(record)) - 1
    assert [p["id"] for p in context["plots"]] == plot_ids[1:] and context["plots"][0]["number"] == 1
    assert {a["path"] for a in context["assets"]} == {p["src"] for p in report_profiles._all_pictures(context)} | {
        p["src"] for p in context["plots"]}  # only what is shown is rendered


def test_events_and_annex_follow_their_switches(record):
    assert record["events"], "the sample needs events"
    customer = present(record, "customer")
    assert customer["events"] == [] and customer["log"]["tables"] == [] and customer["narrative"] == record["narrative"]
    with_annex = present(record, "customer", {"flags": {"annex_manual_log": True}})
    assert with_annex["log"]["tables"] and all(row["event"] == "" for t in with_annex["log"]["tables"]
                                               for row in t["rows"])  # no reference to a hidden table


def test_sections_are_numbered_after_the_selection(record):
    customer = present(record, "customer", {"flags": {"events_table": False}})
    numbers = list(customer["sections"].values())
    assert numbers == list(range(1, len(numbers) + 1))


def test_schema_1_records_keep_their_items_and_honour_the_switches(record):
    legacy = json.loads(json.dumps(record))
    legacy.pop("schema")
    for group in legacy["measurements"]:
        group.pop("component_id")
    for block in legacy["measurement_details"]:
        block.pop("slot")
    context = present(legacy, "customer")
    assert len(context["measurement_details"]) == len(record["measurement_details"])  # as frozen
    assert LEAKAGE_METHOD not in text(context)

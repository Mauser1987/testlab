"""Frozen records and issued report documents (M2F-B1).

Finalizing freezes the record as revision 0 and issues the Engineering document from it. Other profiles
are issued later from the same frozen record and its frozen assets: issuing changes no evidence, never
reads live data, never overwrites a PDF. Issued documents are retrieved byte for byte against their
SHA-256; a record, asset or PDF that does not match is refused.
"""

import gzip
import hashlib
import importlib
import json
import re
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core import serializers
from django.core.files.base import ContentFile
from django.db.models import ProtectedError
from django.urls import reverse

from testlab.documents.render import ChromiumTemplate
from testlab.documents.run_report_context import build_run_report_context, report_assets
from testlab.documents.tests.pdf_text import pdf_lines
from testlab.documents.tests.report_data import dual_run
from testlab.execution import running_intervals
from testlab.execution.models import ManualLogEntry
from testlab.results import finalization, publication, records, report_contents
from testlab.results.models import (
    AcceptanceItem, FaceMeasurement, RecordIntegrityError, ReportDocument, ReportSelection, ResultImage, ResultPlot,
    ResultRevision, TestResult,
)  # fmt: skip

pytestmark = pytest.mark.django_db
migration = importlib.import_module("testlab.results.migrations.0008_m2fb1_report_profiles")
migration_b2 = importlib.import_module("testlab.results.migrations.0009_m2fb2_result_revisions")


class M2EApps:
    """The app registry as migrations 0008 and 0009 see it: TestResult still has the M2E final_* fields
    (dropped by 0009), here attributes of the given final Results; every other model is the current one."""

    def __init__(self, *finals):
        self.finals = list(finals)

    def get_model(self, app, name):
        if name != "TestResult":
            return apps.get_model(app, name)
        related = SimpleNamespace(select_related=lambda *a: self.finals)
        return SimpleNamespace(objects=SimpleNamespace(filter=lambda **k: related))


def m2e_final(result, user, pdf_name, pdf, sha256, snapshot, template_sha256=""):
    """The Result as M2E left it: final, with its PDF, hashes and snapshot on the Result itself."""
    TestResult.objects.filter(pk=result.pk).update(status="final", finalized_at=result.updated_at, finalized_by=user)
    final = TestResult.objects.select_related("test_run__project").get(pk=result.pk)
    final.final_document = SimpleNamespace(name=records.storage().save(pdf_name, ContentFile(pdf)))
    final.final_document_sha256, final.final_template_sha256, final.final_snapshot = sha256, template_sha256, snapshot
    return final


def make_finalizable(result, user):
    """The sample Result with what finalization needs (sample data only)."""
    test_run = result.test_run
    for dataset in test_run.dcs_datasets.all():
        state = running_intervals.state(dataset)
        if state.determination is not None and state.provisional:
            running_intervals.confirm(dataset, user, state.determination.pk)
    TestResult.objects.filter(pk=result.pk).update(conclusion=result.conclusion or "As expected.",
                                                   responsible_engineer=user)  # fmt: skip
    result.refresh_from_db()
    issues, _, evaluations = finalization.check(result, user)
    for e in evaluations:
        if e.missing:
            AcceptanceItem.objects.filter(pk=e.item.pk).update(assessment="not_evaluated")
    for component in result.components.all():
        for kind in ("dimensional", "mahr", "roundpak"):
            if component.applicability(kind) == "required" and not component.face_measurements.filter(
                    kind=kind, reported=True).count() >= 2:  # fmt: skip
                setattr(component, f"{kind}_applicability", "optional")
        component.save()
    issues, _, _ = finalization.check(result, user)
    assert issues == [], [i.message for i in issues]
    return result


@pytest.fixture
def final(user):
    run = dual_run(user)
    result = make_finalizable(run.result, user)
    return finalization.finalize(result, user)


def evidence_state(result):
    """Every evidence row of the Result and its run, serialized: issuing must not change any of it."""
    querysets = [TestResult.objects.filter(pk=result.pk), FaceMeasurement.objects.filter(component__result=result),
                 ResultImage.objects.filter(result=result), ResultPlot.objects.filter(result=result),
                 AcceptanceItem.objects.filter(result=result), ManualLogEntry.objects.filter(test_run=result.test_run),
                 result.components.all(), ResultRevision.objects.filter(result=result)]  # fmt: skip
    return [serializers.serialize("json", qs.order_by("pk")) for qs in querysets]


def read(name):
    with records.storage().open(name, "rb") as f:
        return f.read()


# ---- finalization: revision 0 and its Engineering document ----------------------------------------


def test_finalize_freezes_the_record_and_its_assets_and_issues_r0_e(final, user):
    (revision,) = final.revisions.all()
    record = records.read_record(revision)
    assert record["schema"] == 2 and record["is_draft"] is False
    assert hashlib.sha256(gzip.decompress(read(revision.record_file.name))).hexdigest() == revision.record_sha256
    assert {a["path"] for a in revision.assets} == {a["path"] for a in record["assets"]} and revision.assets
    for asset in revision.assets:  # frozen copies, as rendered, each with its SHA-256
        assert asset["file"].startswith(f"{records.revision_dir(final.test_run, 0)}/assets/")
        assert hashlib.sha256(read(asset["file"])).hexdigest() == asset["sha256"]
    (document,) = revision.documents.all()
    assert (document.identity, document.profile, document.issue, document.origin) == (
        "2026RSD03TL-Run001-TRR-R0-E", "engineering", 1, "finalized")
    assert hashlib.sha256(read(document.file.name)).hexdigest() == document.sha256
    assert document.selection["flags"]["leakage_details"] is True  # complete technical detail


def test_rendering_failure_writes_no_record_and_no_file(user, file_storage, monkeypatch):
    run = dual_run(user)
    result = make_finalizable(run.result, user)
    monkeypatch.setattr(ChromiumTemplate, "render_pdf", lambda self, *a, **k: (_ for _ in ()).throw(
        finalization.PdfConversionError("printer on fire")))  # fmt: skip
    with pytest.raises(finalization.FinalizationError, match="printer on fire"):
        finalization.finalize(result, user)
    assert not ResultRevision.objects.exists() and not ReportDocument.objects.exists()
    left = [p for p in file_storage.rglob("*") if p.is_file() and {"records", "reports"} & set(p.parts)]
    assert left == []


# ---- presentation-only publication ------------------------------------------------------------


def test_customer_report_from_the_frozen_record_changes_no_evidence(final, user):
    revision = final.revisions.get()
    before = evidence_state(final)
    document = publication.issue(revision, "customer", user)
    assert evidence_state(final) == before
    assert document.identity == "2026RSD03TL-Run001-TRR-R0-C" and document.origin == "issued"
    text = " ".join(" ".join(pdf_lines(read(document.file.name))).split())
    assert "2026RSD03TL-Run001-TRR-R0-C" in text and "Customer report" in text and "PREVIEW" not in text
    assert "Average dynamic leakage = Σ volumes" not in text  # clean
    engineering = " ".join(" ".join(pdf_lines(read(revision.documents.get(profile="engineering").file.name))).split())
    assert "Average dynamic leakage = Σ volumes" in engineering
    assert document.selection["flags"]["leakage_details"] is False


def test_issuing_never_reads_live_pictures_or_plots(final, user, monkeypatch):
    revision = final.revisions.get()

    def live_read(*args, **kwargs):
        raise AssertionError("a document of a final revision must not read live assets")

    monkeypatch.setattr("testlab.documents.run_report_context.report_assets", live_read)
    monkeypatch.setattr("testlab.results.publication.report_assets", live_read)
    picture = ResultImage.objects.filter(result=final).first()
    with records.storage().open(picture.preview_file, "wb") as f:  # the live display copy changes on disk
        f.write(b"not the frozen picture")
    document = publication.issue(revision, "customer", user)
    assert document.sha256 == hashlib.sha256(read(document.file.name)).hexdigest()


def test_reissue_needs_a_reason_and_supersedes_the_earlier_issue(final, user):
    revision = final.revisions.get()
    first = publication.issue(revision, "customer", user)
    first_bytes = read(first.file.name)
    with pytest.raises(publication.PublicationError, match="give the reason"):
        publication.issue(revision, "customer", user)
    ReportSelection.objects.create(result=final, profile="customer", updated_by=user,
                                   data={"flags": {"events_table": True}})  # fmt: skip
    second = publication.issue(revision, "customer", user, reason="Customer asked for the event list")
    first.refresh_from_db()
    assert second.identity == "2026RSD03TL-Run001-TRR-R0-C-2" and second.issue == 2
    assert first.status == "superseded" and first.superseded_by == second and "TRR-R0-C-2" in first.status_reason
    assert read(first.file.name) == first_bytes  # never overwritten
    text = " ".join(" ".join(pdf_lines(read(second.file.name))).split())
    assert "Document history" in text  # identity, result revision, issue date, status
    assert re.search(r"2026RSD03TL-Run001-TRR-R0-C 0 \S+ Superseded 2026RSD03TL-Run001-TRR-R0-C-2 0 \S+ Issued", text)
    assert "Customer asked" not in text  # reasons stay in the Engineering report and the application


def test_withdraw_needs_a_reason_and_keeps_the_document(final, user, client):
    document = final.revisions.get().documents.get()
    with pytest.raises(publication.PublicationError, match="reason"):
        publication.withdraw(document, user, " ")
    publication.withdraw(document, user, "Wrong customer address")
    document.refresh_from_db()
    assert document.status == "withdrawn" and document.status_reason == "Wrong customer address"
    with pytest.raises(publication.PublicationError, match="withdrawn, not issued"):
        publication.withdraw(document, user, "again")
    client.force_login(user)
    response = client.get(reverse("results:document", args=[document.pk]))
    assert response.status_code == 200 and response.content == read(document.file.name)


def test_superseded_and_withdrawn_are_distinct(final, user):
    revision = final.revisions.get()
    c1 = publication.issue(revision, "customer", user)
    c2 = publication.issue(revision, "customer", user, reason="New selection")
    publication.withdraw(c2, user, "Issued in error")
    c1.refresh_from_db()
    c2.refresh_from_db()
    assert (c1.status, c2.status) == ("superseded", "withdrawn")
    c3 = publication.issue(revision, "customer", user, reason="Corrected")
    assert c3.issue == 3 and ReportDocument.objects.filter(profile="customer", status="issued").get() == c3


# ---- integrity ---------------------------------------------------------------------------------------


def test_download_is_byte_identical_and_never_renders(final, user, client, monkeypatch):
    document = final.revisions.get().documents.get()
    monkeypatch.setattr(ChromiumTemplate, "render_pdf", lambda *a, **k: pytest.fail("rendered again"))
    client.force_login(user)
    response = client.get(reverse("results:document", args=[document.pk]))
    assert response.content == read(document.file.name)
    assert hashlib.sha256(response.content).hexdigest() == document.sha256
    assert response["Content-Disposition"] == 'attachment; filename="2026RSD03TL-Run001-TRR-R0-E.pdf"'


def test_altered_pdf_record_or_asset_is_refused(final, user, client):
    revision = final.revisions.get()
    document = revision.documents.get()
    with records.storage().open(document.file.name, "wb") as f:
        f.write(b"%PDF tampered")
    client.force_login(user)
    response = client.get(reverse("results:document", args=[document.pk]))
    assert response.status_code == 500 and b"does not match its SHA-256" in response.content
    asset = revision.assets[0]
    with records.storage().open(asset["file"], "wb") as f:
        f.write(b"tampered")
    with pytest.raises(RecordIntegrityError, match="does not match its SHA-256"):
        publication.issue(revision, "customer", user)
    tampered = json.loads(gzip.decompress(read(revision.record_file.name)))
    tampered["identification"]["running_hours"] = "999.00"
    with records.storage().open(revision.record_file.name, "wb") as f:
        f.write(gzip.compress(records.canonical(tampered)))
    with pytest.raises(RecordIntegrityError, match="record of .* does not match"):
        records.read_record(revision)


def test_records_and_documents_cannot_be_changed_or_deleted(final, user):
    revision = final.revisions.get()
    document = revision.documents.get()
    revision.record_sha256 = "0" * 64
    with pytest.raises(RecordIntegrityError):
        revision.save()
    with pytest.raises((RecordIntegrityError, ProtectedError)):
        ResultRevision.objects.get(pk=revision.pk).delete()
    document = ReportDocument.objects.get(pk=document.pk)
    document.sha256 = "0" * 64
    with pytest.raises(RecordIntegrityError):
        document.save()
    with pytest.raises(RecordIntegrityError):
        ReportDocument.objects.get(pk=document.pk).delete()


def test_issuing_needs_permission(final, user, monkeypatch, client):
    monkeypatch.setattr("testlab.results.publication.can_issue_report", lambda u: False)
    with pytest.raises(publication.PublicationError, match="not allowed"):
        publication.issue(final.revisions.get(), "customer", user)
    client.force_login(user)
    response = client.post(reverse("results:report_issue", args=[final.test_run.pk, "customer"]), follow=True)
    assert "Nothing was issued. You are not allowed" in response.content.decode()
    assert not ReportDocument.objects.filter(profile="customer").exists()


def test_documents_need_a_final_result(user, client):
    run = dual_run(user)
    client.force_login(user)
    response = client.post(reverse("results:report_issue", args=[run.pk, "customer"]), follow=True)
    assert "finalize it first" in response.content.decode() and not ReportDocument.objects.exists()


# ---- report contents (presentation selections) ---------------------------------------------------


def test_contents_page_saves_only_differences_and_resets(user, client):
    run = dual_run(user)
    result = run.result
    client.force_login(user)
    url = reverse("results:report_contents", args=[run.pk, "customer"])
    page = client.get(url).content.decode()
    assert "Always included" in page and "Seal face measurements" in page and "Result Draft" in page
    roundpak = FaceMeasurement.objects.filter(component__result=result, kind="roundpak", reported=True).first()
    key = f"{roundpak.component_id}:roundpak"
    picture = ResultImage.objects.filter(result=result).first()
    data = {f"slot:{key}:summary": "on", f"slot:{key}:detail": "on", f"slot:{key}:figures": ["roundpak_polar"],
            "flag:leakage_chart": "on", "flag:events_table": "on", "flag:wear_note": "on"}  # fmt: skip
    for other in ResultImage.objects.filter(result=result).exclude(pk=picture.pk):
        data[f"picture:{other.pk}"] = "on"
    for plot in ResultPlot.objects.filter(result=result):
        data[f"plot:{plot.pk}"] = "on"
    for slot in report_contents.slots(result.components.all()):  # keep the other summaries
        if slot.key != key:
            data[f"slot:{slot.key}:summary"] = "on"
    client.post(url, data)
    stored = ReportSelection.objects.get(result=result, profile="customer").data
    assert stored == {"flags": {"events_table": True},
                      "slots": {key: {"detail": True, "figures": ["roundpak_polar"]}},
                      "pictures": {str(picture.pk): False}}  # fmt: skip
    assert FaceMeasurement.objects.get(pk=roundpak.pk).reported  # selection is not evidence
    client.post(url, {"action": "reset"})
    assert not ReportSelection.objects.filter(result=result, profile="customer").exists()


def test_selection_may_change_after_final_without_touching_evidence(final, user, client):
    before = evidence_state(final)
    client.force_login(user)
    url = reverse("results:report_contents", args=[final.test_run.pk, "customer"])
    assert "Result final" in client.get(url).content.decode()
    client.post(url, {"flag:annex_manual_log": "on"})
    assert ReportSelection.objects.get(profile="customer").data["flags"]["annex_manual_log"] is True
    assert evidence_state(final) == before
    issued = final.revisions.get().documents.get()
    assert read(issued.file.name) and hashlib.sha256(read(issued.file.name)).hexdigest() == issued.sha256


def test_preview_of_each_profile(final, user, client):
    client.force_login(user)
    for profile, heading in (("customer", "Customer report"), ("engineering", "Engineering report")):
        response = client.get(reverse("results:report_profile_preview", args=[final.test_run.pk, profile]))
        text = " ".join(" ".join(pdf_lines(response.content)).split())
        assert response.status_code == 200 and "PREVIEW — not an issued document" in text and heading in text
        assert response["Content-Disposition"].endswith(f'-TestRunReport-{profile.title()}-PREVIEW.pdf"')
    assert ReportDocument.objects.count() == 1  # previews are never stored


# ---- migration of M2E finals (0008) ----------------------------------------------------------------


def test_m2e_final_becomes_revision_0_with_its_pdf_unchanged(user, file_storage):
    """An M2E final (TestResult final_* only, schema-1 snapshot) migrates to revision 0 + R0-E: the same file,
    bytes and SHA-256; the snapshot as the record; the pictures and plots frozen and checked."""
    run = dual_run(user)
    result = make_finalizable(run.result, user)
    snapshot = build_run_report_context(run, final={"by": user, "at": result.updated_at})
    snapshot.pop("schema")  # as M2E froze it
    report_assets(snapshot)  # the display copies exist, as after an M2E rendering
    pdf = b"%PDF-1.7 M2E final report bytes"
    name = f"projects/{run.project.project_no}/runs/{run.display_no}/result/2026RSD03TL-Run001-TestRunReport.pdf"
    legacy = M2EApps(m2e_final(result, user, name, pdf, hashlib.sha256(pdf).hexdigest(), snapshot, "t" * 64))
    stored = legacy.finals[0].final_document.name
    migration._finals(legacy, [])
    migration_b2.check_finals_are_recorded(legacy, None)  # 0009 may drop the M2E fields: all is recorded
    revision = ResultRevision.objects.get(result=result)
    document = revision.documents.get()
    assert (revision.number, revision.origin, revision.record_schema) == (0, "migrated", 1)
    assert records.read_record(revision) == snapshot
    assert document.identity == "2026RSD03TL-Run001-TRR-R0-E" and document.file.name == stored
    assert read(document.file.name) == pdf and document.sha256 == hashlib.sha256(pdf).hexdigest()
    assert document.template_sha256 == "t" * 64 and document.origin == "migrated"
    assert records.read_assets(revision).keys() == {a["path"] for a in snapshot["assets"]}
    customer = publication.issue(revision, "customer", user)  # a later profile from the migrated record
    assert customer.identity == "2026RSD03TL-Run001-TRR-R0-C" and read(document.file.name) == pdf


def test_migration_stops_when_the_m2e_pdf_does_not_match(user, file_storage):
    run = dual_run(user)
    result = make_finalizable(run.result, user)
    legacy = M2EApps(m2e_final(result, user, "projects/x/report.pdf", b"%PDF changed", "0" * 64, {"assets": []}))
    with pytest.raises(RuntimeError, match="does not match its SHA-256; nothing was migrated"):
        migration._finals(legacy, [])
    assert not ResultRevision.objects.exists()


def test_b2_migration_keeps_the_m2e_fields_unless_they_are_recorded(final, user):
    """0009 drops final_document / final_snapshot only when revision 0 and a stored document hold them."""
    (revision,) = final.revisions.all()
    document = revision.documents.get()
    final.final_document, final.final_document_sha256 = SimpleNamespace(name=document.file.name), document.sha256
    final.final_snapshot = records.read_record(revision)
    migration_b2.check_finals_are_recorded(M2EApps(final), None)
    final.final_snapshot = {**final.final_snapshot, "generated": "another day"}
    with pytest.raises(RuntimeError, match="not its final snapshot; nothing was migrated"):
        migration_b2.check_finals_are_recorded(M2EApps(final), None)
    final.final_snapshot, final.final_document_sha256 = records.read_record(revision), "0" * 64
    with pytest.raises(RuntimeError, match="not a stored report document; nothing was migrated"):
        migration_b2.check_finals_are_recorded(M2EApps(final), None)

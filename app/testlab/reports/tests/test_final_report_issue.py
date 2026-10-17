"""Issuing the Final Report: R0, R1, … stored once; refused while an included run is being revised."""

import pytest
from django.db import transaction
from django.urls import reverse

from testlab.documents.tests.pdf_text import pdf_lines
from testlab.reports import publication
from testlab.reports.models import FinalReport, FinalReportDocument
from testlab.results import finalization, revisions
from testlab.results.models import RecordIntegrityError, TestResult
from testlab.results.tests.test_report_publication import read

from .test_final_report import include, two_finals  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db


def text_of(document):
    return " ".join(" ".join(pdf_lines(read(document.file.name))).split())


def test_issue_stores_r0_with_what_it_was_rendered_from(user, two_finals):
    project, result1, result2 = two_finals
    report = include(project, user, result1, result2, introduction="Qualification of the wavy faces.")
    document = publication.issue(report, user)
    assert (document.identity, document.revision, document.status) == (f"{project.project_no}R-R0", 0, "issued")
    assert document.file.name == f"projects/{project.project_no}/final_report/{project.project_no}R-R0.pdf"
    assert document.sha256 == publication.records.sha256(read(document.file.name))
    assert document.texts["introduction"] == "Qualification of the wavy faces."
    assert [(run["run_no"], run["revision"]) for run in document.runs] == [("001", 0), ("002", 0)]
    text = text_of(document)
    assert "DRAFT" not in text and f"{project.project_no}R-R0" in text and "Issued" in text
    assert "Qualification of the wavy faces." in text
    assert publication.changed_since(document) == []


def test_run_sections_name_their_source_not_a_report_status(user, two_finals):
    project, result1, _ = two_finals
    text = text_of(publication.issue(include(project, user, result1), user))
    assert "Source Final Result Result revision 0" in text
    assert "Preview" not in text and "Customer report, not an issued document" not in text


def test_issuing_again_needs_a_reason_and_supersedes_the_earlier_issue(user, two_finals):
    project, result1, result2 = two_finals
    report = include(project, user, result1)
    r0 = publication.issue(report, user)
    pdf = read(r0.file.name)
    report.conclusion = "Both runs are reported."
    report.save()
    assert publication.changed_since(r0) == ["conclusion"]
    with pytest.raises(publication.PublicationError, match="give the reason"):
        publication.issue(report, user)
    r1 = publication.issue(report, user, "Conclusion added")
    r0.refresh_from_db()
    assert (r0.status, r0.superseded_by, r1.identity, r1.reason) == ("superseded", r1, f"{project.project_no}R-R1",
                                                                     "Conclusion added")  # fmt: skip
    assert read(r0.file.name) == pdf  # never rendered again
    text = text_of(r1)
    assert f"{project.project_no}R-R0 R0" in text and "Superseded" in text and "Conclusion added" not in text


def test_issue_is_refused_while_an_included_run_is_being_revised(user, two_finals):
    project, result1, result2 = two_finals
    report = include(project, user, result1, result2)
    revisions.open_revision(result1, user, "Wrong gauge")
    with pytest.raises(publication.PublicationError, match="Run 001 is in progress"):
        publication.issue(report, user)
    assert not FinalReportDocument.objects.exists()
    finalization.finalize(TestResult.objects.get(pk=result1.pk), user)
    document = publication.issue(report, user)
    assert [run["revision"] for run in document.runs] == [1, 0]


def test_a_new_result_revision_shows_as_a_change(user, two_finals):
    project, result1, _ = two_finals
    report = include(project, user, result1)
    document = publication.issue(report, user)
    finalization.finalize(revisions.open_revision(result1, user, "Wrong gauge"), user)
    assert publication.changed_since(document) == ["runs or their Result revisions"]


def test_issued_document_cannot_change_or_be_deleted(user, two_finals):
    project, result1, _ = two_finals
    document = publication.issue(include(project, user, result1), user)
    document.reason = "edited"
    with pytest.raises(RecordIntegrityError), transaction.atomic():
        document.save()
    with pytest.raises(RecordIntegrityError), transaction.atomic():
        FinalReportDocument.objects.get(pk=document.pk).delete()


def test_issue_needs_permission(user, two_finals, monkeypatch):
    project, result1, _ = two_finals
    monkeypatch.setattr("testlab.reports.publication.can_issue_report", lambda u: False)
    with pytest.raises(publication.PublicationError, match="not allowed"):
        publication.issue(include(project, user, result1), user)


def test_page_issues_lists_and_serves_the_documents(client, user, two_finals):
    project, result1, _ = two_finals
    include(project, user, result1)
    client.force_login(user)
    page = reverse("reports:final_report", args=[project.pk])
    assert "Not issued yet" in client.get(page).content.decode()
    response = client.post(reverse("reports:issue", args=[project.pk]), follow=True)
    assert f"{project.project_no}R-R0 issued." in response.content.decode()
    document = FinalReportDocument.objects.get()
    download = client.get(reverse("reports:document", args=[project.pk, document.pk]))
    assert download.content == read(document.file.name)
    assert f'filename="{project.project_no}R-R0.pdf"' in download["Content-Disposition"]
    response = client.post(reverse("reports:issue", args=[project.pk]), follow=True)
    assert "give the reason" in response.content.decode() and FinalReportDocument.objects.count() == 1
    assert f"Reason for issuing {project.project_no}R-R1" in client.get(page).content.decode()


def test_page_explains_why_it_cannot_issue_while_a_run_is_revised(client, user, two_finals):
    project, result1, _ = two_finals
    include(project, user, result1)
    revisions.open_revision(result1, user, "Wrong gauge")
    client.force_login(user)
    page = client.get(reverse("reports:final_report", args=[project.pk])).content.decode()
    assert "Result of Run 001 is in progress" in page and "Issue " not in page
    assert FinalReport.objects.get(project=project).documents.count() == 0

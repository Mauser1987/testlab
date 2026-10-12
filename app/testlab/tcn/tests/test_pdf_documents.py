"""The controlled TCN document is a PDF (stabilization decision S1).

Preview, issue, download and the revision/supersede/cancel history all use
the PDF; it is rendered from the TCN document template and never served
in another format. Most tests use the fast stand-in for Chromium's printing
(conftest.py); the lifecycle test at the end prints real PDFs.
"""

import hashlib

import pytest
from django.urls import reverse

from testlab.documents import pdf
from testlab.documents.render import ChromiumTemplate
from testlab.documents.tests.pdf_text import is_real_pdf, pdf_lines
from testlab.tcn.models import TcnRevision
from testlab.tcn.services import IssueError, cancel_tcn, create_revision, issue_tcn

from .factories import issue as model_issue
from .factories import make_project
from .test_issue import issue, ready_tcn, stored_bytes
from .test_views import edit_url, messages_of

pytestmark = pytest.mark.django_db

Status = TcnRevision.Status
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def stored_files(file_storage):
    return sorted(path.relative_to(file_storage).as_posix() for path in file_storage.rglob("*") if path.is_file())


def document(client, tcn):
    response = client.get(reverse("tcn:document", args=[tcn.pk]))
    return response, b"".join(response.streaming_content) if response.status_code == 200 else b""


def fail_conversion(monkeypatch):
    def failing(template, context):
        raise pdf.PdfConversionError("The PDF could not be rendered: font missing.")

    monkeypatch.setattr(ChromiumTemplate, "render_pdf", failing)


# --- Preview ---------------------------------------------------------------------------------


def test_preview_returns_pdf(logged_in, project, user):
    tcn = ready_tcn(project, user)
    response = logged_in.get(reverse("tcn:preview", args=[tcn.pk]))
    assert response["Content-Type"] == "application/pdf" and response.content.startswith(b"%PDF-")
    assert "DRAFT — not issued" in pdf_lines(response.content)


def test_preview_conversion_failure_returns_to_draft_with_message(logged_in, project, user, monkeypatch):
    tcn = ready_tcn(project, user)
    fail_conversion(monkeypatch)
    response = logged_in.get(reverse("tcn:preview", args=[tcn.pk]))
    assert response.status_code == 302 and response["Location"] == edit_url(tcn)
    assert messages_of(response)[0].startswith("The PDF preview could not be generated.")


# --- Issue -----------------------------------------------------------------------------------


def test_issue_stores_pdf_and_its_hash(project, user, file_storage):
    tcn = issue(ready_tcn(project, user), user)
    assert stored_files(file_storage) == ["projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.pdf"]  # no DOCX
    on_disk = (file_storage / tcn.issued_document.name).read_bytes()
    assert on_disk.startswith(b"%PDF-")
    assert tcn.issued_document_sha256 == hashlib.sha256(on_disk).hexdigest()


def test_failed_pdf_conversion_leaves_the_tcn_draft(project, user, file_storage, monkeypatch):
    tcn = ready_tcn(project, user)
    before = TcnRevision.objects.filter(pk=tcn.pk).values().get()
    fail_conversion(monkeypatch)
    with pytest.raises(IssueError, match="The PDF could not be generated; nothing was issued."):
        issue_tcn(tcn, tcn.row_version, user)
    assert TcnRevision.objects.filter(pk=tcn.pk).values().get() == before  # still draft, same row version
    assert stored_files(file_storage) == []


def test_failed_pdf_conversion_does_not_supersede(project, user, file_storage, monkeypatch):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = create_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    fail_conversion(monkeypatch)
    with pytest.raises(IssueError):
        issue(TcnRevision.objects.get(pk=rev_1.pk), user)
    statuses = list(TcnRevision.objects.order_by("revision").values_list("status", flat=True))
    assert statuses == [Status.ISSUED, Status.DRAFT]
    assert stored_files(file_storage) == ["projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.pdf"]


def test_issue_screen_shows_conversion_failure(logged_in, project, user, monkeypatch):
    tcn = ready_tcn(project, user)
    fail_conversion(monkeypatch)
    response = logged_in.post(reverse("tcn:issue", args=[tcn.pk]), {"row_version": tcn.row_version})
    assert response.status_code == 200
    assert "The PDF could not be generated; nothing was issued." in response.content.decode()
    assert TcnRevision.objects.get(pk=tcn.pk).status == Status.DRAFT


# --- Download: PDF only ---------------------------------------------------------------------


def test_issued_download_returns_pdf(logged_in, project, user):
    tcn = issue(ready_tcn(project, user), user)
    response, content = document(logged_in, tcn)
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="2026RSD03TL-TCN001.pdf"'
    assert content == stored_bytes(tcn) and content.startswith(b"%PDF-")


def test_no_docx_is_exposed(logged_in, project, user, file_storage):
    tcn = ready_tcn(project, user)
    preview = logged_in.get(reverse("tcn:preview", args=[tcn.pk]))
    tcn = issue(TcnRevision.objects.get(pk=tcn.pk), user)
    response, _ = document(logged_in, tcn)
    for served in (preview, response):
        assert served["Content-Type"] != DOCX_CONTENT_TYPE and ".docx" not in served["Content-Disposition"]
    assert not [name for name in stored_files(file_storage) if not name.endswith(".pdf")]
    for page in [edit_url(tcn), reverse("projects:detail", args=[project.pk])]:
        assert "DOCX" not in logged_in.get(page).content.decode()


def test_a_stored_non_pdf_is_never_served(logged_in, project, user, file_storage):
    # A record pointing to a DOCX (e.g. one issued before the PDF decision) offers no download.
    tcn = ready_tcn(project, user)
    name = "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.docx"
    (file_storage / name).parent.mkdir(parents=True)
    (file_storage / name).write_bytes(b"PK docx")
    tcn.issued_document.name = name
    model_issue(tcn, user)  # directly on the model, bypassing the issue service
    response, _ = document(logged_in, tcn)
    assert response.status_code == 404


# --- History: every revision keeps and serves its own issued PDF -----------------------------


def test_supersede_and_cancel_keep_serving_each_issued_pdf(logged_in, project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_0_pdf = stored_bytes(rev_0)
    rev_1 = create_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    rev_1 = issue(TcnRevision.objects.get(pk=rev_1.pk), user)
    rev_1 = cancel_tcn(rev_1, "Rig not available", user)

    rev_0, rev_1 = TcnRevision.objects.get(pk=rev_0.pk), TcnRevision.objects.get(pk=rev_1.pk)
    assert (rev_0.status, rev_1.status) == (Status.SUPERSEDED, Status.CANCELLED)
    for tcn, name, speed in [(rev_0, "2026RSD03TL-TCN001.pdf", "2980"), (rev_1, "2026RSD03TL-TCN001-rev1.pdf", "1500")]:
        response, content = document(logged_in, tcn)
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == f'attachment; filename="{name}"'
        assert hashlib.sha256(content).hexdigest() == tcn.issued_document_sha256
        assert f"Speed: {speed} rpm" in pdf_lines(content)
    assert stored_bytes(rev_0) == rev_0_pdf


# --- Real PDFs through the whole lifecycle ----------------------------------------------------


@pytest.mark.chromium
def test_real_pdf_issue_supersede_cancel_and_download(logged_in, project, user, file_storage):
    rev_0 = ready_tcn(project, user)
    preview = logged_in.get(reverse("tcn:preview", args=[rev_0.pk]))
    assert is_real_pdf(preview.content) and "DRAFT — not issued" in " ".join(pdf_lines(preview.content))

    rev_0 = issue(rev_0, user)
    rev_0_pdf = (file_storage / rev_0.issued_document.name).read_bytes()
    assert is_real_pdf(rev_0_pdf) and rev_0.issued_document_sha256 == hashlib.sha256(rev_0_pdf).hexdigest()
    text = " ".join(pdf_lines(rev_0_pdf))
    assert "Run/TCN No.: 001" in text and "Speed: 2980 rpm" in text and "DRAFT" not in text

    rev_1 = create_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    rev_1 = issue(TcnRevision.objects.get(pk=rev_1.pk), user)
    rev_1 = cancel_tcn(rev_1, "Rig not available", user)
    assert "Run/TCN No.: 001 rev 1" in " ".join(pdf_lines(stored_bytes(rev_1)))

    for tcn in [TcnRevision.objects.get(pk=rev_0.pk), TcnRevision.objects.get(pk=rev_1.pk)]:
        response, content = document(logged_in, tcn)
        assert response["Content-Type"] == "application/pdf" and is_real_pdf(content)
        assert hashlib.sha256(content).hexdigest() == tcn.issued_document_sha256
    assert (file_storage / rev_0.issued_document.name).read_bytes() == rev_0_pdf
    assert stored_files(file_storage) == [
        "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001-rev1.pdf",
        "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001.pdf",
    ]

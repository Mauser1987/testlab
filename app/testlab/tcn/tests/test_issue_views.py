"""S8 issue confirmation, S9 read-only view, download (M1 spec §6); AT-4."""

import hashlib

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from testlab.documents.tests.pdf_text import pdf_lines
from testlab.projects.arrangements import Arrangement
from testlab.projects.models import Project
from testlab.projects.tests.test_defaults_form import post_data
from testlab.tcn.models import TcnRevision

from .factories import make_project, new_revision
from .test_issue import issue, ready_tcn, stored_bytes
from .test_views import edit_data, edit_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def issue_url(tcn):
    return reverse("tcn:issue", args=[tcn.pk])


def document_url(tcn):
    return reverse("tcn:document", args=[tcn.pk])


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# --- S8 -------------------------------------------------------------------------------


def test_s8_lists_issue_errors_without_confirm(logged_in, project, user):
    tcn = TcnRevision.objects.get(pk=ready_tcn(project, user).pk)
    tcn.setup.test_unit = ""
    tcn.setup.save()
    content = logged_in.get(issue_url(tcn)).content.decode()
    assert "cannot be issued yet" in content and "Test unit is required." in content
    assert "Confirm issue" not in content


def test_s8_summary_changes_and_notice(logged_in, project, user):
    source = issue(ready_tcn(project, user), user)
    copy_response = logged_in.post(
        reverse("tcn:create", args=[project.pk]), {"run_no": "2", "source_type": "copy", "source": source.pk}
    )
    copy = TcnRevision.objects.get(test_run__run_no=2)
    assert copy_response["Location"] == edit_url(copy)
    logged_in.post(edit_url(copy), edit_data(copy, speed="1500"))

    content = logged_in.get(issue_url(copy)).content.decode()
    assert "An issued TCN cannot be changed; changes require a new revision." in content
    assert "1 difference from TCN001" in content
    assert "Confirm issue" in content and 'name="row_version" value="2"' in content
    assert "Maria Geerts (you)" in content


def test_confirm_issue(logged_in, project, user):
    tcn = ready_tcn(project, user)
    response = logged_in.post(issue_url(tcn), {"row_version": tcn.row_version})
    assert response.status_code == 302 and response["Location"] == edit_url(tcn)
    assert messages_of(response) == ["TCN001 issued."]
    tcn.refresh_from_db()
    assert (tcn.status, tcn.issued_by) == (TcnRevision.Status.ISSUED, user)


def test_confirm_after_someone_saved_is_refused(client, project, user, other_user):
    tcn = ready_tcn(project, user)
    client.force_login(other_user)
    client.post(edit_url(tcn), edit_data(tcn, speed="1500"))  # saved after the review page was opened
    client.force_login(user)
    response = client.post(issue_url(tcn), {"row_version": 1})
    assert response.status_code == 200
    assert "was changed by Mark Test" in response.content.decode()
    assert 'name="row_version" value="2"' in response.content.decode()  # review again, then confirm
    assert TcnRevision.objects.get(pk=tcn.pk).status == TcnRevision.Status.DRAFT


def test_confirm_with_issue_errors_shows_them(logged_in, project, user):
    tcn = TcnRevision.objects.get(pk=ready_tcn(project, user).pk)
    tcn.prepared_by = ""
    tcn.save()
    response = logged_in.post(issue_url(tcn), {"row_version": tcn.row_version})
    assert "Prepared by is required." in response.content.decode()
    assert TcnRevision.objects.get(pk=tcn.pk).status == TcnRevision.Status.DRAFT


def test_issue_page_of_issued_tcn_redirects_to_view(logged_in, project, user):
    tcn = issue(ready_tcn(project, user), user)
    for response in [logged_in.get(issue_url(tcn)), logged_in.post(issue_url(tcn), {"row_version": 2})]:
        assert response.status_code == 302 and response["Location"] == edit_url(tcn)


def test_edit_page_links_issue(logged_in, project, user):
    tcn = ready_tcn(project, user)
    assert issue_url(tcn) in logged_in.get(edit_url(tcn)).content.decode()


# --- S9 and download -----------------------------------------------------------------------


def test_s9_shows_issued_snapshot_and_history(logged_in, project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = new_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    rev_1 = issue(TcnRevision.objects.get(pk=rev_1.pk), user)

    response = logged_in.get(edit_url(rev_0))
    content = response.content.decode()
    assert "SUPERSEDED" in content and "Superseded by" in content and "TCN001 rev 1" in content
    assert "2980 rpm" in content and "1500 rpm" not in content  # rev 0's issued content
    assert "Speed changed" in content  # history: rev 1's reason
    assert content.count(document_url(rev_0)) >= 1 and document_url(rev_1) in content
    assert f"?source={rev_0.pk}" in content  # Copy to new TCN
    assert 'name="action"' not in content

    content = logged_in.get(edit_url(rev_1)).content.decode()
    assert "An issued TCN cannot be changed" in content and "1500 rpm" in content


def test_download_serves_the_stored_file(logged_in, project, user, file_storage):
    tcn = issue(ready_tcn(project, user), user)
    response = logged_in.get(document_url(tcn))
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="2026RSD03TL-TCN001.pdf"'
    assert b"".join(response.streaming_content) == stored_bytes(tcn)

    # Never regenerated: a missing file is an error, not a new render.
    (file_storage / tcn.issued_document.name).unlink()
    assert logged_in.get(document_url(tcn)).status_code == 404


def test_no_download_for_drafts(logged_in, project, user):
    assert logged_in.get(document_url(ready_tcn(project, user))).status_code == 404


def test_register_offers_download_of_issued_tcn(logged_in, project, user):
    tcn = issue(ready_tcn(project, user), user)
    ready_tcn(project, user, run_no=2)
    content = logged_in.get(reverse("projects:detail", args=[project.pk])).content.decode()
    assert content.count("Download PDF") == 1 and document_url(tcn) in content


# --- AT-4: M1 success criteria 1–10 -----------------------------------------------------------


def test_at4_m1_success_criteria(logged_in, user):
    # 1. Create a project.
    response = logged_in.post(
        reverse("projects:create"), {"project_no": "2099RSD01TL", "description": "TEST UHTW 4.750", "customer": ""}
    )
    project = Project.objects.get(project_no="2099RSD01TL")
    assert response["Location"] == reverse("projects:defaults", args=[project.pk])

    # 2 + 4. Project defaults: seal information, Plug Seal toggled on (and its data).
    defaults = project.default_setup
    data = post_data(
        defaults,
        plug_seal_present=True,
        reference_drawing="F00321662",
        **{"inboard-seal_type_size": "UHTW 4.750", "outboard-seal_type_size": "UHTW 4.750"},
    )
    data.update({"plug-seal_type_size": "DHTW 4.750", "plug_medium": "Water"})
    assert logged_in.post(reverse("projects:defaults", args=[project.pk]), data).status_code == 302
    defaults.refresh_from_db()
    assert defaults.plug_seal_present and sorted(defaults.positions.values_list("role", flat=True)) == [
        "inboard", "outboard", "plug",
    ]  # fmt: skip

    # 3. TCN001 from the project defaults.
    logged_in.post(reverse("tcn:create", args=[project.pk]), {"run_no": "1", "source_type": "defaults"})
    tcn001 = TcnRevision.objects.get(test_run__run_no=1)

    # 5. Conditions and instructions.
    response = logged_in.post(
        edit_url(tcn001),
        edit_data(
            tcn001,
            run_description="• Start Test Unit\n   - measure torque",
            test_unit="B",
            speed="2980",
            duration="min 75",
            seal_support_medium="Water",
            seal_support_pressure="70",
        ),
    )
    assert response.status_code == 302

    # 6. Generate (preview) the TCN document.
    preview = pdf_lines(logged_in.get(reverse("tcn:preview", args=[tcn001.pk])).content)
    assert "DRAFT — not issued" in preview and "Plug Seal Inboard Seal Outboard Seal" in preview

    # 7. Issue / lock.
    tcn001.refresh_from_db()
    logged_in.post(issue_url(tcn001), {"row_version": tcn001.row_version})
    tcn001 = TcnRevision.objects.get(pk=tcn001.pk)
    assert tcn001.status == TcnRevision.Status.ISSUED
    record = TcnRevision.objects.filter(pk=tcn001.pk).values().get()
    file_hash = hashlib.sha256(stored_bytes(tcn001)).hexdigest()
    assert file_hash == tcn001.issued_document_sha256

    # 8. TCN002 by copying TCN001 (proposed source).
    form = logged_in.get(reverse("tcn:create", args=[project.pk])).context["form"]
    assert form.initial["source"] == tcn001
    copy_data = {"run_no": "2", "source_type": "copy", "source": tcn001.pk}
    logged_in.post(reverse("tcn:create", args=[project.pk]), copy_data)
    tcn002 = TcnRevision.objects.get(test_run__run_no=2)

    # 9. Change only what differs.
    logged_in.post(edit_url(tcn002), edit_data(tcn002, speed="1500"))
    tcn002.refresh_from_db()
    assert [change.key for change in logged_in.get(issue_url(tcn002)).context["change_list"]] == ["speed"]

    # 10. Issue TCN002 without affecting TCN001.
    logged_in.post(issue_url(tcn002), {"row_version": tcn002.row_version})
    tcn002 = TcnRevision.objects.get(pk=tcn002.pk)
    assert tcn002.status == TcnRevision.Status.ISSUED
    assert "Speed: 1500 rpm" in pdf_lines(stored_bytes(tcn002))

    tcn001 = TcnRevision.objects.get(pk=tcn001.pk)
    assert TcnRevision.objects.filter(pk=tcn001.pk).values().get() == record
    assert hashlib.sha256(stored_bytes(tcn001)).hexdigest() == file_hash
    assert tcn001.issued_snapshot["speed"] == "2980 rpm"
    assert "Speed: 2980 rpm" in pdf_lines(stored_bytes(tcn001))

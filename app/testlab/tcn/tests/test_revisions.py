"""New revision, cancel, delete draft (M1 spec §4, §6 S7/S9/S10, V13, V14): AT-7."""

import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from testlab.documents.tests.pdf_text import pdf_lines
from testlab.projects.models import RunSetup
from testlab.tcn.models import ImmutableTcnError, TcnRevision, TcnRuleError, TestRun
from testlab.tcn.services import (
    IssueError,
    StaleDraftError,
    cancel_tcn,
    create_revision,
    create_tcn,
    delete_draft,
)

from .factories import cancel, make_project
from .test_issue import issue, ready_tcn, stored_bytes
from .test_views import edit_data, edit_url, messages_of

pytestmark = pytest.mark.django_db

Status = TcnRevision.Status


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def reload(tcn):
    return TcnRevision.objects.get(pk=tcn.pk)


# --- New revision (§4, V13) ------------------------------------------------------------------


def test_new_revision_is_an_independent_draft_copy(project, user, other_user):
    rev_0 = issue(ready_tcn(project, user, reference_drawing="F00321662"), user)
    record = TcnRevision.objects.filter(pk=rev_0.pk).values().get()
    project.description = "Changed later"
    project.save()

    rev_1 = create_revision(rev_0, other_user)
    assert (rev_1.revision, rev_1.status, rev_1.test_run_id) == (1, Status.DRAFT, rev_0.test_run_id)
    assert (rev_1.source_kind, rev_1.source_tcn) == (TcnRevision.SourceKind.NEW_REVISION, rev_0)
    assert rev_1.project_description == "ADNOC BAB UHTW/UHTW 4.750/4.750"  # from the revision, not the project
    assert rev_1.prepared_by == "MT"  # the user making the revision
    assert rev_1.revision_reason == "" and rev_1.issued_at is None
    assert rev_1.setup_id != rev_0.setup_id and rev_1.setup.reference_drawing == "F00321662"
    assert sorted(rev_1.setup.positions.values_list("seal_type_size", flat=True)) == ["UHTW 4.750"] * 2
    assert rev_1.tcn_no == "001 rev 1"

    rev_1.setup.speed = "1500"
    rev_1.setup.save()
    assert TcnRevision.objects.filter(pk=rev_0.pk).values().get() == record  # untouched until rev 1 is issued
    assert reload(rev_0).setup.speed == "2980"


def test_new_revision_only_from_current_issued_revision(project, user):
    draft = ready_tcn(project, user)
    with pytest.raises(TcnRuleError, match="not the current issued revision"):
        create_revision(draft, user)

    rev_0 = issue(draft, user)
    rev_1 = create_revision(rev_0, user)
    with pytest.raises(TcnRuleError, match="TCN001 rev 1 is already in preparation"):
        create_revision(rev_0, user)  # V13: one draft at a time

    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    issue(reload(rev_1), user)
    with pytest.raises(TcnRuleError, match="not the current issued revision"):
        create_revision(reload(rev_0), user)  # superseded
    assert create_revision(reload(rev_1), user).revision == 2


def test_no_new_revision_of_a_cancelled_run(project, user):
    tcn = cancel_tcn(issue(ready_tcn(project, user), user), "Test cancelled by customer", user)
    with pytest.raises(TcnRuleError, match="cancelled; it cannot be revised"):
        create_revision(tcn, user)
    assert tcn.test_run.revisions.count() == 1


# --- Cancel (V14) ----------------------------------------------------------------------------


def test_cancel_keeps_record_and_document(project, user, other_user):
    tcn = issue(ready_tcn(project, user), user)
    content = stored_bytes(tcn)
    snapshot = tcn.issued_snapshot

    tcn = cancel_tcn(tcn, "  Customer withdrew the test  ", other_user)
    tcn = reload(tcn)
    assert tcn.status == Status.CANCELLED
    assert (tcn.cancel_reason, tcn.cancelled_by) == ("Customer withdrew the test", other_user)
    assert tcn.cancelled_at is not None
    assert (tcn.issued_by, tcn.issued_snapshot) == (user, snapshot)
    assert stored_bytes(tcn) == content and tcn.issued_document_sha256 == hashlib.sha256(content).hexdigest()
    with pytest.raises(ImmutableTcnError):
        tcn.delete()


@pytest.mark.parametrize("reason", ["", "   "])
def test_cancel_requires_a_reason(project, user, reason):
    tcn = issue(ready_tcn(project, user), user)
    with pytest.raises(ValidationError):
        cancel_tcn(tcn, reason, user)
    assert reload(tcn).status == Status.ISSUED


def test_cancel_only_the_current_issued_revision(project, user):
    draft = ready_tcn(project, user)
    with pytest.raises(TcnRuleError, match="only that one can be cancelled"):
        cancel_tcn(draft, "Reason", user)

    rev_0 = issue(draft, user)
    rev_1 = create_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    issue(reload(rev_1), user)
    with pytest.raises(TcnRuleError, match="only that one can be cancelled"):
        cancel_tcn(reload(rev_0), "Reason", user)  # superseded
    cancel_tcn(reload(rev_1), "Reason", user)
    with pytest.raises(TcnRuleError):
        cancel_tcn(reload(rev_1), "Again", user)


def test_cancel_refused_while_a_draft_revision_is_pending(project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = create_revision(rev_0, user)
    with pytest.raises(TcnRuleError, match="delete that draft before cancelling"):
        cancel_tcn(rev_0, "Reason", user)
    delete_draft(rev_1, rev_1.row_version, user)
    assert cancel_tcn(reload(rev_0), "Reason", user).status == Status.CANCELLED


def test_draft_of_a_cancelled_run_cannot_be_issued(project, user, file_storage):
    # Not reachable through the services (cancel refuses while a draft is pending); backstop.
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = create_revision(rev_0, user)
    rev_1.revision_reason = "Speed changed"
    rev_1.save()
    cancel(reload(rev_0), user)
    with pytest.raises(IssueError, match="has been cancelled"):
        issue(reload(rev_1), user)
    assert reload(rev_1).status == Status.DRAFT
    assert not (file_storage / "projects/2026RSD03TL/tcn/2026RSD03TL-TCN001-rev1.pdf").exists()


def test_cancelled_tcn_can_still_be_copied(project, user):
    tcn = cancel_tcn(issue(ready_tcn(project, user), user), "Reason", user)
    copy = create_tcn(project, 2, user, source=tcn)
    assert copy.source_tcn == tcn and copy.setup.speed == "2980"


# --- Delete draft (§4) ------------------------------------------------------------------------


def test_delete_draft_rev_0_removes_the_run(project, user):
    tcn = ready_tcn(project, user)
    setup_id = tcn.setup_id
    delete_draft(tcn, tcn.row_version, user)
    assert not TestRun.objects.filter(project=project).exists()
    assert not RunSetup.objects.filter(pk=setup_id).exists()
    assert create_tcn(project, 1, user).tcn_no == "001"  # run number free again


def test_delete_draft_revision_keeps_issued_revision(project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    record = TcnRevision.objects.filter(pk=rev_0.pk).values().get()
    rev_1 = create_revision(rev_0, user)
    delete_draft(rev_1, rev_1.row_version, user)
    assert list(rev_0.test_run.revisions.all()) == [rev_0]
    assert TcnRevision.objects.filter(pk=rev_0.pk).values().get() == record
    assert create_revision(rev_0, user).revision == 1  # the number is reused: rev 1 left no trace


def test_delete_refused_for_issued_tcn(project, user):
    tcn = issue(ready_tcn(project, user), user)
    with pytest.raises(ImmutableTcnError):
        delete_draft(tcn, tcn.row_version, user)
    assert reload(tcn).status == Status.ISSUED


def test_delete_refused_when_draft_changed_since_review(project, user):
    tcn = ready_tcn(project, user)
    TcnRevision.objects.filter(pk=tcn.pk).update(row_version=2)  # saved by someone else
    with pytest.raises(StaleDraftError):
        delete_draft(tcn, 1, user)
    assert TcnRevision.objects.filter(pk=tcn.pk).exists()


def test_delete_refused_for_a_copy_source(project, user):
    source = ready_tcn(project, user)
    create_tcn(project, 2, user, source=source)
    with pytest.raises(TcnRuleError, match="TCN002 was copied from it"):
        delete_draft(source, source.row_version, user)
    assert reload(source).row_version == source.row_version  # nothing changed


# --- AT-7: revision through the screens ------------------------------------------------------------


def test_at7_revision_of_tcn002(logged_in, project, user):
    tcn001 = issue(ready_tcn(project, user), user)
    logged_in.post(reverse("tcn:create", args=[project.pk]), {"run_no": "2", "source_type": "copy", "source": tcn001.pk})
    rev_0 = TcnRevision.objects.get(test_run__run_no=2)
    logged_in.post(reverse("tcn:issue", args=[rev_0.pk]), {"row_version": rev_0.row_version})
    rev_0 = reload(rev_0)
    rev_0_file = stored_bytes(rev_0)

    # S9 → New revision → draft rev 1.
    content = logged_in.get(edit_url(rev_0)).content.decode()
    assert reverse("tcn:new_revision", args=[rev_0.pk]) in content and "Cancel TCN" in content
    response = logged_in.post(reverse("tcn:new_revision", args=[rev_0.pk]))
    rev_1 = TcnRevision.objects.get(test_run=rev_0.test_run, revision=1)
    assert response["Location"] == edit_url(rev_1)
    assert messages_of(response) == ["TCN002 rev 1 created as draft (new revision of TCN002)."]
    content = logged_in.get(edit_url(rev_1)).content.decode()
    assert "new revision of TCN002" in content and 'name="revision_reason"' in content

    # Edit; a reason is required to issue.
    logged_in.post(edit_url(rev_1), edit_data(rev_1, speed="1500"))
    rev_1 = reload(rev_1)
    response = logged_in.post(reverse("tcn:issue", args=[rev_1.pk]), {"row_version": rev_1.row_version})
    assert "Reason for revision is required." in response.content.decode()
    assert reload(rev_1).status == Status.DRAFT

    data = edit_data(rev_1)
    data["revision_reason"] = "Speed reduced on customer request"
    logged_in.post(edit_url(rev_1), data)
    rev_1 = reload(rev_1)
    assert [c.key for c in logged_in.get(reverse("tcn:issue", args=[rev_1.pk])).context["change_list"]] == ["speed"]
    logged_in.post(reverse("tcn:issue", args=[rev_1.pk]), {"row_version": rev_1.row_version})

    rev_0, rev_1 = reload(rev_0), reload(rev_1)
    assert (rev_0.status, rev_1.status) == (Status.SUPERSEDED, Status.ISSUED)
    lines = pdf_lines(stored_bytes(rev_1))
    assert "Run/TCN No.: 002 rev 1" in " ".join(lines) and "Speed: 1500 rpm" in lines

    # Both documents downloadable; rev 0's unchanged.
    for tcn, name in [(rev_0, "2026RSD03TL-TCN002.pdf"), (rev_1, "2026RSD03TL-TCN002-rev1.pdf")]:
        response = logged_in.get(reverse("tcn:document", args=[tcn.pk]))
        assert response["Content-Disposition"] == f'attachment; filename="{name}"'
        assert b"".join(response.streaming_content) == stored_bytes(tcn)
    assert stored_bytes(rev_0) == rev_0_file

    # Superseded: no revise/cancel; history lists both.
    content = logged_in.get(edit_url(rev_0)).content.decode()
    assert reverse("tcn:new_revision", args=[rev_0.pk]) not in content and "Cancel TCN" not in content
    assert "Speed reduced on customer request" in content
    register = logged_in.get(reverse("projects:detail", args=[project.pk])).context["register"]
    assert [row["tcn"] for row in register] == [tcn001, rev_1]


# --- S9 / S10 / delete screens --------------------------------------------------------------------


def test_s9_links_pending_draft_instead_of_new_revision(logged_in, project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = create_revision(rev_0, user)
    content = logged_in.get(edit_url(rev_0)).content.decode()
    assert reverse("tcn:new_revision", args=[rev_0.pk]) not in content
    assert "Open draft TCN001 rev 1" in content and edit_url(rev_1) in content
    assert "Cancel TCN" not in content

    response = logged_in.post(reverse("tcn:new_revision", args=[rev_0.pk]))
    assert response["Location"] == edit_url(rev_0)
    assert messages_of(response) == ["TCN001 rev 1 is already in preparation as a draft."]


def test_new_revision_requires_post(logged_in, project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    assert logged_in.get(reverse("tcn:new_revision", args=[rev_0.pk])).status_code == 405
    assert rev_0.test_run.revisions.count() == 1


def test_s10_cancel(logged_in, project, user):
    tcn = issue(ready_tcn(project, user), user)
    url = reverse("tcn:cancel", args=[tcn.pk])
    assert "Reason for cancelling" in logged_in.get(url).content.decode()

    response = logged_in.post(url, {"reason": "  "})
    assert response.status_code == 200 and "This field is required." in response.content.decode()
    assert reload(tcn).status == Status.ISSUED

    response = logged_in.post(url, {"reason": "Rig not available"})
    assert response["Location"] == edit_url(tcn) and messages_of(response) == ["TCN001 cancelled."]
    content = logged_in.get(edit_url(tcn)).content.decode()
    assert "CANCELLED" in content and "Rig not available" in content
    assert reverse("tcn:new_revision", args=[tcn.pk]) not in content and "Cancel TCN" not in content
    assert reverse("tcn:document", args=[tcn.pk]) in content and f"?source={tcn.pk}" in content

    content = logged_in.get(reverse("projects:detail", args=[project.pk])).content.decode()
    assert "Cancelled" in content and reverse("tcn:document", args=[tcn.pk]) in content

    response = logged_in.get(url)  # already cancelled
    assert response["Location"] == edit_url(tcn)


def test_cancel_page_of_draft_redirects(logged_in, project, user):
    tcn = ready_tcn(project, user)
    for response in [logged_in.get(reverse("tcn:cancel", args=[tcn.pk])),
                     logged_in.post(reverse("tcn:cancel", args=[tcn.pk]), {"reason": "x"})]:  # fmt: skip
        assert response["Location"] == edit_url(tcn)
    assert reload(tcn).status == Status.DRAFT


def test_delete_draft_rev_0_through_the_screen(logged_in, project, user):
    tcn = ready_tcn(project, user)
    url = reverse("tcn:delete", args=[tcn.pk])
    assert url in logged_in.get(edit_url(tcn)).content.decode()
    content = logged_in.get(url).content.decode()
    assert "Run 001 are deleted" in content and 'name="row_version" value="1"' in content

    response = logged_in.post(url, {"row_version": tcn.row_version})
    assert response["Location"] == reverse("projects:detail", args=[project.pk])
    assert messages_of(response) == ["Draft TCN001 deleted."]
    assert not TestRun.objects.exists()


def test_delete_draft_revision_through_the_screen(logged_in, project, user):
    rev_0 = issue(ready_tcn(project, user), user)
    rev_1 = create_revision(rev_0, user)
    response = logged_in.post(reverse("tcn:delete", args=[rev_1.pk]), {"row_version": rev_1.row_version})
    assert response["Location"] == edit_url(rev_0)
    assert messages_of(response) == ["Draft TCN001 rev 1 deleted."]
    assert list(TcnRevision.objects.all()) == [rev_0]


def test_delete_screen_refusals(client, project, user, other_user):
    tcn = ready_tcn(project, user)
    create_tcn(project, 2, user, source=tcn)
    client.force_login(user)
    response = client.post(reverse("tcn:delete", args=[tcn.pk]), {"row_version": tcn.row_version})
    assert response.status_code == 200 and "TCN002 was copied from it" in response.content.decode()

    other = TcnRevision.objects.get(test_run__run_no=2)
    client.force_login(other_user)
    client.post(edit_url(other), edit_data(other, speed="1500"))
    client.force_login(user)
    response = client.post(reverse("tcn:delete", args=[other.pk]), {"row_version": 1})
    assert "was changed by Mark Test" in response.content.decode()
    assert TcnRevision.objects.filter(pk=other.pk).exists()

    issued = issue(reload(other), user)
    for response in [client.get(reverse("tcn:delete", args=[issued.pk])),
                     client.post(reverse("tcn:delete", args=[issued.pk]), {"row_version": issued.row_version})]:  # fmt: skip
        assert response["Location"] == edit_url(issued)
    assert reload(issued).status == Status.ISSUED

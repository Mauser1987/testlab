"""Authorization groundwork (stabilization decision S3): controlled TCN actions go through
tcn/permissions.py. M1: every active logged-in user may issue and cancel."""

import pytest
from django.urls import reverse

from testlab.tcn import permissions, views
from testlab.tcn.models import TcnRevision

from .factories import make_project
from .test_issue import issue, ready_tcn

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL")


def test_m1_every_active_user_may_issue_and_cancel(user, other_user):
    for person in (user, other_user):
        assert permissions.can_issue_tcn(person) and permissions.can_cancel_tcn(person)
    other_user.is_active = False
    assert not permissions.can_issue_tcn(other_user)


def test_views_use_the_permission_functions(client, project, user, monkeypatch):
    draft = ready_tcn(project, user)
    issued = issue(ready_tcn(project, user, run_no=2), user)
    client.force_login(user)
    monkeypatch.setattr(views, "can_issue_tcn", lambda u: False)
    monkeypatch.setattr(views, "can_cancel_tcn", lambda u: False)

    assert reverse("tcn:issue", args=[draft.pk]) not in client.get(reverse("tcn:edit", args=[draft.pk])).content.decode()
    assert client.get(reverse("tcn:issue", args=[draft.pk])).status_code == 403
    assert client.post(reverse("tcn:issue", args=[draft.pk]), {"row_version": 1}).status_code == 403
    assert "Cancel TCN" not in client.get(reverse("tcn:edit", args=[issued.pk])).content.decode()
    assert client.post(reverse("tcn:cancel", args=[issued.pk]), {"reason": "x"}).status_code == 403
    statuses = TcnRevision.objects.order_by("test_run__run_no").values_list("status", flat=True)
    assert list(statuses) == [TcnRevision.Status.DRAFT, TcnRevision.Status.ISSUED]

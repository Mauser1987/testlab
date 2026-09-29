"""S4 register, S6 new TCN, S7 draft edit (M1 spec §6, §7); AT-8, AT-14."""

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from testlab.documents.tests.pdf_text import pdf_lines
from testlab.projects.arrangements import Arrangement
from testlab.projects.tests.test_defaults_form import post_data
from testlab.tcn.models import TcnRevision, TestRun
from testlab.tcn.services import create_tcn

from .factories import issue, make_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(user):
    return make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def new_url(project):
    return reverse("tcn:create", args=[project.pk])


def edit_url(tcn):
    return reverse("tcn:edit", args=[tcn.pk])


def edit_data(tcn, action="save", **overrides):
    """What the S7 form posts for `tcn` as loaded, with `overrides` applied."""
    header = {
        "project_description": tcn.project_description,
        "prepared_by": tcn.prepared_by,
        "row_version": tcn.row_version,
    }
    for key in list(overrides):
        if key in header:
            header[key] = overrides.pop(key)
    data = post_data(tcn.setup, action=action, **overrides)
    data.update(header)
    return data


# --- S6 New TCN -------------------------------------------------------------------


def test_first_tcn_only_from_project_defaults(logged_in, project):
    content = logged_in.get(new_url(project)).content.decode()
    assert 'value="001"' in content
    assert "Project defaults" in content and "Copy of TCN" not in content

    response = logged_in.post(new_url(project), {"run_no": "001", "source_type": "defaults"})
    tcn = TcnRevision.objects.get()
    assert response.status_code == 302 and response["Location"] == edit_url(tcn)
    assert str(tcn) == "TCN001" and tcn.source_kind == "project_defaults"
    assert messages_of(response) == ["TCN001 created as draft (from project defaults)."]


def test_next_tcn_proposes_copy_of_highest_run(logged_in, project, user):
    create_tcn(project, 1, user)
    latest = create_tcn(project, 3, user)
    response = logged_in.get(new_url(project))
    form = response.context["form"]
    assert form.initial["run_no"] == "004"
    assert form.initial["source_type"] == "copy"
    assert form.initial["source"] == latest


@pytest.mark.parametrize("typed", ["4", "04", "004", " 4 "])
def test_run_no_input_forms(logged_in, project, typed):
    logged_in.post(new_url(project), {"run_no": typed, "source_type": "defaults"})
    assert TestRun.objects.get().display_no == "004"


@pytest.mark.parametrize("typed", ["0", "1000", "abc", "4a", ""])
def test_run_no_invalid(logged_in, project, typed):
    response = logged_in.post(new_url(project), {"run_no": typed, "source_type": "defaults"})
    assert response.status_code == 200
    assert not TestRun.objects.exists()


def test_duplicate_run_no_message(logged_in, project, user):
    create_tcn(project, 1, user)
    response = logged_in.post(new_url(project), {"run_no": "1", "source_type": "defaults"})
    assert response.status_code == 200
    assert "Run number already used!" in response.content.decode()
    assert TestRun.objects.count() == 1


def test_copy_to_new_tcn(logged_in, project, user):
    source = create_tcn(project, 1, user)
    source.setup.run_description = "Run 1"
    source.setup.save()
    response = logged_in.get(new_url(project), {"source": source.pk})
    assert response.context["form"].initial["source"] == source

    response = logged_in.post(new_url(project), {"run_no": "2", "source_type": "copy", "source": source.pk})
    copy = TcnRevision.objects.get(test_run__run_no=2)
    assert copy.source_tcn == source and copy.setup.run_description == "Run 1"
    assert messages_of(response) == ["TCN002 created as draft (copy of TCN001)."]


def test_copy_requires_a_source(logged_in, project, user):
    create_tcn(project, 1, user)
    response = logged_in.post(new_url(project), {"run_no": "2", "source_type": "copy"})
    assert "Select the TCN to copy." in response.content.decode()
    assert TestRun.objects.count() == 1


def test_tcn_of_other_project_cannot_be_copied(logged_in, project, user):
    other = make_project(user, project_no="2099RSD02TL")
    foreign = create_tcn(other, 4, user)
    assert logged_in.get(new_url(project), {"source": foreign.pk}).status_code == 404
    assert logged_in.get(new_url(project), {"source": "x"}).status_code == 404
    content = logged_in.get(new_url(other)).content.decode()
    assert "TCN004" in content

    create_tcn(project, 1, user)
    response = logged_in.post(new_url(project), {"run_no": "2", "source_type": "copy", "source": foreign.pk})
    assert response.status_code == 200
    assert "Select a valid choice" in response.content.decode()
    assert not project.test_runs.filter(run_no=2).exists()


# --- S7 edit draft --------------------------------------------------------------


def test_edit_page_shows_header_and_setup_form(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    content = logged_in.get(edit_url(tcn)).content.decode()
    assert "TCN001" in content and "DRAFT" in content
    assert "Run/TCN No.: <strong>001</strong>" in content
    assert "from project defaults" in content
    assert 'value="ADNOC BAB UHTW/UHTW 4.750/4.750"' in content
    assert 'name="row_version"' in content
    assert "Seal under test" in content
    assert "revision_reason" not in content  # rev 0


def test_save_draft(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    data = edit_data(tcn, prepared_by="mt", run_description="Dynamic test", speed="2980 rpm", test_unit="TU5")
    response = logged_in.post(edit_url(tcn), data)
    assert response.status_code == 302 and response["Location"] == edit_url(tcn)
    tcn.refresh_from_db()
    tcn.setup.refresh_from_db()
    assert tcn.prepared_by == "MT" and tcn.row_version == 2
    assert (tcn.setup.run_description, tcn.setup.speed, tcn.setup.test_unit) == ("Dynamic test", "2980", "TU5")
    assert "TCN001 saved." in messages_of(response)
    assert any("saved as “2980”" in m for m in messages_of(response))


def test_update_action_does_not_save(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    data = edit_data(tcn, action="update", arrangement=Arrangement.SINGLE, speed="1500")
    response = logged_in.post(edit_url(tcn), data)
    assert response.status_code == 200
    assert "Test Seal" in response.content.decode()
    tcn.setup.refresh_from_db()
    assert (tcn.setup.arrangement, tcn.setup.speed) == (Arrangement.DUAL_PRESSURIZED, "")


def test_arrangement_switch_on_draft_asks_before_discarding(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    tcn.setup.positions.filter(role="inboard").update(seal_type_size="UHTW 4.750")
    tcn.setup.seal_support_pressure = "70"
    tcn.setup.save()
    data = edit_data(tcn, arrangement=Arrangement.SINGLE)

    response = logged_in.post(edit_url(tcn), data)
    assert response.status_code == 200
    assert "Inboard Seal: UHTW 4.750" in response.content.decode()
    assert tcn.setup.positions.count() == 2

    response = logged_in.post(edit_url(tcn), dict(data, confirm_discard="1"))
    assert response.status_code == 302
    tcn.setup.refresh_from_db()
    assert sorted(tcn.setup.positions.values_list("role", flat=True)) == ["test"]
    assert tcn.setup.seal_support_pressure == "70"  # kept, now labelled Flush


def test_invalid_header_shows_errors_and_saves_nothing(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    response = logged_in.post(edit_url(tcn), edit_data(tcn, prepared_by="X" * 11, speed="1500"))
    assert response.status_code == 200
    assert "at most 10 characters" in response.content.decode()
    tcn.setup.refresh_from_db()
    assert tcn.setup.speed == ""


def test_at14_second_session_cannot_overwrite(client, django_user_model, project, user, other_user):
    """AT-14: two sessions edit the same draft; the second save is refused."""
    tcn = create_tcn(project, 1, user)
    first, second = client, client.__class__()
    first.force_login(user)
    second.force_login(other_user)
    form_first = edit_data(tcn, speed="1500")  # both opened version 1
    form_second = edit_data(tcn, speed="3600")

    assert second.post(edit_url(tcn), form_second).status_code == 302
    response = first.post(edit_url(tcn), form_first)
    assert response.status_code == 200
    content = response.content.decode()
    assert "was changed by Mark Test" in content and "have not been saved" in content
    assert 'value="1500"' in content  # the user's input is still on screen
    tcn.setup.refresh_from_db()
    assert tcn.setup.speed == "3600"
    assert TcnRevision.objects.get(pk=tcn.pk).row_version == 2


def test_issued_tcn_cannot_be_edited_via_the_form(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    data = edit_data(tcn, speed="1500")
    issue(tcn, user)
    response = logged_in.get(edit_url(tcn))
    assert response.status_code == 200
    assert response.templates[0].name == "tcn/tcn_view.html"  # read-only S9, no form
    assert 'name="action"' not in response.content.decode()

    response = logged_in.post(edit_url(tcn), data)
    assert response.status_code == 302 and response["Location"] == edit_url(tcn)
    assert "TCN001 is issued and cannot be edited." in messages_of(response)
    assert TcnRevision.objects.get(pk=tcn.pk).setup.speed == ""


def test_revision_reason_field_only_from_rev_1(logged_in, project, user):
    rev_0 = issue(create_tcn(project, 1, user), user)
    rev_1 = TcnRevision.objects.create(
        test_run=rev_0.test_run,
        revision=1,
        setup=rev_0.setup.clone(),
        source_kind=TcnRevision.SourceKind.NEW_REVISION,
        source_tcn=rev_0,
        created_by=user,
        updated_by=user,
    )
    assert 'name="revision_reason"' in logged_in.get(edit_url(rev_1)).content.decode()
    data = edit_data(rev_1)
    data["revision_reason"] = "Speed changed on customer request"
    logged_in.post(edit_url(rev_1), data)
    rev_1.refresh_from_db()
    assert rev_1.revision_reason == "Speed changed on customer request"


# --- S4 register ----------------------------------------------------------------


def test_project_page_register(logged_in, project, user):
    first = create_tcn(project, 1, user)
    first.setup.test_unit = "TU5"
    first.setup.speed = "2980"
    first.setup.seal_support_pressure = "70"
    first.setup.save()
    issue(first, user)
    create_tcn(project, 2, user, source=first)

    response = logged_in.get(reverse("projects:detail", args=[project.pk]))
    content = response.content.decode()
    assert "ADNOC BAB UHTW/UHTW 4.750/4.750" in content
    assert [row["tcn"].tcn_no for row in response.context["register"]] == ["001", "002"]
    assert "Issued" in content and "Draft" in content
    assert "TU5" in content and "2980 rpm" in content and "Barrier: 70 barg" in content
    assert f'?source={first.pk}"' in content
    assert reverse("tcn:create", args=[project.pk]) in content


def test_register_shows_issued_revision_and_pending_draft(logged_in, project, user):
    rev_0 = issue(create_tcn(project, 1, user), user)
    rev_1 = TcnRevision.objects.create(
        test_run=rev_0.test_run,
        revision=1,
        setup=rev_0.setup.clone(),
        source_kind=TcnRevision.SourceKind.NEW_REVISION,
        source_tcn=rev_0,
        created_by=user,
        updated_by=user,
    )
    response = logged_in.get(reverse("projects:detail", args=[project.pk]))
    (row,) = response.context["register"]
    assert row["tcn"] == rev_0 and row["pending_draft"] == rev_1
    assert "draft rev 1" in response.content.decode()


def test_project_list_counts_tcns(logged_in, project, user):
    create_tcn(project, 1, user)
    create_tcn(project, 2, user)
    response = logged_in.get(reverse("projects:list"))
    (listed,) = response.context["projects"]
    assert listed.tcn_count == 2 and listed.last_tcn_at is not None


# --- AT-8 -------------------------------------------------------------------------


def test_at8_project_defaults_edit_changes_no_tcn(logged_in, project, user):
    """AT-8: editing defaults alters no existing TCN; a new TCN from defaults uses the new values."""
    defaults = project.default_setup
    logged_in.post(reverse("projects:defaults", args=[project.pk]), post_data(defaults, speed="2980", test_unit="TU5"))
    tcn001 = issue(create_tcn(project, 1, user), user)
    tcn002 = create_tcn(project, 2, user, source=tcn001)  # draft

    defaults.refresh_from_db()
    response = logged_in.post(
        reverse("projects:defaults", args=[project.pk]),
        post_data(defaults, speed="1500", test_unit="TU7", arrangement=Arrangement.SINGLE, confirm_discard="1"),
    )
    assert response.status_code == 302
    for tcn in (tcn001, tcn002):
        setup = TcnRevision.objects.get(pk=tcn.pk).setup
        assert (setup.speed, setup.test_unit, setup.arrangement) == ("2980", "TU5", Arrangement.DUAL_PRESSURIZED)
        assert sorted(setup.positions.values_list("role", flat=True)) == ["inboard", "outboard"]

    logged_in.post(new_url(project), {"run_no": "3", "source_type": "defaults"})
    tcn003 = TcnRevision.objects.get(test_run__run_no=3)
    assert (tcn003.setup.speed, tcn003.setup.test_unit, tcn003.setup.arrangement) == ("1500", "TU7", Arrangement.SINGLE)


# --- Differences vs source (commit 7) ---------------------------------------------


def test_copy_shows_markers_after_save(logged_in, project, user):
    source = create_tcn(project, 1, user)
    source.setup.speed = "2980"
    source.setup.save()
    copy = create_tcn(project, 2, user, source=source)

    content = logged_in.get(edit_url(copy)).content.decode()
    assert "No differences from TCN001 yet" in content
    assert 'class="was"' not in content

    logged_in.post(edit_url(copy), edit_data(copy, speed="1500", prepared_by="MT"))
    response = logged_in.get(edit_url(copy))
    content = response.content.decode()
    assert "2 differences from TCN001" in content
    assert "changed — was: 2980</span>" in content and "changed — was: MG</span>" in content
    assert [c.key for c in response.context["change_list"]] == ["prepared_by", "speed"]


def test_markers_reflect_saved_values_not_unsaved_input(logged_in, project, user):
    copy = create_tcn(project, 2, user, source=create_tcn(project, 1, user))
    response = logged_in.post(edit_url(copy), edit_data(copy, action="update", speed="1500"))
    assert response.context["change_list"] == []


def test_multiline_run_description_marker(logged_in, project, user):
    source = create_tcn(project, 1, user)
    source.setup.run_description = "• Step 1\n   - detail"
    source.setup.save()
    copy = create_tcn(project, 2, user, source=source)
    logged_in.post(edit_url(copy), edit_data(copy, run_description="• Step 1 changed"))
    content = logged_in.get(edit_url(copy)).content.decode()
    marker = '<details class="was"><summary>changed — was:</summary><pre>• Step 1\n   - detail</pre></details>'
    assert marker in content


def test_no_comparison_for_tcn_from_defaults_or_on_defaults_page(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    response = logged_in.get(edit_url(tcn))
    assert response.context["change_list"] is None
    assert "difference" not in response.content.decode()
    content = logged_in.get(reverse("projects:defaults", args=[project.pk])).content.decode()
    assert 'class="was"' not in content and "difference" not in content


# --- Preview PDF (commit 8; PDF since stabilization S1) --------------------------------------------------------


def preview_url(tcn):
    return reverse("tcn:preview", args=[tcn.pk])


def test_preview_draft_pdf(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    logged_in.post(edit_url(tcn), edit_data(tcn, speed="2980"))
    before = TcnRevision.objects.filter(pk=tcn.pk).values().get()

    response = logged_in.get(preview_url(tcn))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'inline; filename="2026RSD03TL-TCN001-DRAFT.pdf"'
    assert response["Cache-Control"] == "no-store"
    lines = pdf_lines(response.content)
    assert "DRAFT — not issued" in lines and "Speed: 2980 rpm" in lines

    # Nothing is stored or changed by a preview.
    assert TcnRevision.objects.filter(pk=tcn.pk).values().get() == before


def test_preview_uses_saved_draft_not_project_defaults(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    defaults = project.default_setup
    defaults.speed = "1500"
    defaults.save()
    lines = pdf_lines(logged_in.get(preview_url(tcn)).content)
    assert not any("1500" in line for line in lines)


def test_edit_page_links_preview(logged_in, project, user):
    tcn = create_tcn(project, 1, user)
    assert preview_url(tcn) in logged_in.get(edit_url(tcn)).content.decode()


def test_no_preview_of_issued_tcn(logged_in, project, user):
    tcn = issue(create_tcn(project, 1, user), user)
    response = logged_in.get(preview_url(tcn))
    assert response.status_code == 302
    assert response["Location"] == edit_url(tcn)  # the read-only view; its download serves the stored file
    assert logged_in.post(preview_url(tcn)).status_code == 405

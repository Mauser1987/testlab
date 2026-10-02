import re

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from testlab.projects.models import Project

from .test_models import make_project


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def post_project(client, url, **data):
    values = {"project_no": "2099RSD01TL", "description": "TEST UHTW 4.750", "customer": ""}
    values.update(data)
    return client.post(url, values)


def message_texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def test_create_project(logged_in, user):
    response = post_project(logged_in, reverse("projects:create"), project_no=" 2099rsd01tl ", customer="ADNOC")
    assert response.status_code == 302
    project = Project.objects.get()
    assert response["Location"] == reverse("projects:defaults", args=[project.pk])
    assert project.project_no == "2099RSD01TL"
    assert project.customer == "ADNOC"
    assert project.created_by == user and project.updated_by == user
    assert message_texts(response) == ["Project 2099RSD01TL saved."]


def test_duplicate_project_no_rejected_in_any_case(logged_in, user):
    make_project(user, project_no="2099RSD01TL")
    response = post_project(logged_in, reverse("projects:create"), project_no="2099rsd01tl")
    assert response.status_code == 200
    assert "A project with this number already exists." in response.content.decode()
    assert Project.objects.count() == 1


def test_non_conforming_project_no_saved_with_warning(logged_in):
    response = post_project(logged_in, reverse("projects:create"), project_no="2099-TEST")
    assert response.status_code == 302
    assert Project.objects.filter(project_no="2099-TEST").exists()
    assert any("does not follow the usual format" in m for m in message_texts(response))


def test_invalid_characters_rejected(logged_in):
    response = post_project(logged_in, reverse("projects:create"), project_no="A/B")
    assert response.status_code == 200
    assert "Use only letters, digits" in response.content.decode()
    assert not Project.objects.exists()


@pytest.mark.parametrize("description", ["", "   ", "x" * 201])
def test_description_required_and_limited(logged_in, description):
    response = post_project(logged_in, reverse("projects:create"), description=description)
    assert response.status_code == 200
    assert not Project.objects.exists()


def test_edit_project_records_updater(client, user, other_user):
    project = make_project(user)
    client.force_login(other_user)
    response = post_project(
        client, reverse("projects:edit", args=[project.pk]), project_no="2099RSD02TL", description="Corrected"
    )
    assert response.status_code == 302
    project.refresh_from_db()
    assert project.project_no == "2099RSD02TL"
    assert project.description == "Corrected"
    assert project.created_by == user
    assert project.updated_by == other_user


def test_edit_form_shows_current_values(logged_in, user):
    project = make_project(user, customer="Celeros")
    response = logged_in.get(reverse("projects:edit", args=[project.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert 'value="2099RSD01TL"' in content
    assert 'value="Celeros"' in content


def test_list_shows_projects_and_searches(logged_in, user):
    make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750", customer="ADNOC")
    make_project(user, project_no="2026RSD06TL", description="Celeros pump seal", customer="Celeros")

    content = logged_in.get(reverse("projects:list")).content.decode()
    assert "2026RSD03TL" in content and "2026RSD06TL" in content
    assert content.index("2026RSD06TL") < content.index("2026RSD03TL")

    for query, expected, absent in [
        ("rsd03", "2026RSD03TL", "2026RSD06TL"),
        ("bab", "2026RSD03TL", "2026RSD06TL"),
        ("celeros", "2026RSD06TL", "2026RSD03TL"),
    ]:
        content = logged_in.get(reverse("projects:list"), {"q": query}).content.decode()
        assert expected in content and absent not in content

    content = logged_in.get(reverse("projects:list"), {"q": "nomatch"}).content.decode()
    assert "No projects match" in content


def configure_defaults(project, arrangement, seal_types, **fields):
    """Set the project defaults directly: arrangement, seal type per role, conditions."""
    setup = project.default_setup
    setup.arrangement = arrangement
    for name, value in fields.items():
        setattr(setup, name, value)
    setup.save()
    setup.positions.all().delete()
    for role in setup.applicable_roles():
        setup.positions.create(role=role, seal_type_size=seal_types.get(role, ""))


def list_rows(content):
    body = content[content.index("<tbody>") : content.index("</tbody>")]
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", row)).strip() for row in body.split("</tr>")[:-1]]


def test_list_shows_engineering_overview_from_defaults(logged_in, user, django_assert_max_num_queries):
    dual = make_project(user, project_no="2026RSD03TL", description="ADNOC BAB UHTW/UHTW 4.750/4.750", customer="ADNOC")
    configure_defaults(
        dual,
        "dual_pressurized",
        {"plug": "DHTW 4.750", "inboard": "UHTW 4.750", "outboard": "UHTW 4.750"},
        plug_seal_present=True,
        process_pressure="10",
        seal_support_pressure="35",
        test_unit="TU-04",
    )
    single = make_project(user, project_no="2025RSD02TL", customer="Celeros")
    configure_defaults(
        single,
        "single",
        {"plug": "DHTW 4.750", "test": "C0625623AP"},
        plug_seal_present=True,
        seal_support_pressure="TBD",
    )
    make_project(user, project_no="2024RSD01TL")
    mixed = make_project(user, project_no="2023RSD01TL", customer="Shell")
    configure_defaults(mixed, "dual_unpressurized", {"inboard": "UHTW 4.750", "outboard": "DHTW 3.500"})

    with django_assert_max_num_queries(6):  # no query per project
        content = logged_in.get(reverse("projects:list")).content.decode()

    head = content[content.index("<thead>") : content.index("</thead>")]
    columns = ["Project no.", "Customer", "Seal type", "Arrangement", "Process pressure",
               "Barrier / Buffer / Flush pressure", "No. of TCNs", "Test unit"]
    assert [head.index(c) for c in columns] == sorted(head.index(c) for c in columns)
    assert "Description" not in head and "Last TCN" not in head
    assert "ADNOC BAB" not in content  # the description stays on the project page

    assert list_rows(content) == [
        # Seal type of the seals under test only, equal values once; the Plug Seal is left out.
        "2026RSD03TL ADNOC UHTW 4.750 Dual Pressurized + Plug Seal 10 barg 35 barg 0 TU-04 Defaults",
        "2025RSD02TL Celeros C0625623AP Single — TBD barg 0 — Defaults",
        "2024RSD01TL — — Dual Pressurized — — 0 — Defaults",
        "2023RSD01TL Shell UHTW 4.750 / DHTW 3.500 Dual Unpressurized — — 0 — Defaults",
    ]
    assert 'title="Barrier pressure"' in content and 'title="Flush pressure"' in content
    assert reverse("projects:defaults", args=[dual.pk]) in content
    assert reverse("projects:detail", args=[dual.pk]) in content

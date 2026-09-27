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

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from testlab.projects.models import Project, project_no_format_warning


def make_project(user, **fields):
    values = {"project_no": "2099RSD01TL", "description": "TEST UHTW 4.750", "created_by": user, "updated_by": user}
    values.update(fields)
    return Project.objects.create(**values)


def test_save_normalises_project_no_and_trims_text(user):
    project = make_project(user, project_no=" 2099rsd01tl ", description="  ADNOC BAB  ", customer=" ADNOC ")
    project.refresh_from_db()
    assert project.project_no == "2099RSD01TL"
    assert project.description == "ADNOC BAB"
    assert project.customer == "ADNOC"


def test_project_no_characters_restricted(user):
    for bad in ["A/B", "A B", "2099\\X", "TCN:1"]:
        project = Project(project_no=bad, description="x", created_by=user, updated_by=user)
        with pytest.raises(ValidationError) as excinfo:
            project.full_clean()
        assert "project_no" in excinfo.value.message_dict


def test_project_no_max_length(user):
    project = Project(project_no="X" * 21, description="x", created_by=user, updated_by=user)
    with pytest.raises(ValidationError):
        project.full_clean()


def test_format_warning_is_only_for_non_conforming_numbers():
    assert project_no_format_warning("2026RSD03TL") is None
    assert "2099-TEST" in project_no_format_warning("2099-TEST")


@override_settings(TESTLAB_PROJECT_NO_PATTERN="")
def test_format_warning_can_be_disabled():
    assert project_no_format_warning("ANYTHING") is None

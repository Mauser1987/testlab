from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("new/", views.ProjectCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="edit"),
    path("<int:pk>/defaults/", views.ProjectDefaultsView.as_view(), name="defaults"),
    path("<int:pk>/program/", views.ProgramView.as_view(), name="program"),
    path("<int:pk>/program/requirements/", views.ProgramRequirementAddView.as_view(), name="program_requirement_add"),
    path("program/requirements/<int:pk>/", views.ProgramRequirementEditView.as_view(), name="program_requirement"),
]

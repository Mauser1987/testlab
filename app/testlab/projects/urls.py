from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("new/", views.ProjectCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProjectUpdateView.as_view(), name="edit"),
    path("<int:pk>/defaults/", views.ProjectDefaultsView.as_view(), name="defaults"),
    path("<int:pk>/drawings/<str:kind>/", views.DrawingUploadView.as_view(), name="drawing_add"),
    path("drawings/<int:pk>/", views.DrawingFileView.as_view(), name="drawing_file"),
    path("drawings/<int:pk>/preview/", views.DrawingFileView.as_view(preview=True), name="drawing_preview"),
    path("drawings/<int:pk>/delete/", views.DrawingDeleteView.as_view(), name="drawing_delete"),
    path("<int:pk>/program/", views.ProgramView.as_view(), name="program"),
    path("<int:pk>/program/requirements/", views.ProgramRequirementAddView.as_view(), name="program_requirement_add"),
    path("program/requirements/<int:pk>/", views.ProgramRequirementEditView.as_view(), name="program_requirement"),
]

from django.urls import path

from . import views

app_name = "tcn"

urlpatterns = [
    path("projects/<int:project_pk>/tcn/new/", views.TcnCreateView.as_view(), name="create"),
    path("tcn/<int:pk>/", views.TcnEditView.as_view(), name="edit"),
    path("tcn/<int:pk>/preview/", views.TcnPreviewView.as_view(), name="preview"),
    path("tcn/<int:pk>/issue/", views.TcnIssueView.as_view(), name="issue"),
    path("tcn/<int:pk>/document/", views.TcnDocumentView.as_view(), name="document"),
    path("tcn/<int:pk>/new-revision/", views.TcnNewRevisionView.as_view(), name="new_revision"),
    path("tcn/<int:pk>/cancel/", views.TcnCancelView.as_view(), name="cancel"),
    path("tcn/<int:pk>/delete/", views.TcnDeleteView.as_view(), name="delete"),
]

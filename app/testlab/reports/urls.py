from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("projects/<int:pk>/final-report/", views.FinalReportView.as_view(), name="final_report"),
    path("projects/<int:pk>/final-report/preview/", views.FinalReportPreviewView.as_view(), name="preview"),
]

from django.urls import path

from . import views

app_name = "execution"

urlpatterns = [
    path("runs/<int:run_pk>/log/", views.ManualLogView.as_view(), name="log"),
    path("log/<int:pk>/edit/", views.EntryEditView.as_view(), name="entry_edit"),
    path("log/<int:pk>/delete/", views.EntryDeleteView.as_view(), name="entry_delete"),
    path("runs/<int:run_pk>/dcs/", views.DcsListView.as_view(), name="dcs"),
    path("dcs/<int:pk>/", views.DcsDetailView.as_view(), name="dcs_detail"),
    path("dcs/<int:pk>/data/", views.DcsDataView.as_view(), name="dcs_data"),
    path("dcs/<int:pk>/raw/", views.DcsRawView.as_view(), name="dcs_raw"),
]

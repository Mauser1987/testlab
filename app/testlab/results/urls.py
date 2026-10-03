from django.urls import path

from . import views

app_name = "results"

urlpatterns = [
    path("runs/<int:run_pk>/result/", views.ResultView.as_view(), name="result"),
    path("runs/<int:run_pk>/result/start/", views.ResultStartView.as_view(), name="start"),
    path("runs/<int:run_pk>/result/components/", views.ComponentsView.as_view(), name="components"),
    path("runs/<int:run_pk>/result/components/add/", views.ComponentAddView.as_view(), name="component_add"),
    path("result/components/<int:pk>/remove/", views.ComponentRemoveView.as_view(), name="component_remove"),
    path("runs/<int:run_pk>/result/measurements/", views.MeasurementsView.as_view(), name="measurements"),
    path("runs/<int:run_pk>/result/pictures/", views.ImageUploadView.as_view(), name="image_upload"),
    path("runs/<int:run_pk>/result/compare/<int:component_pk>/", views.CompareView.as_view(), name="compare"),
    path("result/pictures/<int:pk>/edit/", views.ImageEditView.as_view(), name="image_edit"),
    path("result/pictures/<int:pk>/delete/", views.ImageDeleteView.as_view(), name="image_delete"),
    path("result/pictures/<int:pk>/move/", views.ImageMoveView.as_view(), name="image_move"),
    path("result/pictures/<int:pk>/original/", views.ImageFileView.as_view(), name="image_original"),
    path("result/pictures/<int:pk>/preview/", views.ImageFileView.as_view(preview=True), name="image_preview"),
    path("runs/<int:run_pk>/result/acceptance/", views.AcceptanceAddView.as_view(), name="acceptance_add"),
    path("result/acceptance/<int:pk>/", views.AcceptanceEditView.as_view(), name="acceptance_edit"),
    path("dcs/<int:dataset_pk>/to-result/", views.PlotAddView.as_view(), name="plot_add"),
    path("result/plots/<int:pk>/update/", views.PlotUpdateView.as_view(), name="plot_update"),
    path("result/plots/<int:pk>/image/", views.PlotImageView.as_view(), name="plot_image"),
    path("result/plots/<int:pk>/caption/", views.PlotCaptionView.as_view(), name="plot_caption"),
    path("result/plots/<int:pk>/move/", views.PlotMoveView.as_view(), name="plot_move"),
    path("result/plots/<int:pk>/delete/", views.PlotDeleteView.as_view(), name="plot_delete"),
    path("runs/<int:run_pk>/result/conclusion/", views.NarrativeView.as_view(), name="narrative"),
]

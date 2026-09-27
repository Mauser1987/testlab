from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="projects:list"), name="home"),
    path("projects/", include("testlab.projects.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # Admin is for user management by superusers only.
    path("admin/", admin.site.urls),
]

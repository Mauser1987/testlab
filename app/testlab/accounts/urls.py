from django.contrib.auth.views import LoginView
from django.urls import path

from .forms import LoginForm
from .views import RegisterView

urlpatterns = [
    # Before django.contrib.auth.urls, so this login view (email address) is used.
    path("login/", LoginView.as_view(authentication_form=LoginForm), name="login"),
    path("register/", RegisterView.as_view(), name="register"),
]

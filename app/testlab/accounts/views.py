from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .forms import AWAITING_APPROVAL, RegistrationForm, registration_open


@method_decorator(login_not_required, name="dispatch")
class RegisterView(View):
    """Self-registration from the login page; the account awaits administrator approval."""

    template_name = "accounts/register.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("home")
        return self.render(request, RegistrationForm())

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("home")
        form = RegistrationForm(request.POST)
        if form.is_valid() and form.save() is not None:
            messages.success(request, AWAITING_APPROVAL)
            return redirect("login")
        return self.render(request, form)

    def render(self, request, form):
        return render(request, self.template_name, {"form": form, "registration_open": registration_open()})

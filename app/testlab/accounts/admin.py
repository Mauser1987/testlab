"""User administration in Django admin, including approval of registered accounts.

A self-registered account is inactive ("awaiting approval") until an
administrator activates it: select it and run "Approve selected accounts",
or tick "Active" on the user page.
"""

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin


class ApprovalFilter(admin.SimpleListFilter):
    title = "approval"
    parameter_name = "approval"

    def lookups(self, request, model_admin):
        return [("pending", "Awaiting approval"), ("deactivated", "Deactivated")]

    def queryset(self, request, queryset):
        if self.value() == "pending":
            return queryset.filter(is_active=False, last_login__isnull=True)
        if self.value() == "deactivated":
            return queryset.filter(is_active=False, last_login__isnull=False)
        return queryset


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class TestLabUserAdmin(UserAdmin):
    list_display = ["email", "first_name", "last_name", "is_active", "is_staff", "date_joined", "last_login"]
    list_filter = [ApprovalFilter, "is_active", "is_staff", "is_superuser", "groups"]
    ordering = ["is_active", "-date_joined"]  # accounts awaiting approval first
    search_fields = ["email", "username", "first_name", "last_name"]
    actions = ["approve"]

    @admin.action(description="Approve selected accounts (activate)", permissions=["change"])
    def approve(self, request, queryset):
        count = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f"{count} account{'s' if count != 1 else ''} approved.", messages.SUCCESS)

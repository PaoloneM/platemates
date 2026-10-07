from django.contrib import admin

from .models import Invitation, OIDCIdentity, UserProfile


@admin.register(OIDCIdentity)
class OIDCIdentityAdmin(admin.ModelAdmin):
    list_display = ["user", "subject", "created_at", "last_login_at"]
    search_fields = ["user__email", "subject"]
    readonly_fields = ["created_at", "last_login_at"]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["team", "role", "note", "state", "created_at", "expires_at"]
    list_filter = ["team"]
    readonly_fields = ["token", "accepted_at", "accepted_by"]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "language"]

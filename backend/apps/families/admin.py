from django.contrib import admin

from .models import Family, FamilyMember, Membership, Preference, RecipeBookEntry


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


class FamilyMemberInline(admin.TabularInline):
    model = FamilyMember
    extra = 0


class PreferenceInline(admin.TabularInline):
    model = Preference
    autocomplete_fields = ["ingredient", "cuisine"]
    extra = 0


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    filter_horizontal = ["tools"]
    inlines = [MembershipInline, FamilyMemberInline, PreferenceInline]


@admin.register(RecipeBookEntry)
class RecipeBookEntryAdmin(admin.ModelAdmin):
    list_display = ["family", "recipe", "status", "rating"]
    list_filter = ["family", "status"]
    autocomplete_fields = ["recipe"]

from django.contrib import admin

from .models import CalendarDay, Member, Membership, Preference, RecipeBookEntry, Team


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


class MemberInline(admin.TabularInline):
    model = Member
    extra = 0


class PreferenceInline(admin.TabularInline):
    model = Preference
    autocomplete_fields = ["ingredient", "cuisine"]
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    filter_horizontal = ["tools"]
    inlines = [MembershipInline, MemberInline, PreferenceInline]


@admin.register(RecipeBookEntry)
class RecipeBookEntryAdmin(admin.ModelAdmin):
    list_display = ["team", "recipe", "status", "rating"]
    list_filter = ["team", "status"]
    autocomplete_fields = ["recipe"]


@admin.register(CalendarDay)
class CalendarDayAdmin(admin.ModelAdmin):
    list_display = ["team", "date", "people", "note"]
    list_filter = ["team"]
    date_hierarchy = "date"

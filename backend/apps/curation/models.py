"""Drafts of system recipes: researched on the web and drafted by the LLM in the background,
then reviewed by staff, who publish them as recipes of the system team or discard them.

A draft never becomes a recipe by itself: publishing goes through the recipe editor, like every
other recipe, and only marks the draft published.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Reliability(models.TextChoices):
    # Two or more real recipe pages whose ingredients agree.
    HIGH = "high", _("High")
    # One real page, or several that disagree.
    MEDIUM = "medium", _("Medium")
    # No page found: the model wrote it from what it knows.
    LOW = "low", _("Low")


class SystemDraft(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        READY = "ready", _("Ready for review")
        FAILED = "failed", _("Failed")
        PUBLISHED = "published", _("Published")
        DISCARDED = "discarded", _("Discarded")

    # The dish staff asked for, in their words.
    dish = models.CharField(max_length=200)
    # The language the recipe is drafted in.
    language = models.CharField(max_length=10, default="it")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # The verified recipe pages it is based on: url, site, title, rating, rating_count.
    sources = models.JSONField(default=list, blank=True)
    # The recipe draft, in the assistant's shape (`apps.assistant.draft.normalize_draft`).
    draft = models.JSONField(null=True, blank=True)
    reliability = models.CharField(max_length=10, choices=Reliability.choices, blank=True)
    # How much the sources' ingredients agree, 0 to 1 (null with fewer than two sources).
    agreement = models.FloatField(null=True, blank=True)
    # The web rating read from the sources, on a 0-5 scale, and how many votes it rests on.
    web_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    web_rating_count = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    recipe = models.ForeignKey(
        "recipes.Recipe", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.dish} ({self.status})"

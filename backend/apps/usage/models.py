"""What the AI providers consumed, by team and feature, and what it is estimated to cost.

A row per call to a model (apps/usage/recorder.py), attributed to the team and feature the call
was made for (apps/usage/context.py). Costs are not stored: they are computed when shown, from
the price list administrators keep (`ModelPrice`), so correcting a price corrects the history.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Feature(models.TextChoices):
    ASSISTANT = "assistant", _("Recipe assistant")
    MENU = "menu", _("Menu generation")
    SYSTEM_DRAFTS = "system_drafts", _("System recipe drafts")
    EMBEDDINGS = "embeddings", _("Recipe embeddings")
    OTHER = "other", _("Other")


class AIUsage(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Null: not made for a team (health checks), or the team was deleted since.
    team = models.ForeignKey(
        "families.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_usage"
    )
    feature = models.CharField(max_length=20, choices=Feature.choices, default=Feature.OTHER)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=200)
    operation = models.CharField(max_length=20)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    web_searches = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["team", "created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.model} {self.feature}"


class ModelPrice(models.Model):
    """A model's price, in USD, as the provider publishes it: per million tokens, and per
    thousand web searches. Kept by administrators (Management > Usage)."""

    model = models.CharField(max_length=200, unique=True)
    input_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    output_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cache_read_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cache_write_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    per_thousand_searches = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["model"]

    def __str__(self) -> str:
        return self.model

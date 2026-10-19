"""Drafts of system recipes: researched on the web and drafted by the LLM in the background,
then published as recipes of the system team, or discarded.

A draft becomes a recipe only by being published: by staff from the recipe editor, or, for a
draft of a campaign, automatically when it meets the bar staff set (`apps.curation.publishing`):
sources that agree, a good web rating, every ingredient known or approved.

A campaign fills the catalog in bulk: themes with a number of dishes each, planned by the model
a few at a time and drafted one by one in the worker. The links the web search finds are kept
with what became of them (`CandidateLink`); ingredients the catalog does not know wait in one
list for staff (`IngredientProposal`), never created by themselves.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _


class Reliability(models.TextChoices):
    # Two or more real recipe pages whose ingredients agree.
    HIGH = "high", _("High")
    # One real page, or several that disagree.
    MEDIUM = "medium", _("Medium")
    # No page found: the model wrote it from what it knows.
    LOW = "low", _("Low")


class Campaign(models.Model):
    """Many system recipes at once: `targets` are themes, each with a number of dishes; `brief`
    applies to all of them ("simple everyday recipes...")."""

    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        PAUSED = "paused", _("Paused")
        DONE = "done", _("Done")

    name = models.CharField(max_length=120)
    language = models.CharField(max_length=10, default="it")
    brief = models.TextField(blank=True)
    # [{"key": "primi", "theme": "...", "count": 50}]: `key` names the target in its drafts.
    targets = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Why planning stopped short of a target, if it did (the model found no new dish, ...).
    notes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class SourceSite(models.Model):
    """A recipe site the web search is steered towards (trusted) or away from (blocked).
    `domain` matches the site and its subdomains ("giallozafferano.it" matches
    "ricette.giallozafferano.it")."""

    domain = models.CharField(max_length=120, unique=True)
    trusted = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-trusted", "domain"]

    def __str__(self) -> str:
        return self.domain

    def covers(self, site: str) -> bool:
        return site == self.domain or site.endswith("." + self.domain)


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
    # Drafted for a campaign, for one of its targets (its `key`).
    campaign = models.ForeignKey(
        Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="drafts"
    )
    target = models.CharField(max_length=40, blank=True)
    # Published without staff opening it, having met the bar (`publishing.auto_publish`).
    published_automatically = models.BooleanField(default=False)
    # Searches that found no source for it (a campaign's draft is tried again a few times,
    # never written from the model's memory).
    search_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.dish} ({self.status})"


class CandidateLink(models.Model):
    """A page the web search offered for a draft's dish, and what became of it."""

    class Outcome(models.TextChoices):
        USED = "used", _("Used as a source")
        REJECTED = "rejected", _("Not a complete recipe page, or unreachable")
        BLOCKED = "blocked", _("Site blocked")
        SAME_SITE = "same_site", _("Another page of a site already used")
        NOT_CHECKED = "not_checked", _("Not needed: enough sources already")

    draft = models.ForeignKey(SystemDraft, on_delete=models.CASCADE, related_name="links")
    url = models.URLField(max_length=500)
    site = models.CharField(max_length=120)
    trusted = models.BooleanField(default=False)
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    title = models.CharField(max_length=200, blank=True)
    rating = models.FloatField(null=True, blank=True)
    rating_count = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["draft", "position"]

    def __str__(self) -> str:
        return f"{self.url} ({self.outcome})"


class IngredientProposal(models.Model):
    """An ingredient name drafts use and the catalog does not know, with what the model
    proposes: a new system ingredient (category, season, unit, staple or not) or another name
    of an existing one. Staff approve, change or reject it; drafts using it wait until then."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    class Action(models.TextChoices):
        NEW = "new", _("New ingredient")
        ALIAS = "alias", _("Another name of an existing one")

    # Normalized like an ingredient's name.
    name = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    action = models.CharField(max_length=5, choices=Action.choices, default=Action.NEW)
    alias_of = models.ForeignKey(
        "catalog.Ingredient", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    category = models.CharField(max_length=20, blank=True)
    default_unit = models.CharField(max_length=2, blank=True)
    season_months = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    basic = models.BooleanField(default=False)
    # Fields staff changed before approving: the ingredient records them as their decision.
    edited = ArrayField(models.CharField(max_length=20), default=list, blank=True)
    # The catalog entry it became (approved).
    ingredient = models.ForeignKey(
        "catalog.Ingredient", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    drafts = models.ManyToManyField(SystemDraft, blank=True, related_name="ingredient_proposals")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"

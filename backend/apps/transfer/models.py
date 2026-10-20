"""Imports run in the background (the worker), so a large file never meets a request timeout:
the job keeps the file, the options, how far it got and the report."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ImportJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    file_name = models.CharField(max_length=255, blank=True)
    # The export file itself. Kept after a preview, to import it for real without uploading it
    # again; emptied once really imported.
    document = models.JSONField(default=dict)
    mode = models.CharField(max_length=10, default="skip")
    target_team = models.ForeignKey(
        "families.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    dry_run = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # Where it is: the phase ("catalog", "recipes", "teams", "embeddings"), and how many of
    # the phase's items are done out of how many.
    phase = models.CharField(max_length=20, blank=True)
    done = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    report = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.status})"

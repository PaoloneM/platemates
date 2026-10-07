"""A conversation with the recipe assistant, persisted so a draft survives a page reload."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.teams.models import Team


class Mode(models.TextChoices):
    TELL = "tell", _("Tell me the recipe")
    SEARCH = "search", _("Help me search")
    LINK = "link", _("Give me a link")
    PHOTO = "photo", _("Upload or take a photo")


# Modes whose backend exists. The others are listed in the UI as "coming soon": offering them
# before their tools exist would let the LLM invent the content of pages or photos.
AVAILABLE_MODES = {Mode.TELL, Mode.LINK, Mode.PHOTO, Mode.SEARCH}


class AssistantSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        SAVED = "saved", _("Saved as a recipe")
        ABANDONED = "abandoned", _("Abandoned")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="assistant_sessions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_sessions"
    )
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TELL)
    # The whole exchange in OpenAI chat format (user, assistant with tool calls, tool results),
    # so it can be sent back to the model as is. The system prompt is not stored.
    messages = models.JSONField(default=list)
    # The latest recipe draft the assistant proposed (see `draft.py` for its shape).
    draft = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    recipe = models.ForeignKey(
        "recipes.Recipe", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.get_mode_display()} by {self.user} ({self.status})"


class Attachment(models.Model):
    """A photo sent to the assistant, and what was read from it.

    Kept in the database (not on disk) so it is in the backups with everything else, and so the
    review screen can show it beside the draft. Images are downscaled by the browser first
    (a few hundred KB each).
    """

    session = models.ForeignKey(
        AssistantSession, on_delete=models.CASCADE, related_name="attachments"
    )
    content_type = models.CharField(max_length=50)
    data = models.BinaryField()
    # Literal transcription of the text in the image; empty until read.
    transcription = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Photo {self.pk} of session {self.session_id}"

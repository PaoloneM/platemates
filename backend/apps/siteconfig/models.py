"""Application settings changed at runtime by administrators, without a release or a restart.

What can be set is defined in code (`registry.py`: type, default, limits); the database holds
only the values that differ from the default. `.env` keeps what belongs to the deployment
(addresses, secrets); settings here tune how the app behaves.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class ConfigVar(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key} = {self.value!r}"

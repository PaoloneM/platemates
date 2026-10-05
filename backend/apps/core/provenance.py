"""Track who set each derived property: the LLM, a computation, or the user.

The user always has the final say. A property is first proposed (by the LLM or by a derivation
such as bottom-up seasonality), and stays a proposal until the user confirms or overrides it.
Automatic processes must never overwrite a value the user has set.
"""

from __future__ import annotations

from django.db import models


class Source(models.TextChoices):
    LLM = "llm", "Suggested by the LLM"
    DERIVED = "derived", "Computed from other data"
    USER = "user", "Set by the user"


class ProvenanceMixin(models.Model):
    # {"<field name>": "<Source value>"}. Fields not listed have never been set by anyone special.
    provenance = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True

    def source_of(self, field: str) -> str | None:
        return self.provenance.get(field)

    def is_user_set(self, field: str) -> bool:
        return self.source_of(field) == Source.USER

    def propose(self, field: str, value: object, source: str) -> bool:
        """Set `field` from an automatic source, unless the user already decided it.

        Returns whether the value was applied. Does not save.
        """
        if source == Source.USER:
            raise ValueError("Use set_by_user() for user decisions.")
        if self.is_user_set(field):
            return False
        setattr(self, field, value)
        self.provenance = {**self.provenance, field: source}
        return True

    def set_by_user(self, field: str, value: object) -> None:
        """Record a user decision; automatic sources will no longer override it. Does not save."""
        setattr(self, field, value)
        self.provenance = {**self.provenance, field: Source.USER.value}

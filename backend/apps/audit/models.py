"""What a team's people changed, for the team's owners (Team page > Activity).

One event per action of a user (one API request that changed something), per team, with the
changes it made: which objects were created, changed (each field before and after) or deleted.
Kept for a limited time and up to a number of events (`audit.*` settings, administrators), see
`recorder.purge`.
"""

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    team = models.ForeignKey("families.Team", on_delete=models.CASCADE, related_name="audit_events")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The user's name when it happened: kept if the user leaves.
    user_name = models.CharField(max_length=150)
    # What the request was: "<resource>.<action>" ("shopping-list.merge", "recipe.destroy"),
    # worded by the interface.
    action = models.CharField(max_length=80)
    # The main object of the event, for its one-line summary.
    target_type = models.CharField(max_length=40)
    target_label = models.CharField(max_length=200, blank=True)
    # [{type, id, label, op: create|update|delete, fields: {name: [before, after]}}]
    changes = models.JSONField(default=list)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["team", "-id"], name="audit_team_newest")]

    def __str__(self) -> str:
        return f"{self.user_name} {self.action} {self.target_label}"

from rest_framework import mixins, serializers, viewsets

from apps.teams.permissions import require_owner, user_teams

from .models import AuditEvent
from .recorder import oldest_kept


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "user",
            "user_name",
            "action",
            "target_type",
            "target_label",
            "changes",
        ]


class AuditEventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """`?team=` (required, owners only): the team's activity, newest first; `?user=` narrows
    it to one person. Events past `audit.retention_days` never show, even before the lazy
    purge removes them."""

    serializer_class = AuditEventSerializer

    def get_queryset(self):
        team = user_teams(self.request.user).filter(pk=self.request.query_params.get("team") or 0)
        team = team.first()
        if team is None:
            raise serializers.ValidationError({"team": "Not one of your teams."})
        require_owner(self.request.user, team)
        events = AuditEvent.objects.filter(team=team, created_at__gte=oldest_kept())
        user = self.request.query_params.get("user")
        return events.filter(user=user) if user and user.isdigit() else events

from django.db import connection
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import IsAppAdmin
from apps.siteconfig import registry
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


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def stats_view(request):
    """For administrators: the activity log's totals and the teams by number of events, with
    their last activity and an estimate of their storage (the size of their rows; the table's
    total also counts its indexes and space not yet reclaimed)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.team_id, t.name, COUNT(*), MAX(e.created_at), SUM(pg_column_size(e.*))
            FROM audit_auditevent e JOIN families_team t ON t.id = e.team_id
            GROUP BY e.team_id, t.name
            ORDER BY COUNT(*) DESC, MAX(e.created_at) DESC
            """
        )
        teams = [
            {"team": team, "name": name, "events": count, "last": last, "bytes": int(size)}
            for team, name, count, last, size in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT pg_total_relation_size('audit_auditevent'), COUNT(*), MIN(created_at) "
            "FROM audit_auditevent"
        )
        table_bytes, total, oldest = cursor.fetchone()
    return Response(
        {
            "total_events": total,
            "table_bytes": table_bytes,
            "oldest": oldest,
            "retention_days": registry.get("audit.retention_days"),
            "max_events": registry.get("audit.max_events"),
            "teams": teams,
        }
    )

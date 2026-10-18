"""Asking for a team of one's own (a signed-in user without a team) and dealing with the
requests (administrators, admin plane): creating the team, with the requester as owner, or
dismissing the request. The requester learns the outcome by email and on their page."""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsAppAdmin
from apps.teams.models import Membership, Team

from . import emails
from .models import AccessRequest, InviteRequest, UserProfile, supported_language
from .serializers import _display_name

# Requests (for a team, or to an owner) one user may send in 24 hours: each one is an email.
REQUESTS_PER_DAY = 5


def check_daily_requests(user) -> None:
    since = timezone.now() - dt.timedelta(days=1)
    sent = (
        AccessRequest.objects.filter(requester=user, created_at__gte=since).count()
        + InviteRequest.objects.filter(requester=user, created_at__gte=since).count()
    )
    if sent >= REQUESTS_PER_DAY:
        raise serializers.ValidationError(
            {"detail": "Too many requests today.", "code": "too_many"}
        )


def language_of(user, fallback: str = "") -> str:
    return UserProfile.of(user).language or fallback


class MyTeamRequestSerializer(serializers.ModelSerializer):
    created_team_name = serializers.CharField(source="team.name", read_only=True, default=None)

    class Meta:
        model = InviteRequest
        fields = ["id", "team_name", "message", "status", "created_team_name", "created_at"]
        read_only_fields = ["status", "created_at"]

    def validate_team_name(self, name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise serializers.ValidationError("A name is needed.")
        return name


class MyTeamRequestViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The user's own requests for a team: `{team_name, message?}` asks the administrators;
    deleting a pending one withdraws it."""

    serializer_class = MyTeamRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return InviteRequest.objects.filter(requester=self.request.user).select_related("team")

    def perform_create(self, serializer):
        user = self.request.user
        if self.get_queryset().filter(status=InviteRequest.Status.PENDING).exists():
            raise serializers.ValidationError(
                {"detail": "A request is already waiting.", "code": "already_pending"}
            )
        check_daily_requests(user)
        serializer.save(
            requester=user,
            email=user.email,
            name=_display_name(user) or "",
            language=language_of(
                user, supported_language(self.request.headers.get("Accept-Language"))
            ),
        )

    def perform_destroy(self, request):
        if request.status != InviteRequest.Status.PENDING:
            raise serializers.ValidationError({"detail": "Only a waiting request."})
        request.delete()


class InviteRequestSerializer(serializers.ModelSerializer):
    handled_by_name = serializers.SerializerMethodField()
    created_team_name = serializers.CharField(source="team.name", read_only=True, default=None)

    class Meta:
        model = InviteRequest
        fields = [
            "id",
            "email",
            "name",
            "team_name",
            "message",
            "language",
            "status",
            "created_team_name",
            "created_at",
            "handled_at",
            "handled_by_name",
        ]
        read_only_fields = [f for f in fields if f != "status"]

    def get_handled_by_name(self, request) -> str | None:
        user = request.handled_by
        return (user.get_full_name() or user.email) if user else None


class InviteRequestViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """For administrators: the requests, waiting ones first (`?status=` narrows). POST
    `create-team/` `{name?}` creates the team; PATCH `status` dismisses a request (or reopens
    it). The requester is told by email."""

    serializer_class = InviteRequestSerializer
    permission_classes = [IsAppAdmin]

    def get_queryset(self):
        requests = InviteRequest.objects.select_related("handled_by", "requester", "team")
        wanted = self.request.query_params.get("status")
        if wanted in InviteRequest.Status.values:
            requests = requests.filter(status=wanted)
        return requests

    def perform_update(self, serializer):
        before = serializer.instance.status
        done = serializer.validated_data.get("status") != InviteRequest.Status.PENDING
        request = serializer.save(
            handled_at=timezone.now() if done else None,
            handled_by=self.request.user if done else None,
        )
        if (
            request.requester
            and before != request.status
            and request.status == InviteRequest.Status.DISMISSED
        ):
            emails.send(
                "team_declined",
                request.requester.email,
                language_of(request.requester, request.language),
                team=request.team_name,
            )

    @action(detail=True, methods=["post"], url_path="create-team")
    def create_team(self, request, pk=None):
        team_request = self.get_object()
        if team_request.requester is None or team_request.status != InviteRequest.Status.PENDING:
            raise serializers.ValidationError({"detail": "Only a waiting request for a team."})
        name = " ".join(str(request.data.get("name") or team_request.team_name).split())[:100]
        if not name:
            raise serializers.ValidationError({"name": "A name is needed."})
        with transaction.atomic():
            team = Team.objects.create(name=name)
            Membership.objects.create(
                user=team_request.requester, team=team, role=Membership.Role.OWNER
            )
            team_request.team = team
            team_request.status = InviteRequest.Status.HANDLED
            team_request.handled_at = timezone.now()
            team_request.handled_by = request.user
            team_request.save()
        emails.send(
            "team_created",
            team_request.requester.email,
            language_of(team_request.requester, team_request.language),
            url=f"{settings.APP_URL}/team",
            team=team.name,
        )
        return Response(InviteRequestSerializer(team_request).data, status=status.HTTP_201_CREATED)

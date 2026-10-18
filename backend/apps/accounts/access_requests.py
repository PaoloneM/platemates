"""Asking a team owner, known by email, to be let in (any signed-in user), and the owner's
answer.

The requester never learns whether the address belongs to an owner: the request is stored
and shown as waiting either way, and only a real owner receives it (by email and on their
Team page). Requests are limited per user and day (`team_requests.REQUESTS_PER_DAY`).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.teams.models import Membership, Team

from . import emails
from .models import AccessRequest
from .serializers import _display_name
from .team_requests import check_daily_requests, language_of


def find_owner(email: str):
    """The user with this verified address who owns a team, or None."""
    return (
        get_user_model()
        .objects.filter(
            email__iexact=email,
            profile__email_verified=True,
            membership__role=Membership.Role.OWNER,
            membership__team__is_system=False,
        )
        .distinct()
        .first()
    )


def notify_owner(request: AccessRequest) -> None:
    emails.send(
        "access_request",
        request.owner.email,
        language_of(request.owner),
        requester=_display_name(request.requester),
        requester_email=request.requester.email,
        message=request.message,
    )


def claim_waiting(user) -> int:
    """Hand an owner the waiting requests to their address that found no owner when sent
    (their address was not known to be verified yet, or they owned no team then), and email
    them about each. Run at login and when they look at their requests."""
    if find_owner(user.email) != user:
        return 0
    waiting = AccessRequest.objects.filter(
        owner__isnull=True, owner_email__iexact=user.email, status=AccessRequest.Status.PENDING
    ).exclude(requester=user)
    claimed = 0
    for request in waiting.select_related("requester"):
        request.owner = user
        request.save(update_fields=["owner"])
        notify_owner(request)
        claimed += 1
    return claimed


class MyAccessRequestSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True, default=None)

    class Meta:
        model = AccessRequest
        fields = ["id", "owner_email", "message", "status", "team_name", "created_at"]
        read_only_fields = ["status", "created_at"]

    def validate_owner_email(self, email: str) -> str:
        return email.strip().lower()


class ReceivedAccessRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    requester_email = serializers.EmailField(source="requester.email", read_only=True)

    class Meta:
        model = AccessRequest
        fields = ["id", "requester_name", "requester_email", "message", "created_at"]

    def get_requester_name(self, request) -> str | None:
        return _display_name(request.requester)


class AccessRequestViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The user's own requests (list, `{owner_email, message?}` to ask, delete to withdraw a
    waiting one); `received/` lists the waiting ones addressed to the user as owner, who
    answers with `accept/` `{team}` or `decline/`."""

    serializer_class = MyAccessRequestSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return AccessRequest.objects.filter(requester=self.request.user).select_related("team")

    def perform_create(self, serializer):
        user = self.request.user
        email = serializer.validated_data["owner_email"]
        if (
            self.get_queryset()
            .filter(owner_email=email, status=AccessRequest.Status.PENDING)
            .exists()
        ):
            raise serializers.ValidationError(
                {"owner_email": "Already asked.", "code": "already_pending"}
            )
        check_daily_requests(user)
        owner = find_owner(email)
        if owner == user:
            owner = None
        request = serializer.save(requester=user, owner=owner)
        if owner:
            notify_owner(request)

    def perform_destroy(self, request):
        if request.status != AccessRequest.Status.PENDING:
            raise serializers.ValidationError({"detail": "Only a waiting request."})
        request.delete()

    def _received(self):
        return AccessRequest.objects.filter(
            owner=self.request.user, status=AccessRequest.Status.PENDING
        ).select_related("requester")

    @action(detail=False, methods=["get"])
    def received(self, request):
        claim_waiting(request.user)
        return Response(ReceivedAccessRequestSerializer(self._received(), many=True).data)

    def _answer(self, pk):
        try:
            return self._received().get(pk=pk)
        except (AccessRequest.DoesNotExist, ValueError) as missing:
            raise NotFound() from missing

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        access = self._answer(pk)
        team = Team.objects.filter(
            pk=request.data.get("team"),
            is_system=False,
            memberships__user=request.user,
            memberships__role=Membership.Role.OWNER,
        ).first()
        if team is None:
            raise serializers.ValidationError({"team": "One of your teams."})
        with transaction.atomic():
            Membership.objects.get_or_create(
                user=access.requester, team=team, defaults={"role": Membership.Role.MEMBER}
            )
            access.status = AccessRequest.Status.ACCEPTED
            access.team = team
            access.decided_at = timezone.now()
            access.save()
        emails.send(
            "access_accepted",
            access.requester.email,
            language_of(access.requester),
            url=f"{settings.APP_URL}/",
            team=team.name,
            owner=_display_name(request.user),
        )
        return Response(MyAccessRequestSerializer(access).data)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        access = self._answer(pk)
        access.status = AccessRequest.Status.DECLINED
        access.decided_at = timezone.now()
        access.save()
        emails.send("access_declined", access.requester.email, language_of(access.requester))
        return Response(status=204)

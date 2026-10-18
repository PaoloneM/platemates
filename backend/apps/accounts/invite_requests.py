"""Asking for an invitation (anyone, from the sign-in page) and dealing with the requests
(administrators, admin plane).

The public endpoint must not become a way to fill the database or to probe who asked: it is
rate limited per address, a hidden field catches bots (their request is answered as any other
and dropped), an address already waiting is not stored twice, the pending queue has a ceiling,
and the answer is always the same 204, whatever happened.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.core.permissions import IsAppAdmin

from .models import InviteRequest, supported_language

# Pending requests beyond which new ones are dropped (administrators deal with the queue).
MAX_PENDING = 500


class RequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)
    # Left empty by people (the field is hidden); bots fill it in.
    website = serializers.CharField(required=False, allow_blank=True)


class InviteRequestThrottle(SimpleRateThrottle):
    """Per client address (`NUM_PROXIES`), signed in or not."""

    scope = "invite_request"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([InviteRequestThrottle])
def request_invite(request):
    """`{email, name?, message?}`: ask the administrators for an invitation. Always 204."""
    data = RequestSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    values = data.validated_data
    email = values["email"].strip().lower()
    pending = InviteRequest.objects.filter(status=InviteRequest.Status.PENDING)
    if (
        not values.get("website")
        and not pending.filter(email=email).exists()
        and pending.count() < MAX_PENDING
    ):
        InviteRequest.objects.create(
            email=email,
            name=" ".join((values.get("name") or "").split()),
            message=(values.get("message") or "").strip(),
            language=supported_language(request.headers.get("Accept-Language")),
        )
    return Response(status=status.HTTP_204_NO_CONTENT)


class InviteRequestSerializer(serializers.ModelSerializer):
    handled_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InviteRequest
        fields = [
            "id",
            "email",
            "name",
            "message",
            "language",
            "status",
            "created_at",
            "handled_at",
            "handled_by_name",
        ]
        read_only_fields = [f for f in fields if f != "status"]

    def get_handled_by_name(self, request) -> str | None:
        user = request.handled_by
        return (user.get_full_name() or user.email) if user else None


class InviteRequestViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """For administrators: the requests, waiting ones first (`?status=` narrows); PATCH
    `status` to handled or dismissed (or back to pending)."""

    serializer_class = InviteRequestSerializer
    permission_classes = [IsAppAdmin]

    def get_queryset(self):
        requests = InviteRequest.objects.select_related("handled_by")
        wanted = self.request.query_params.get("status")
        if wanted in InviteRequest.Status.values:
            requests = requests.filter(status=wanted)
        return requests

    def perform_update(self, serializer):
        done = serializer.validated_data.get("status") != InviteRequest.Status.PENDING
        serializer.save(
            handled_at=timezone.now() if done else None,
            handled_by=self.request.user if done else None,
        )

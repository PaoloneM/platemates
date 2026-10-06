from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.families.models import Membership
from apps.families.permissions import FamilyScopedMixin

from .models import Invitation, UserProfile, supported_language
from .oidc import enabled_identity_providers
from .serializers import InvitationPreviewSerializer, InvitationSerializer


@ensure_csrf_cookie
@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def me(request):
    """Who is signed in, and into which families. Also sets the CSRF cookie the SPA needs.

    Answers 200 for anonymous visitors too (`authenticated: false`), so the SPA can tell "not
    signed in" from "something is broken". PATCH updates the user's preferences (`language`).
    """
    user = request.user
    if not user.is_authenticated:
        if request.method == "PATCH":
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response({"authenticated": False})
    profile = UserProfile.of(user)
    if request.method == "PATCH":
        language = supported_language(request.data.get("language"))
        if not language:
            raise serializers.ValidationError({"language": "Unsupported language."})
        profile.language = language
        profile.save(update_fields=["language"])
    memberships = Membership.objects.filter(user=user).select_related("family")
    return Response(
        {
            "authenticated": True,
            "user": {
                "id": user.pk,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_staff": user.is_staff,
                "language": profile.language or None,
            },
            "families": [
                {"id": m.family_id, "name": m.family.name, "role": m.role} for m in memberships
            ],
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def login_options(request):
    """How the login screen may offer to sign in: always email/password, plus social providers."""
    return Response({"identity_providers": enabled_identity_providers()})


class InvitationViewSet(
    FamilyScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Owners invite people to their family. Deleting an invitation revokes it."""

    queryset = Invitation.objects.select_related("family")
    serializer_class = InvitationSerializer

    def check_family(self, family):
        super().check_family(family)
        if not Membership.objects.filter(
            user=self.request.user, family=family, role=Membership.Role.OWNER
        ).exists():
            raise serializers.ValidationError({"family": "Only owners can invite."})

    def perform_create(self, serializer):
        self.check_family(serializer.validated_data["family"])
        serializer.save(invited_by=self.request.user)

    def perform_destroy(self, instance):
        self.check_family(instance.family)
        if instance.state == Invitation.State.PENDING:
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at"])

    def _by_token(self, token):
        return Invitation.objects.select_related("family").filter(token=token or "").first()

    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-token/(?P<token>[\w-]+)",
        permission_classes=[IsAuthenticated],
    )
    def preview(self, request, token=None):
        invitation = self._by_token(token)
        if invitation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(InvitationPreviewSerializer(invitation).data)

    @preview.mapping.post
    def accept(self, request, token=None):
        invitation = self._by_token(token)
        if invitation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            membership = invitation.accept(request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc), "state": invitation.state}, status=status.HTTP_409_CONFLICT
            )
        return Response({"family": membership.family_id, "role": membership.role})

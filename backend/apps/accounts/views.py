from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.teams.models import Membership, Team
from apps.teams.permissions import TeamScopedMixin

from .models import Invitation, UserProfile, supported_language
from .oidc import enabled_identity_providers
from .serializers import InvitationPreviewSerializer, InvitationSerializer


@ensure_csrf_cookie
@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def me(request):
    """Who is signed in, and into which teams. Also sets the CSRF cookie the SPA needs.

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
    memberships = Membership.objects.filter(user=user).select_related("team")
    return Response(
        {
            "authenticated": True,
            "user": {
                "id": user.pk,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_staff": user.is_staff,
                "is_admin": profile.is_admin,
                "language": profile.language or None,
            },
            "teams": [{"id": m.team_id, "name": m.team.name, "role": m.role} for m in memberships],
            # Staff write the system team's recipes (the curated part of the community).
            "system_team": (
                Team.objects.filter(is_system=True).values_list("pk", flat=True).first()
                if user.is_staff
                else None
            ),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def login_options(request):
    """How the login screen may offer to sign in: always email/password, plus social providers."""
    return Response({"identity_providers": enabled_identity_providers()})


class InvitationViewSet(
    TeamScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Owners invite people to their team. Deleting an invitation revokes it."""

    queryset = Invitation.objects.select_related("team", "invited_by", "accepted_by")

    def get_queryset(self):
        queryset = super().get_queryset()
        if team := self.request.query_params.get("team"):
            queryset = queryset.filter(team_id=team)
        return queryset

    serializer_class = InvitationSerializer

    def check_team(self, team):
        super().check_team(team)
        if not Membership.objects.filter(
            user=self.request.user, team=team, role=Membership.Role.OWNER
        ).exists():
            raise serializers.ValidationError({"team": "Only owners can invite."})

    def perform_create(self, serializer):
        self.check_team(serializer.validated_data["team"])
        serializer.save(invited_by=self.request.user)

    def perform_destroy(self, instance):
        self.check_team(instance.team)
        if instance.state == Invitation.State.PENDING:
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at"])

    def _by_token(self, token):
        return Invitation.objects.select_related("team").filter(token=token or "").first()

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
        return Response({"team": membership.team_id, "role": membership.role})

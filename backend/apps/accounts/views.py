from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.planes import admin_powers, staff_powers
from apps.core.planes import current as current_plane
from apps.siteconfig.registry import MENU_LAYOUTS, public_values
from apps.teams.models import Membership, Team
from apps.teams.permissions import TeamScopedMixin

from .models import SHOPPING_APPS, THEMES, Invitation, UserProfile, supported_language
from .oidc import enabled_identity_providers
from .serializers import InvitationPreviewSerializer, InvitationSerializer


@ensure_csrf_cookie
@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def me(request):
    """Who is signed in, and into which teams. Also sets the CSRF cookie the SPA needs.

    Answers 200 for anonymous visitors too (`authenticated: false`), so the SPA can tell "not
    signed in" from "something is broken". PATCH updates the user's preferences (`language`,
    `theme`, `shopping_app`, `menu_layout`).
    """
    user = request.user
    if not user.is_authenticated:
        if request.method == "PATCH":
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response({"authenticated": False})
    profile = UserProfile.of(user)
    if request.method == "PATCH":
        changed = []
        if "language" in request.data:
            language = supported_language(request.data.get("language"))
            if not language:
                raise serializers.ValidationError({"language": "Unsupported language."})
            profile.language = language
            changed.append("language")
        if "theme" in request.data:
            if request.data["theme"] not in dict(THEMES):
                raise serializers.ValidationError({"theme": "system, light or dark."})
            profile.theme = request.data["theme"]
            changed.append("theme")
        if "menu_layout" in request.data:
            if request.data["menu_layout"] not in ("", *MENU_LAYOUTS):
                raise serializers.ValidationError({"menu_layout": "vertical, horizontal or ''."})
            profile.menu_layout = request.data["menu_layout"]
            changed.append("menu_layout")
        if "shopping_app" in request.data:
            if request.data["shopping_app"] not in dict(SHOPPING_APPS):
                raise serializers.ValidationError({"shopping_app": "Not a supported app."})
            profile.shopping_app = request.data["shopping_app"]
            changed.append("shopping_app")
        if not changed:
            raise serializers.ValidationError("Nothing to change.")
        profile.save(update_fields=changed)
    memberships = Membership.objects.filter(user=user).select_related("team")
    return Response(
        {
            "authenticated": True,
            "user": {
                "id": user.pk,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                # Powers, not roles: false on the public plane (apps/core/planes.py), so the
                # interface shows Gestione and staff controls only on the admin plane.
                "is_staff": staff_powers(user),
                "is_admin": admin_powers(user),
                "language": profile.language or None,
                "theme": profile.theme,
                "shopping_app": profile.shopping_app or None,
                # The user's own choice; null: the team's (in `teams`), or the application's.
                "menu_layout": profile.menu_layout or None,
            },
            "teams": [
                {
                    "id": m.team_id,
                    "name": m.team.name,
                    "role": m.role,
                    "menu_layout": m.team.menu_layout or None,
                }
                for m in memberships
            ],
            "plane": current_plane(),
            # Application settings the interface follows (`siteconfig`, `public` ones).
            "settings": public_values(),
            # Staff write the system team's recipes (the curated part of the community).
            "system_team": (
                Team.objects.filter(is_system=True).values_list("pk", flat=True).first()
                if staff_powers(user)
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

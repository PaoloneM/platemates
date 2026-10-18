import datetime as dt

from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.planes import admin_powers, staff_powers
from apps.core.planes import current as current_plane
from apps.siteconfig.registry import MENU_LAYOUTS, public_values
from apps.teams.models import Membership, Team
from apps.teams.permissions import TeamScopedMixin

from . import emails
from .models import SHOPPING_APPS, THEMES, Invitation, UserProfile, supported_language
from .oidc import enabled_identity_providers
from .serializers import (
    InvitationPreviewSerializer,
    InvitationSerializer,
    _display_name,
    mask_email,
)


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


# Emailed invitations a team may send in 24 hours.
INVITATION_EMAILS_PER_DAY = 20


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
        team = serializer.validated_data["team"]
        self.check_team(team)
        if serializer.validated_data.get("email"):
            self._check_daily_emails(team)
        invitation = serializer.save(invited_by=self.request.user)
        self.email_sent = self._send(invitation) if invitation.email else None

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data["email_sent"] = self.email_sent
        return response

    def _check_daily_emails(self, team) -> None:
        """Invitations go out under PlateMates' name: a ceiling per team keeps it from being a
        way to send mail to anyone."""
        since = timezone.now() - dt.timedelta(days=1)
        sent = Invitation.objects.filter(team=team, created_at__gte=since).exclude(email="")
        if sent.count() >= INVITATION_EMAILS_PER_DAY:
            raise serializers.ValidationError(
                {"email": "Too many invitations by email today.", "code": "too_many"}
            )

    def _send(self, invitation, message: str = "") -> bool:
        inviter = self.request.user
        language = getattr(getattr(inviter, "profile", None), "language", "") or (
            self.request.LANGUAGE_CODE
        )
        return emails.send(
            "invitation",
            invitation.email,
            language,
            url=f"{settings.APP_URL}/invite/{invitation.token}",
            inviter=_display_name(inviter),
            inviter_email=inviter.email,
            team=invitation.team.name,
            email=invitation.email,
            expires=invitation.expires_at.strftime("%d/%m/%Y"),
            message=message or self.request.data.get("message", "")[:500],
        )

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Send an invitation's email again (owners; pending invitations sent by email)."""
        invitation = self.get_object()
        self.check_team(invitation.team)
        if not invitation.email or invitation.state != Invitation.State.PENDING:
            raise serializers.ValidationError({"detail": "Only a pending emailed invitation."})
        self._check_daily_emails(invitation.team)
        return Response({"email_sent": self._send(invitation)})

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """Pending invitations sent to the user's own verified address: a way in for someone
        who signed up from the landing page, or lost the email."""
        profile = UserProfile.of(request.user)
        if not (profile.email_verified and request.user.email):
            return Response([])
        pending = [
            i
            for i in Invitation.objects.select_related("team", "invited_by").filter(
                email__iexact=request.user.email, accepted_at__isnull=True, revoked_at__isnull=True
            )
            if i.state == Invitation.State.PENDING
        ]
        return Response(
            [
                {
                    "token": i.token,
                    "team_name": i.team.name,
                    "invited_by_name": _display_name(i.invited_by),
                    "expires_at": i.expires_at,
                }
                for i in pending
            ]
        )

    def perform_destroy(self, instance):
        self.check_team(instance.team)
        if instance.state == Invitation.State.PENDING:
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at"])

    @staticmethod
    def _is_addressee(user, email: str) -> bool:
        return UserProfile.of(user).email_verified and user.email.lower() == email.lower()

    def _by_token(self, token):
        return (
            Invitation.objects.select_related("team", "invited_by")
            .filter(token=token or "")
            .first()
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-token/(?P<token>[\w-]+)",
        # Before signing in too: the sign-in page says who invited them, and to which team.
        # Accepting needs a signed-in user (checked in `accept`).
        permission_classes=[AllowAny],
    )
    def preview(self, request, token=None):
        invitation = self._by_token(token)
        if invitation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(InvitationPreviewSerializer(invitation).data)

    @preview.mapping.post
    def accept(self, request, token=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        invitation = self._by_token(token)
        if invitation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if invitation.email and not self._is_addressee(request.user, invitation.email):
            return Response(
                {"code": "wrong_account", "email_hint": mask_email(invitation.email)},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            membership = invitation.accept(request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc), "state": invitation.state}, status=status.HTTP_409_CONFLICT
            )
        return Response({"team": membership.team_id, "role": membership.role})

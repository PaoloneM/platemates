import logging

from django.utils import translation
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ai import AIError
from apps.families.models import Membership
from apps.recipes.models import Recipe

from .agent import run_turn
from .models import AssistantSession
from .serializers import AssistantSessionSerializer, MessageSerializer

log = logging.getLogger(__name__)


class AssistantSessionViewSet(
    mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """A user's conversations with the recipe assistant. Only their author sees them."""

    serializer_class = AssistantSessionSerializer

    def get_queryset(self):
        return AssistantSession.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        family = serializer.validated_data["family"]
        if not Membership.objects.filter(user=self.request.user, family=family).exists():
            raise serializers.ValidationError({"family": "Not one of your families."})
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        session = self.get_object()
        if session.status != AssistantSession.Status.OPEN:
            return Response({"detail": "This conversation is closed."}, status=409)
        message = MessageSerializer(data=request.data)
        message.is_valid(raise_exception=True)
        try:
            run_turn(session, message.validated_data["text"], language=translation.get_language())
        except AIError as exc:
            log.warning("assistant turn failed: %s", exc)
            return Response(
                {"detail": "The assistant is not available right now.", "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(self.get_serializer(session).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Mark the conversation as saved (with the recipe it produced) or abandoned."""
        session = self.get_object()
        recipe_id = request.data.get("recipe")
        if recipe_id:
            recipe = Recipe.objects.filter(pk=recipe_id, owner_family=session.family).first()
            if recipe is None:
                raise serializers.ValidationError({"recipe": "Recipe not found."})
            session.recipe = recipe
            session.status = AssistantSession.Status.SAVED
        else:
            session.status = AssistantSession.Status.ABANDONED
        session.save(update_fields=["recipe", "status", "updated_at"])
        return Response(self.get_serializer(session).data)

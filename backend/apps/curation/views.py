import logging

from django.db import transaction
from django.db.models import Count
from django.utils import translation
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from ai import AIError, get_chat_provider

from .drafting import dishes_for_theme
from .jobs import announce, notify_worker
from .models import SystemDraft
from .serializers import DraftRequestSerializer, SystemDraftDetailSerializer, SystemDraftSerializer

log = logging.getLogger(__name__)


class SystemDraftViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """System recipe drafts, for staff: request them, follow them, discard or retry them.
    Publishing is saving the recipe from the editor with `system_draft` set."""

    permission_classes = [IsAdminUser]
    queryset = SystemDraft.objects.select_related("requested_by")

    def get_serializer_class(self):
        return SystemDraftDetailSerializer if self.action == "retrieve" else SystemDraftSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if wanted := self.request.query_params.get("status"):
            queryset = queryset.filter(status__in=wanted.split(","))
        return queryset

    def create(self, request):
        data = DraftRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        language = (translation.get_language() or "it")[:2]
        dishes = data.validated_data["dishes"]
        if data.validated_data["theme"]:
            try:
                dishes = dishes_for_theme(
                    data.validated_data["theme"],
                    data.validated_data["count"],
                    language,
                    get_chat_provider(),
                )
            except (AIError, ValueError) as exc:
                log.warning("dishes for theme failed: %s", exc)
                return Response(
                    {"detail": "The model is not available right now.", "error": str(exc)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if not dishes:
                raise ValidationError({"theme": "No new dish found for this theme."})
        with transaction.atomic():
            drafts = SystemDraft.objects.bulk_create(
                SystemDraft(dish=dish, language=language, requested_by=request.user)
                for dish in dishes
            )
            notify_worker()
            transaction.on_commit(lambda: [announce(d, "queued") for d in drafts])
        return Response(
            SystemDraftSerializer(drafts, many=True).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False)
    def counts(self, request):
        """How many drafts are in each status, for the page's tabs."""
        rows = SystemDraft.objects.values("status").annotate(n=Count("pk"))
        counts = {status: 0 for status in SystemDraft.Status.values}
        counts.update({row["status"]: row["n"] for row in rows})
        return Response(counts)

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        draft = self.get_object()
        if draft.status in (SystemDraft.Status.RUNNING, SystemDraft.Status.PUBLISHED):
            raise ValidationError({"status": "Not while running or once published."})
        draft.status = SystemDraft.Status.DISCARDED
        draft.save(update_fields=["status"])
        return Response(SystemDraftSerializer(draft).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Queue a failed or discarded draft again, optionally for a reworded dish
        (`{"dish": ...}`). What the previous run found is cleared."""
        draft = self.get_object()
        if draft.status not in (SystemDraft.Status.FAILED, SystemDraft.Status.DISCARDED):
            raise ValidationError({"status": "Only failed or discarded drafts are retried."})
        dish = " ".join(str(request.data.get("dish", draft.dish)).split())[:200]
        if not dish:
            raise ValidationError({"dish": "Which dish?"})
        with transaction.atomic():
            draft.dish = dish
            draft.status = SystemDraft.Status.QUEUED
            draft.error = ""
            draft.sources, draft.draft = [], None
            draft.reliability, draft.agreement = "", None
            draft.web_rating = draft.web_rating_count = None
            draft.started_at = draft.finished_at = None
            draft.save()
            notify_worker()
            transaction.on_commit(lambda: announce(draft, "queued"))
        return Response(SystemDraftSerializer(draft).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Bring a discarded draft that had a recipe back to review, as it was."""
        draft = self.get_object()
        if draft.status != SystemDraft.Status.DISCARDED or not draft.draft:
            raise ValidationError({"status": "Only a discarded draft with a recipe is restored."})
        draft.status = SystemDraft.Status.READY
        draft.save(update_fields=["status"])
        return Response(SystemDraftSerializer(draft).data)

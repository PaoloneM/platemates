from django.db import transaction
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.recipes.models import Recipe, Visibility

from .models import Family, FamilyMember, Membership, Preference, RecipeBookEntry
from .permissions import FamilyScopedMixin
from .serializers import (
    FamilyMemberSerializer,
    FamilySerializer,
    PreferenceSerializer,
    RecipeBookEntrySerializer,
)


class FamilyViewSet(viewsets.ModelViewSet):
    serializer_class = FamilySerializer

    def get_queryset(self):
        return Family.objects.filter(memberships__user=self.request.user).prefetch_related(
            "members", "preferences", "tools"
        )

    def perform_create(self, serializer):
        # Access is invitation-only: new families are created by staff, everyone else joins one.
        if not self.request.user.is_staff:
            raise PermissionDenied("Only staff can create families; ask for an invitation.")
        family = serializer.save()
        Membership.objects.create(user=self.request.user, family=family, role=Membership.Role.OWNER)


class FamilyMemberViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    queryset = FamilyMember.objects.all()
    serializer_class = FamilyMemberSerializer


class PreferenceViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    queryset = Preference.objects.all()
    serializer_class = PreferenceSerializer


class RecipeBookEntryViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    """A family's recipe book. Filters: `?family=`, `?status=`, `?search=`, `?course=`.

    Removing an entry removes the recipe from the book; a private recipe that no family keeps
    any more is deleted with it, since nobody else could ever see it.
    """

    queryset = RecipeBookEntry.objects.select_related("recipe__cuisine").order_by("recipe__title")
    serializer_class = RecipeBookEntrySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if family := params.get("family"):
            queryset = queryset.filter(family_id=family)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if search := params.get("search", "").strip():
            queryset = queryset.filter(recipe__title__icontains=search)
        if course := params.get("course"):
            queryset = queryset.filter(recipe__course=course)
        return queryset

    def perform_create(self, serializer):
        self.check_family(serializer.validated_data["family"])
        recipe = serializer.validated_data["recipe"]
        if not Recipe.objects.visible_to(self.request.user).filter(pk=recipe.pk).exists():
            raise ValidationError({"recipe": "Recipe not found."})
        serializer.save()

    @transaction.atomic
    def perform_destroy(self, instance):
        recipe = instance.recipe
        instance.delete()
        if (
            recipe.visibility == Visibility.PRIVATE
            and not RecipeBookEntry.objects.filter(recipe=recipe).exists()
        ):
            recipe.delete()

from rest_framework import viewsets

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
        family = serializer.save()
        Membership.objects.create(user=self.request.user, family=family, role=Membership.Role.OWNER)


class FamilyMemberViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    queryset = FamilyMember.objects.all()
    serializer_class = FamilyMemberSerializer


class PreferenceViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    queryset = Preference.objects.all()
    serializer_class = PreferenceSerializer


class RecipeBookEntryViewSet(FamilyScopedMixin, viewsets.ModelViewSet):
    queryset = RecipeBookEntry.objects.select_related("recipe")
    serializer_class = RecipeBookEntrySerializer

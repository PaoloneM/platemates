"""Multi-family access: a user only ever sees the families they are a member of."""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import serializers

from .models import Family


def user_families(user) -> QuerySet[Family]:
    return Family.objects.filter(memberships__user=user)


class FamilyScopedMixin:
    """For viewsets over objects that belong to a family.

    `family_lookup` is the ORM path from the model to its family.
    """

    family_lookup = "family"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(**{f"{self.family_lookup}__memberships__user": self.request.user})

    def check_family(self, family: Family) -> None:
        if not user_families(self.request.user).filter(pk=family.pk).exists():
            raise serializers.ValidationError({"family": "Not one of your families."})

    def perform_create(self, serializer):
        self.check_family(serializer.validated_data["family"])
        serializer.save()

    def perform_update(self, serializer):
        if "family" in serializer.validated_data:
            self.check_family(serializer.validated_data["family"])
        serializer.save()

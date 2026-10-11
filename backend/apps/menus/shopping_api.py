"""The shopping lists' API: the weeks to prepare, generating and merging lists, ticking items.

Every change is announced to the team's browsers (`shopping`), so people shopping together see
each other's ticks; they reload the list from here (events are notices, never the data).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Ingredient, Unit
from apps.realtime.events import publish
from apps.teams.models import Team
from apps.teams.permissions import TeamScopedMixin, user_teams

from . import shopping
from .models import ShoppingItem, ShoppingList, WeeklyMenu


def announce(team_id: int, list_id: int | None) -> None:
    """Tell the team's browsers a list changed, once the change is saved."""
    transaction.on_commit(lambda: publish(team_id, "shopping", {"team": team_id, "list": list_id}))


class ShoppingItemSerializer(serializers.ModelSerializer):
    bought_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ShoppingItem
        fields = [
            "id",
            "shopping_list",
            "ingredient",
            "name",
            "category",
            "unit",
            "quantity",
            "optional",
            "needed_on",
            "note",
            "manual",
            "bought",
            "bought_at",
            "bought_by_name",
            "position",
        ]
        read_only_fields = ["optional", "needed_on", "manual", "bought_at", "position"]
        extra_kwargs = {"name": {"required": False}}

    def get_bought_by_name(self, item) -> str | None:
        user = item.bought_by
        return (user.first_name or user.email) if user else None

    def validate(self, attrs):
        if self.instance is not None:
            # An item stays in its list.
            attrs.pop("shopping_list", None)
        shopping_list = attrs.get("shopping_list") or getattr(self.instance, "shopping_list", None)
        ingredient = attrs.get("ingredient")
        usable = (
            ingredient is None
            or shopping_list is None
            or Ingredient.objects.usable_by(shopping_list.team).filter(pk=ingredient.pk).exists()
        )
        if not usable:
            raise serializers.ValidationError({"ingredient": "Not an ingredient of yours."})
        if self.instance is None:
            if not (attrs.get("name") or "").strip() and ingredient is None:
                raise serializers.ValidationError({"name": "Name what to buy."})
            if ingredient is not None:
                attrs.setdefault("name", ingredient.name)
                attrs.setdefault("category", ingredient.category)
                if "unit" not in attrs:
                    attrs["unit"] = ingredient.default_unit
        if "name" in attrs:
            attrs["name"] = " ".join(attrs["name"].split())
        if attrs.get("unit") == Unit.TO_TASTE:
            attrs["quantity"] = None
        return attrs


class ShoppingListSerializer(serializers.ModelSerializer):
    weeks = serializers.SerializerMethodField()
    total = serializers.IntegerField(read_only=True, default=0)
    bought = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ShoppingList
        fields = ["id", "team", "title", "weeks", "created_at", "total", "bought"]
        read_only_fields = ["team", "created_at"]

    def get_weeks(self, shopping_list) -> list[str]:
        return [m.week_start.isoformat() for m in shopping_list.menus.all()]

    def validate_title(self, title: str) -> str:
        title = " ".join(title.split())
        if not title:
            raise serializers.ValidationError("A list needs a title.")
        return title


class ShoppingListDetailSerializer(ShoppingListSerializer):
    items = ShoppingItemSerializer(many=True, read_only=True)

    class Meta(ShoppingListSerializer.Meta):
        fields = [*ShoppingListSerializer.Meta.fields, "items"]


class GenerateSerializer(serializers.Serializer):
    menu = serializers.PrimaryKeyRelatedField(queryset=WeeklyMenu.objects.all())


class MergeSerializer(serializers.Serializer):
    lists = serializers.PrimaryKeyRelatedField(
        queryset=ShoppingList.objects.all(), many=True, allow_empty=False
    )

    def validate_lists(self, lists):
        if len(set(lists)) < 2:
            raise serializers.ValidationError("Choose at least two lists.")
        if len({sl.team_id for sl in lists}) > 1:
            raise serializers.ValidationError("Lists of different teams cannot be merged.")
        return list(dict.fromkeys(lists))


class ShoppingListViewSet(
    TeamScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """`?team=` narrows the lists. Lists are made by `generate` (from a week's menu) and
    `merge`; renamed with PATCH `title`; deleting one makes its weeks available again."""

    team_lookup = "team"
    pagination_class = None

    def get_queryset(self):
        queryset = (
            ShoppingList.objects.annotate(
                total=Count("items", distinct=True),
                bought=Count("items", filter=Q(items__bought=True), distinct=True),
            )
            .prefetch_related("menus")
            .order_by("-created_at")
        )
        queryset = queryset.filter(team__memberships__user=self.request.user).distinct()
        team = self.request.query_params.get("team")
        return queryset.filter(team=team) if team and team.isdigit() else queryset

    def get_serializer_class(self):
        return ShoppingListDetailSerializer if self.action == "retrieve" else ShoppingListSerializer

    def get_object(self):
        obj = super().get_object()
        if self.action == "retrieve":
            obj = ShoppingList.objects.prefetch_related("menus", "items__bought_by").get(pk=obj.pk)
            obj.total = obj.items.count()
            obj.bought = obj.items.filter(bought=True).count()
        return obj

    def perform_update(self, serializer):
        shopping_list = serializer.save()
        announce(shopping_list.team_id, shopping_list.pk)

    def perform_destroy(self, instance):
        team_id, list_id = instance.team_id, instance.pk
        instance.delete()
        announce(team_id, list_id)

    def _team(self) -> Team:
        team = (
            user_teams(self.request.user).filter(pk=self.request.query_params.get("team")).first()
        )
        if team is None:
            raise serializers.ValidationError({"team": "Not one of your teams."})
        return team

    @action(detail=False, methods=["get"])
    def weeks(self, request):
        """`?team=`: the weeks from the current one on with something to buy and no list."""
        team = self._team()
        return Response(
            [
                {"menu": menu.pk, "week_start": menu.week_start.isoformat()}
                for menu in shopping.weeks_to_prepare(team)
            ]
        )

    @action(detail=False, methods=["post"])
    def generate(self, request):
        """`{menu}`: a new list with what that week's menu needs now (each call a new list)."""
        data = GenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        menu = data.validated_data["menu"]
        if not user_teams(request.user).filter(pk=menu.team_id).exists():
            raise serializers.ValidationError({"menu": "Not a menu of yours."})
        shopping_list = shopping.snapshot(menu, user=request.user)
        announce(menu.team_id, shopping_list.pk)
        return Response(
            ShoppingListSerializer(self.get_queryset().get(pk=shopping_list.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"])
    def merge(self, request):
        """`{lists: [ids]}`: one list from them, which are deleted (see shopping.merge)."""
        data = MergeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        lists = data.validated_data["lists"]
        if not user_teams(request.user).filter(pk=lists[0].team_id).exists():
            raise serializers.ValidationError({"lists": "Not lists of yours."})
        merged = shopping.merge(lists, user=request.user)
        announce(merged.team_id, merged.pk)
        return Response(
            ShoppingListSerializer(self.get_queryset().get(pk=merged.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class ShoppingItemViewSet(
    TeamScopedMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Items added by hand (POST, `manual`), corrected or ticked (PATCH `bought`), removed."""

    queryset = ShoppingItem.objects.select_related("shopping_list", "bought_by")
    serializer_class = ShoppingItemSerializer
    team_lookup = "shopping_list__team"

    def perform_create(self, serializer):
        shopping_list = serializer.validated_data.get("shopping_list")
        if shopping_list is None:
            raise serializers.ValidationError({"shopping_list": "Which list?"})
        self.check_team(shopping_list.team)
        last = shopping_list.items.order_by("-position").values_list("position", flat=True).first()
        item = serializer.save(manual=True, position=(last or 0) + 1)
        announce(shopping_list.team_id, item.shopping_list_id)

    def perform_update(self, serializer):
        bought = serializer.validated_data.get("bought")
        extra = {}
        if bought is not None and bought != serializer.instance.bought:
            extra = (
                {"bought_at": timezone.now(), "bought_by": self.request.user}
                if bought
                else {"bought_at": None, "bought_by": None}
            )
        item = serializer.save(**extra)
        announce(item.shopping_list.team_id, item.shopping_list_id)

    def perform_destroy(self, instance):
        team_id, list_id = instance.shopping_list.team_id, instance.shopping_list_id
        instance.delete()
        announce(team_id, list_id)

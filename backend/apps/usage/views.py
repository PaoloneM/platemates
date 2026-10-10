"""Usage and estimated costs, and the price list (Management > Usage, administrators)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import IsAppAdmin

from .models import AIUsage, ModelPrice

COUNTS = [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "web_searches",
]
MILLION = Decimal(1_000_000)


def cost_of(row: dict[str, Any], price: ModelPrice | None) -> Decimal | None:
    """USD, from a row's sums. None when the model has no price (a local model, or one the
    list lacks)."""
    if price is None:
        return None
    tokens = (
        row["input_tokens"] * price.input_per_mtok
        + row["output_tokens"] * price.output_per_mtok
        + row["cache_read_tokens"] * price.cache_read_per_mtok
        + row["cache_write_tokens"] * price.cache_write_per_mtok
    ) / MILLION
    return tokens + row["web_searches"] * price.per_thousand_searches / 1000


def _month(value: str | None) -> dt.date:
    try:
        year, month = (int(p) for p in (value or "").split("-"))
        return dt.date(year, month, 1)
    except ValueError:
        today = timezone.localdate()
        return today.replace(day=1)


def _group(rows, key) -> list[dict[str, Any]]:
    groups: dict[Any, dict[str, Any]] = {}
    for row in rows:
        k = key(row)
        group = groups.setdefault(
            k, {"calls": 0, **dict.fromkeys(COUNTS, 0), "cost": Decimal(0), "unpriced_calls": 0}
        )
        group["calls"] += row["calls"]
        for name in COUNTS:
            group[name] += row[name]
        if row["cost"] is None:
            group["unpriced_calls"] += row["calls"]
        else:
            group["cost"] += row["cost"]
    return [{"key": k, **v, "cost": round(v["cost"], 4)} for k, v in groups.items()]


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def usage_view(request):
    """`?month=YYYY-MM` (default: this month): calls, tokens, web searches and estimated cost,
    by team, by feature and by model; and which months have data."""
    month = _month(request.query_params.get("month"))
    prices = {p.model: p for p in ModelPrice.objects.all()}
    rows = list(
        AIUsage.objects.filter(created_at__year=month.year, created_at__month=month.month)
        .values("team_id", "team__name", "feature", "provider", "model")
        .annotate(calls=Count("id"), **{name: Sum(name) for name in COUNTS})
    )
    for row in rows:
        row["cost"] = cost_of(row, prices.get(row["model"]))

    by_team = _group(rows, lambda r: (r["team_id"], r["team__name"]))
    features_of_team: dict[Any, dict[str, Any]] = defaultdict(dict)
    for row in _group(rows, lambda r: (r["team_id"], r["feature"])):
        features_of_team[row["key"][0]][row["key"][1]] = row["cost"]
    months = (
        AIUsage.objects.annotate(month=TruncMonth("created_at"))
        .values_list("month", flat=True)
        .distinct()
        .order_by("-month")
    )
    totals = _group(rows, lambda r: "all")
    return Response(
        {
            "month": f"{month:%Y-%m}",
            "months": [f"{m:%Y-%m}" for m in months],
            "totals": totals[0] if totals else None,
            "teams": sorted(
                (
                    {
                        **{k: v for k, v in g.items() if k != "key"},
                        "team_id": g["key"][0],
                        "team": g["key"][1],
                        "features": features_of_team[g["key"][0]],
                    }
                    for g in by_team
                ),
                key=lambda g: -g["cost"],
            ),
            "features": sorted(
                ({**g, "feature": g.pop("key")} for g in _group(rows, lambda r: r["feature"])),
                key=lambda g: -g["cost"],
            ),
            "models": sorted(
                (
                    {
                        **{k: v for k, v in g.items() if k != "key"},
                        "provider": g["key"][0],
                        "model": g["key"][1],
                        "priced": g["key"][1] in prices,
                    }
                    for g in _group(rows, lambda r: (r["provider"], r["model"]))
                ),
                key=lambda g: -g["cost"],
            ),
        }
    )


class ModelPriceSerializer(serializers.ModelSerializer):
    updated_by = serializers.CharField(source="updated_by.email", read_only=True, default=None)

    class Meta:
        model = ModelPrice
        fields = [
            "id",
            "model",
            "input_per_mtok",
            "output_per_mtok",
            "cache_read_per_mtok",
            "cache_write_per_mtok",
            "per_thousand_searches",
            "updated_at",
            "updated_by",
        ]
        read_only_fields = ["updated_at", "updated_by"]


class ModelPriceViewSet(viewsets.ModelViewSet):
    """The price list costs are estimated from. Administrators only."""

    queryset = ModelPrice.objects.select_related("updated_by")
    serializer_class = ModelPriceSerializer
    permission_classes = [IsAppAdmin]
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

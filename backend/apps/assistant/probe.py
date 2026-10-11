"""Search probe (Manage, administrators): how recipe search reads a request and ranks the
recipes, with the `search.*` settings or other values to try, to tune them. Read only; like
`manage.py search_probe`."""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ai import get_chat_provider
from apps.core.permissions import IsAppAdmin
from apps.usage.context import attribute
from apps.usage.models import Feature

from . import search

LANGUAGES = {"it": "Italian", "en": "English"}


class ProbeSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)
    # Skip the chat model: the request as typed (what happens when it is unavailable).
    plain = serializers.BooleanField(default=False)
    language = serializers.ChoiceField(choices=list(LANGUAGES), default="it")
    # Hundredths, as the settings; absent: the current setting.
    min_similarity = serializers.IntegerField(min_value=0, max_value=100, required=False)
    margin = serializers.IntegerField(min_value=0, max_value=100, required=False)
    keyword_bonus = serializers.IntegerField(min_value=0, max_value=100, required=False)


@api_view(["POST"])
@permission_classes([IsAppAdmin])
def probe_view(request):
    """`{text, plain?, language?, min_similarity?, margin?, keyword_bonus?}`: the request as
    read, the values used, and every candidate ranked, `kept` for those offered. Among the
    recipes the requesting administrator can see."""
    data = ProbeSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    values = data.validated_data
    current = search.Tuning.current()
    tuning = search.Tuning(
        *(
            values[name] / 100 if name in values else getattr(current, name)
            for name in ("min_similarity", "margin", "keyword_bonus")
        )
    )
    with attribute(team=None, feature=Feature.OTHER):
        read = (
            search.plain_request(values["text"])
            if values["plain"]
            else search.understand(
                values["text"], LANGUAGES[values["language"]], get_chat_provider()
            )
        )
        ranked = search.rank(request.user, read, tuning)
    return Response(
        {
            "request": {
                "query": read.query,
                "keywords": read.keywords,
                "dishes": read.dishes,
                "exclude_categories": read.exclude_categories,
                "exclude_ingredients": read.exclude_ingredients,
            },
            "tuning": {
                name: round(getattr(tuning, name) * 100)
                for name in ("min_similarity", "margin", "keyword_bonus")
            },
            "results": [
                {
                    "recipe": s.recipe.pk,
                    "title": s.recipe.title,
                    "similarity": round(s.similarity, 3),
                    "keyword": s.keyword,
                    "score": round(s.score, 3),
                    "kept": s.kept,
                }
                for s in ranked
            ],
        }
    )

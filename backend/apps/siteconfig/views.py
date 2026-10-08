from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.cache import cache_manager
from apps.core.permissions import IsAppAdmin

from .models import ConfigVar
from .registry import SETTINGS


def _describe(setting, row: ConfigVar | None) -> dict:
    updated_by = row.updated_by if row else None
    return {
        "key": setting.key,
        "kind": setting.kind,
        "group": setting.group,
        "default": setting.default,
        "minimum": setting.minimum,
        "maximum": setting.maximum,
        "value": row.value if row else setting.default,
        "is_default": row is None,
        "updated_at": row.updated_at if row else None,
        "updated_by": (updated_by.get_full_name() or updated_by.email) if updated_by else None,
    }


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def config_list(request):
    """Every setting with its current value; administrators only."""
    rows = {row.key: row for row in ConfigVar.objects.select_related("updated_by")}
    return Response([_describe(s, rows.get(s.key)) for s in SETTINGS.values()])


@api_view(["PUT", "DELETE"])
@permission_classes([IsAppAdmin])
def config_detail(request, key):
    """PUT `{"value": ...}` sets a value; DELETE brings the setting back to its default."""
    setting = SETTINGS.get(key)
    if setting is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        ConfigVar.objects.filter(key=key).delete()
        return Response(_describe(setting, None))
    try:
        value = setting.clean(request.data.get("value"))
    except ValueError as exc:
        raise serializers.ValidationError({"value": str(exc)}) from None
    if value == setting.default:
        ConfigVar.objects.filter(key=key).delete()
        return Response(_describe(setting, None))
    row, _ = ConfigVar.objects.update_or_create(
        key=key, defaults={"value": value, "updated_by": request.user}
    )
    return Response(_describe(setting, row))


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def cache_stats(request):
    """What the cache holds and how it is doing; administrators only."""
    return Response(cache_manager.stats())


@api_view(["POST"])
@permission_classes([IsAppAdmin])
def cache_clear(request):
    """Empty the cache: Redis, and this process's memory (the others follow within seconds)."""
    cache_manager.clear(by=request.user.get_full_name() or request.user.email)
    return Response(cache_manager.stats())

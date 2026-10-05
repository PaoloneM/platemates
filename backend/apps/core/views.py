from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ai import get_chat_provider, get_embedding_provider


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Liveness of the backend and the services it depends on.

    `?deep=1` also queries the AI providers, for authenticated users only.
    """
    report: dict[str, object] = {"backend": {"ok": True}}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        report["database"] = {"ok": True}
    except Exception as exc:
        report["database"] = {"ok": False, "error": str(exc)}
    if request.query_params.get("deep") and request.user.is_authenticated:
        report["llm"] = get_chat_provider().health()
        report["embeddings"] = get_embedding_provider().health()
    return Response(report)

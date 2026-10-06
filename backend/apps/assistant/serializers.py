from rest_framework import serializers

from apps.catalog.matching import match_ingredient

from .models import AVAILABLE_MODES, AssistantSession


class AssistantSessionSerializer(serializers.ModelSerializer):
    transcript = serializers.SerializerMethodField()
    # For each draft ingredient, the catalog entry it matches (or candidates), in draft order.
    matches = serializers.SerializerMethodField()

    class Meta:
        model = AssistantSession
        fields = [
            "id",
            "family",
            "mode",
            "status",
            "recipe",
            "draft",
            "matches",
            "transcript",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "recipe", "draft", "created_at", "updated_at"]

    def get_transcript(self, session) -> list[dict]:
        """What the user sees: their messages and the assistant's text, plus where a draft came."""
        out = []
        for message in session.messages:
            if message["role"] == "user":
                out.append({"role": "user", "text": message["content"]})
            elif message["role"] == "assistant":
                out.append(
                    {
                        "role": "assistant",
                        "text": message.get("content") or "",
                        "draft": bool(message.get("tool_calls")),
                    }
                )
        return out

    def get_matches(self, session) -> list[dict]:
        if not session.draft:
            return []
        return [match_ingredient(line["name"]) for line in session.draft["ingredients"]]

    def validate_mode(self, mode):
        if mode not in AVAILABLE_MODES:
            raise serializers.ValidationError("This mode is not available yet.")
        return mode


class MessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000)

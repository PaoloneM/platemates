from rest_framework import serializers

from apps.catalog.matching import match_ingredient

from .models import AVAILABLE_MODES, AssistantSession


class AssistantSessionSerializer(serializers.ModelSerializer):
    transcript = serializers.SerializerMethodField()
    # For each draft ingredient, the catalog entry it matches (or candidates), in draft order.
    matches = serializers.SerializerMethodField()
    # Photos of the conversation and the text read from them, for the review screen.
    attachments = serializers.SerializerMethodField()

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
            "attachments",
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
                entry = {"role": "user", "text": message["content"]}
                if message.get("attachment"):
                    entry["attachment"] = message["attachment"]
                    entry["text"] = message["content"].removesuffix("[photo]").strip()
                out.append(entry)
            elif message["role"] == "assistant":
                entry = {
                    "role": "assistant",
                    "text": message.get("content") or "",
                    "draft": bool(message.get("tool_calls")),
                }
                if "results" in message:
                    entry["results"] = message["results"]
                    entry["text"] = ""
                if message.get("notice"):
                    entry["notice"] = message["notice"]
                if message.get("error"):
                    # The UI shows a translated explanation instead of the raw text.
                    entry["error"] = message["error"]
                    entry["text"] = ""
                out.append(entry)
        return out

    def get_attachments(self, session) -> list[dict]:
        return [
            {"id": a.pk, "transcription": a.transcription}
            for a in session.attachments.only("id", "transcription")
        ]

    def get_matches(self, session) -> list[dict]:
        if not session.draft:
            return []
        return [match_ingredient(line["name"]) for line in session.draft["ingredients"]]

    def validate_mode(self, mode):
        if mode not in AVAILABLE_MODES:
            raise serializers.ValidationError("This mode is not available yet.")
        return mode


# What the browser sends after downscaling (JPEG); the others are accepted as they come.
IMAGE_TYPES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG", "image/webp": b"RIFF"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class MessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    image = serializers.FileField(required=False)

    def validate_image(self, image):
        if image.size > MAX_IMAGE_BYTES:
            raise serializers.ValidationError("Image too large.")
        signature = IMAGE_TYPES.get(image.content_type)
        head = image.read(4)
        image.seek(0)
        # Check the bytes, not just the declared type.
        if signature is None or not head.startswith(signature[:4]):
            raise serializers.ValidationError("Only JPEG, PNG or WebP images.")
        return image

    def validate(self, attrs):
        if not attrs.get("text", "").strip() and not attrs.get("image"):
            raise serializers.ValidationError("Send a text or a photo.")
        return attrs

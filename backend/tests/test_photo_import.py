import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from ai import ChatResult
from apps.assistant.agent import run_turn
from apps.assistant.models import AssistantSession, Attachment, Mode

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
CARD = (
    "Torta di mele della nonna\n(per 6 persone)\n- 3 mele\n- 200 g farina\n"
    "Forno 180° per 45 minuti."
)
DRAFT = {
    "title": "Torta di mele della nonna",
    "servings": 6,
    "course": "dessert",
    "ingredients": [
        {
            "name": "mela",
            "quantity": 3,
            "unit": "pc",
            "category": "fruit",
            "season_months": [9, 10, 11],
        }
    ],
    "steps": ["Forno 180° per 45 minuti."],
}


class FakeChat:
    model = "fake"

    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        return self.results.pop(0)


@pytest.fixture
def session(family, user):
    return AssistantSession.objects.create(family=family, user=user, mode=Mode.PHOTO)


def photo_of(session):
    return Attachment.objects.create(session=session, content_type="image/jpeg", data=JPEG)


def test_photo_is_transcribed_then_structured(session):
    vision = FakeChat(ChatResult(content=CARD))
    chat = FakeChat(ChatResult(content=json.dumps(DRAFT)))
    photo = photo_of(session)
    result = run_turn(session, "", photo=photo, chat=chat, vision=vision)
    session.refresh_from_db()
    photo.refresh_from_db()

    assert result.draft_updated and result.error is None
    assert photo.transcription == CARD
    assert session.draft["title"] == "Torta di mele della nonna"
    # The image went to the vision model with the literal-transcription prompt...
    [message] = vision.sent[0][0]
    assert "word for word" in message["content"][0]["text"]
    assert message["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # ...and only its transcription to the structuring call.
    assert CARD in chat.sent[0][0][1]["content"]
    assert [m["role"] for m in session.messages] == ["user", "assistant", "tool"]
    assert session.messages[0]["attachment"] == photo.pk


def test_a_photo_without_text(session):
    result = run_turn(
        session,
        "",
        photo=photo_of(session),
        chat=FakeChat(),
        vision=FakeChat(ChatResult(content="NO TEXT")),
    )
    assert result.error == "no_text_in_photo"


def test_pages_of_one_recipe_are_read_together(session):
    vision = FakeChat(
        ChatResult(content="Pagina uno: ingredienti " * 3),
        ChatResult(content="Pagina due: procedimento " * 3),
    )
    chat = FakeChat(ChatResult(content=json.dumps(DRAFT)), ChatResult(content=json.dumps(DRAFT)))
    run_turn(session, "", photo=photo_of(session), chat=chat, vision=vision)
    run_turn(session, "seconda pagina", photo=photo_of(session), chat=chat, vision=vision)
    second_text = chat.sent[1][0][1]["content"]
    assert "Pagina uno" in second_text and "Pagina due" in second_text


def test_corrections_after_a_photo_use_the_chat_model(session):
    corrected = {**DRAFT, "servings": 8}
    call = {"id": "c", "function": {"name": "propose_recipe", "arguments": json.dumps(corrected)}}
    chat = FakeChat(
        ChatResult(content=json.dumps(DRAFT)), ChatResult(content="", tool_calls=[call])
    )
    run_turn(
        session, "", photo=photo_of(session), chat=chat, vision=FakeChat(ChatResult(content=CARD))
    )
    run_turn(session, "per 8", chat=chat)
    session.refresh_from_db()
    assert session.draft["servings"] == 8
    # The attachment id stays local: the model gets plain messages.
    assert all("attachment" not in m for m in chat.sent[1][0])


# -- API --------------------------------------------------------------------------------------


@pytest.fixture
def fakes(monkeypatch):
    vision = FakeChat(ChatResult(content=CARD))
    chat = FakeChat(ChatResult(content=json.dumps(DRAFT)))
    monkeypatch.setattr("apps.assistant.agent.get_vision_provider", lambda: vision)
    monkeypatch.setattr("apps.assistant.agent.get_chat_provider", lambda: chat)
    return vision, chat


def upload(api, session, data=JPEG, content_type="image/jpeg", **extra):
    image = SimpleUploadedFile("photo.jpg", data, content_type=content_type)
    return api.post(
        f"/api/assistant/sessions/{session.pk}/messages/",
        {"image": image, **extra},
        format="multipart",
    )


def test_upload_through_the_api(api, session, fakes):
    response = upload(api, session, text="la torta della nonna")
    assert response.status_code == 200, response.json()
    data = response.json()
    [first, _] = data["transcript"]
    assert first["text"] == "la torta della nonna"
    assert data["attachments"] == [{"id": first["attachment"], "transcription": CARD}]
    image = api.get(f"/api/assistant/sessions/{session.pk}/attachments/{first['attachment']}/")
    assert image.status_code == 200
    assert image["Content-Type"] == "image/jpeg"
    assert image.content == JPEG


def test_only_real_images_are_accepted(api, session, fakes):
    assert (
        upload(api, session, data=b"<html>not an image", content_type="image/jpeg").status_code
        == 400
    )
    assert upload(api, session, data=JPEG, content_type="application/pdf").status_code == 400
    assert Attachment.objects.count() == 0


def test_photos_are_private_to_the_author(api, session, fakes):
    upload(api, session)
    photo = Attachment.objects.get()
    stranger = APIClient()
    stranger.force_authenticate(get_user_model().objects.create_user("eve"))
    url = f"/api/assistant/sessions/{session.pk}/attachments/{photo.pk}/"
    assert stranger.get(url).status_code == 404


def test_a_message_needs_text_or_a_photo(api, session):
    response = api.post(
        f"/api/assistant/sessions/{session.pk}/messages/", {"text": " "}, format="json"
    )
    assert response.status_code == 400

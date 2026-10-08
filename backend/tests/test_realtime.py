import asyncio
import json

import httpx
import pytest
from django.test import Client

from ai import AIUnavailableError
from ai.openai_compatible import OpenAICompatibleChat
from apps.realtime import events, server


def sse(*chunks, done=True):
    lines = [f"data: {json.dumps({'choices': [{'delta': delta}]})}" for delta in chunks]
    if done:
        lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def streaming_chat(body, status=200):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status, text=body, headers={"content-type": "text/event-stream"}
        )
    )
    client = httpx.Client(base_url="http://llm", transport=transport)
    return OpenAICompatibleChat(base_url="http://llm", model="m", client=client)


def test_a_streamed_answer_is_collected_and_reported_piece_by_piece():
    chat = streaming_chat(
        sse(
            {"role": "assistant"},
            {"reasoning_content": "Hmm"},
            {"content": '{"a"'},
            {"content": ": 1}"},
        )
    )
    pieces = []
    result = chat.chat_stream([], on_delta=lambda kind, text: pieces.append((kind, text)))
    assert result.content == '{"a": 1}'
    assert pieces == [("reasoning", "Hmm"), ("content", '{"a"'), ("content", ": 1}")]


def test_a_streamed_call_stops_at_the_deadline():
    chat = streaming_chat(sse({"content": "x"}, {"content": "y"}))
    with pytest.raises(AIUnavailableError, match="longer than the time allowed"):
        chat.chat_stream([], on_delta=lambda kind, text: None, deadline=0)


def test_the_caller_can_stop_a_streamed_call():
    chat = streaming_chat(sse({"content": "x"}, {"content": "y"}))

    def stop(kind, text):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        chat.chat_stream([], on_delta=stop)


def test_a_streamed_call_reports_server_errors():
    chat = streaming_chat('{"detail": "no model"}', status=503)
    with pytest.raises(Exception, match="not available"):
        chat.chat_stream([], on_delta=lambda kind, text: None)


def test_events_go_to_the_teams_room(realtime_events):
    events.publish(7, "generation", {"phase": "queued"})
    assert realtime_events == [("team-7", "generation", {"phase": "queued"})]


def test_sending_never_fails_the_caller(monkeypatch):
    def broken(*args):
        raise ConnectionError("no redis")

    monkeypatch.setattr(events, "_emit", broken)
    events.publish(7, "generation", {})  # logged, not raised


@pytest.fixture(autouse=True)
def keep_test_connection(monkeypatch):
    """The server refreshes its database connection around each login; in a test that would
    close the connection holding the test's transaction."""
    monkeypatch.setattr(server, "close_old_connections", lambda: None)


def session_cookie(user):
    client = Client()
    client.force_login(user)
    return f"other=1; sessionid={client.cookies['sessionid'].value}"


def test_a_signed_in_user_joins_the_rooms_of_their_teams(team, user):
    assert server.rooms_of(session_cookie(user)) == (user.pk, [f"team-{team.pk}"])


@pytest.mark.parametrize("cookie", ["", "sessionid=forged", "csrftoken=x"])
def test_without_a_valid_session_nobody_joins(db, cookie):
    assert server.rooms_of(cookie) is None


def test_the_socket_refuses_anonymous_connections(db):
    import socketio

    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        asyncio.run(server.connect("sid", {"HTTP_COOKIE": ""}))


def test_the_socket_accepts_only_the_apps_origins(settings):
    assert server.sio.eio.cors_allowed_origins == settings.REALTIME_ALLOWED_ORIGINS

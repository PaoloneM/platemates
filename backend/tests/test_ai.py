import json

import httpx
import pytest

from ai.base import AIUnavailableError, AuthError, ModelNotLoadedError
from ai.openai_compatible import OpenAICompatibleChat, OpenAICompatibleEmbeddings
from ai.studio import StudioChat


def make(cls, handler, **kwargs):
    client = httpx.Client(base_url="http://ai.test", transport=httpx.MockTransport(handler))
    return cls(base_url="http://ai.test", model="m", api_key="k", client=client, **kwargs)


def test_chat_returns_content_and_tool_calls():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": " hi ", "tool_calls": [{"id": "1"}]},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    result = make(OpenAICompatibleChat, handler).chat([{"role": "user", "content": "x"}])
    assert result.content == "hi"
    assert result.tool_calls == [{"id": "1"}]
    assert seen["auth"] == "Bearer k"


def test_studio_sends_its_extra_flags():
    bodies = []

    def handler(request):
        bodies.append(request.read())
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    make(StudioChat, handler, enable_thinking=True).chat([])
    assert b'"enable_thinking":true' in bodies[0].replace(b" ", b"")


def test_embeddings_keep_input_order():
    def handler(request):
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]}
        )

    assert make(OpenAICompatibleEmbeddings, handler).embed(["a", "b"]) == [[1.0], [2.0]]


@pytest.mark.parametrize(("status", "error"), [(401, AuthError), (503, ModelNotLoadedError)])
def test_http_errors_are_mapped(status, error):
    provider = make(OpenAICompatibleChat, lambda r: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(error):
        provider.chat([])


def test_unreachable_provider_reports_unhealthy_without_raising():
    def handler(request):
        raise httpx.ConnectError("down")

    provider = make(StudioChat, handler)
    with pytest.raises(AIUnavailableError):
        provider.chat([])
    assert provider.health()["ok"] is False


def test_studio_tools_are_restricted_to_web_search():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.read()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    make(StudioChat, handler, enable_tools=True, max_tool_calls=2).chat([])
    make(StudioChat, handler).chat([])
    with_tools, without = bodies
    assert with_tools["enabled_tools"] == ["web_search"]  # never python/terminal/edit_file
    assert with_tools["max_tool_calls_per_message"] == 2
    assert without["enable_tools"] is False and "enabled_tools" not in without

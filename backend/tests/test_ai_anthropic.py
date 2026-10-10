"""The Claude adapter: OpenAI-format requests in, Claude's API out, and back."""

import json

import httpx
import pytest

from ai.anthropic import (
    AnthropicChat,
    from_anthropic_response,
    structured_schema,
    to_anthropic_messages,
)
from ai.base import AIUnavailableError, AuthError


def make(handler, **kwargs):
    client = httpx.Client(base_url="http://ai.test", transport=httpx.MockTransport(handler))
    return AnthropicChat(base_url="http://ai.test", model="m", api_key="k", client=client, **kwargs)


def reply(*blocks, stop="end_turn"):
    return httpx.Response(200, json={"content": list(blocks), "stop_reason": stop})


def test_a_chat_is_sent_in_claude_format():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.read())
        return reply({"type": "text", "text": " ciao "})

    result = make(handler).chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}],
        temperature=0.3,
    )
    assert result.content == "ciao"
    assert result.finish_reason == "stop"
    assert seen["headers"]["x-api-key"] == "k"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["system"] == "Be brief."
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    # Refused by Claude 4.7 and later: never sent.
    assert "temperature" not in body
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] > 0


def test_tool_calls_and_results_round_trip():
    history = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "una ricetta"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "import-3",
                    "type": "function",
                    "function": {"name": "propose_recipe", "arguments": '{"title": "Zuppa"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "import-3", "content": "Shown."},
        {"role": "user", "content": "più sale"},
    ]
    system, turns = to_anthropic_messages(history)
    assert system == "s"
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["content"] == [
        {
            "type": "tool_use",
            "id": "import-3",
            "name": "propose_recipe",
            "input": {"title": "Zuppa"},
        }
    ]
    # The result leads the next user turn, merged with the user's new message.
    assert turns[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "import-3",
        "content": "Shown.",
    }
    assert turns[2]["content"][1] == {"type": "text", "text": "più sale"}


def test_claude_tool_use_comes_back_as_openai_tool_calls():
    result = from_anthropic_response(
        {
            "content": [
                {"type": "text", "text": "Ecco."},
                {"type": "tool_use", "id": "toolu_1", "name": "propose_recipe", "input": {"a": 1}},
            ],
            "stop_reason": "tool_use",
        }
    )
    assert result.content == "Ecco."
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "propose_recipe", "arguments": '{"a": 1}'},
        }
    ]


def test_function_tools_become_claude_tools():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return reply({"type": "text", "text": "ok"})

    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    tool = {"type": "function", "function": {"name": "t", "description": "d", "parameters": schema}}
    make(handler).chat([{"role": "user", "content": "x"}], tools=[tool])
    assert seen["body"]["tools"] == [{"name": "t", "description": "d", "input_schema": schema}]


def test_json_schemas_become_structured_outputs():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return reply({"type": "text", "text": '{"servings": 2}'})

    schema = {
        "type": "object",
        "properties": {
            "servings": {"type": "integer", "minimum": 1},
            "months": {"type": "array", "items": {"type": "integer", "maximum": 12}},
        },
    }
    response_format = {"type": "json_schema", "json_schema": {"name": "r", "schema": schema}}
    result = make(handler).chat([{"role": "user", "content": "x"}], response_format=response_format)
    assert json.loads(result.content) == {"servings": 2}
    sent = seen["body"]["output_config"]["format"]
    assert sent["type"] == "json_schema"
    assert sent["schema"] == {
        "type": "object",
        "properties": {
            "servings": {"type": "integer"},
            "months": {"type": "array", "items": {"type": "integer"}},
        },
        "additionalProperties": False,
    }


def test_structured_schemas_close_nested_objects():
    schema = {
        "type": "object",
        "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {}}}},
    }
    closed = structured_schema(schema)
    assert closed["properties"]["lines"]["items"]["additionalProperties"] is False


def test_photos_become_image_blocks():
    _system, turns = to_anthropic_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "read"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
                ],
            }
        ]
    )
    assert turns[0]["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }


def test_web_search_uses_the_server_tool_and_keeps_the_urls():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return reply(
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "s1",
                "content": [{"type": "web_search_result", "url": "https://a.test/r", "title": "R"}],
            },
            {"type": "text", "text": "Ecco le pagine."},
        )

    result = make(handler, web_search=True).chat([{"role": "user", "content": "ricetta"}])
    assert seen["body"]["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
    ]
    # The model left the URLs out of its text: the search results' are added.
    assert "https://a.test/r" in result.content


def test_thinking_is_adaptive_when_asked_for():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return reply({"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "ok"})

    result = make(handler, thinking=True).chat([{"role": "user", "content": "x"}])
    assert seen["body"]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert result.content == "ok"


def test_streaming_reports_reasoning_and_content():
    events = [
        {"type": "message_start", "message": {}},
        {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "th"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": '{"a"'}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": ": 1}"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]
    stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)

    def handler(request):
        assert json.loads(request.read())["stream"] is True
        return httpx.Response(200, text=stream)

    pieces = []
    result = make(handler).chat_stream(
        [{"role": "user", "content": "x"}], on_delta=lambda kind, text: pieces.append(kind)
    )
    assert result.content == '{"a": 1}'
    assert result.finish_reason == "stop"
    assert pieces == ["reasoning", "content", "content"]


@pytest.mark.parametrize(
    ("status", "error"), [(401, AuthError), (429, AIUnavailableError), (529, AIUnavailableError)]
)
def test_errors_are_mapped(status, error):
    chat = make(lambda request: httpx.Response(status, json={"error": {"message": "no"}}))
    with pytest.raises(error):
        chat.chat([{"role": "user", "content": "x"}])


def test_health_checks_the_model():
    assert make(lambda request: httpx.Response(200, json={"id": "m"})).health()["ok"] is True
    assert make(lambda request: httpx.Response(404, json={})).health()["ok"] is False


def test_a_model_that_refuses_disabled_thinking_is_told_its_own_way():
    sent = []

    def handler(request):
        body = json.loads(request.read())
        sent.append(body["thinking"])
        if body["thinking"] == {"type": "disabled"}:
            message = (
                'To turn thinking off on this model, send "thinking": {"type": "between_tools"}'
            )
            return httpx.Response(400, json={"error": {"message": message}})
        return reply({"type": "text", "text": "ok"})

    chat = make(handler)
    chat.model = "picky-model"
    assert chat.chat([{"role": "user", "content": "x"}]).content == "ok"
    assert chat.chat([{"role": "user", "content": "y"}]).content == "ok"
    # Learned once, then used directly.
    assert sent == [{"type": "disabled"}, {"type": "between_tools"}, {"type": "between_tools"}]

from __future__ import annotations

import json

import pytest

from nanobot.providers.custom_provider import CustomProvider


def test_parse_plain_string_response() -> None:
    provider = CustomProvider(api_key="test", api_base="http://localhost:8000/v1", default_model="dummy")

    out = provider._parse("hello")

    assert out.content == "hello"
    assert out.finish_reason == "stop"


def test_parse_responses_payload_with_text_and_tool_call() -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.with7.cn/chatgpt/v1", default_model="dummy")
    payload = {
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "hello world"}],
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": "{\"path\":\"README.md\"}",
            },
        ],
    }

    out = provider._parse_responses(payload)

    assert out.content == "hello world"
    assert out.finish_reason == "stop"
    assert out.usage["prompt_tokens"] == 10
    assert out.usage["completion_tokens"] == 5
    assert out.tool_calls[0].name == "read_file"
    assert out.tool_calls[0].arguments["path"] == "README.md"


def test_aicodewith_base_and_route_normalization() -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.aicodewith.com", default_model="dummy")

    assert provider._is_aicodewith_gateway() is True
    assert provider._openai_responses_base() == "https://api.aicodewith.com/chatgpt/v1"
    assert provider._anthropic_base() == "https://api.aicodewith.com"
    assert provider._gemini_base() == "https://api.aicodewith.com/gemini_cli"
    assert provider._route_kind_for_model("anthropic/claude-sonnet-4-6") == "anthropic"
    assert provider._route_kind_for_model("gemini/gemini-2.5-pro") == "gemini"
    assert provider._route_kind_for_model("gpt-5.2") == "openai"
    assert provider._normalize_model_for_route("anthropic/claude-sonnet-4-6", "anthropic") == "claude-sonnet-4-6"
    assert provider._normalize_model_for_route("google/gemini-2.5-pro", "gemini") == "gemini-2.5-pro"


def test_parse_anthropic_payload_with_tool_use() -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.aicodewith.com", default_model="dummy")
    payload = {
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 18, "output_tokens": 9},
        "content": [
            {"type": "text", "text": "我来读文件。"},
            {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "README.md"}},
        ],
    }

    out = provider._parse_anthropic(payload)

    assert out.content == "我来读文件。"
    assert out.finish_reason == "stop"
    assert out.usage["prompt_tokens"] == 18
    assert out.usage["completion_tokens"] == 9
    assert out.tool_calls[0].id == "call_1"
    assert out.tool_calls[0].name == "read_file"
    assert out.tool_calls[0].arguments["path"] == "README.md"


def test_parse_gemini_payload_with_function_call() -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.aicodewith.com", default_model="dummy")
    payload = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "好的，我先读取文件。"},
                        {"functionCall": {"name": "read_file", "args": {"path": "README.md"}}},
                    ]
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 11, "totalTokenCount": 31},
    }

    out = provider._parse_gemini(payload)

    assert out.content == "好的，我先读取文件。"
    assert out.finish_reason == "stop"
    assert out.usage["prompt_tokens"] == 20
    assert out.usage["completion_tokens"] == 11
    assert out.tool_calls[0].name == "read_file"
    assert out.tool_calls[0].arguments["path"] == "README.md"


@pytest.mark.asyncio
async def test_chat_via_responses_tolerates_bad_content_encoding_header(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.with7.cn/chatgpt/v1", default_model="dummy")
    payload = {"status": "completed", "output_text": "ok-from-response", "output": [], "usage": {}}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    captured_headers: dict[str, str] = {}

    class _FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {"content-encoding": "deflate"}

        async def aiter_raw(self):
            yield raw

    class _FakeStream:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, params=None, json=None):
            nonlocal captured_headers
            captured_headers = dict(headers or {})
            return _FakeStream()

    monkeypatch.setattr("nanobot.providers.custom_provider.httpx.AsyncClient", _FakeClient)

    out = await provider._chat_via_responses(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="gpt-5.4",
        max_tokens=128,
        reasoning_effort=None,
    )

    assert out.content == "ok-from-response"
    assert captured_headers.get("Accept-Encoding") == "identity"


@pytest.mark.asyncio
async def test_chat_via_responses_non_200_returns_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.with7.cn/chatgpt/v1", default_model="dummy")
    payload = {"error": "upstream down"}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    class _FakeResponse:
        def __init__(self):
            self.status_code = 502
            self.headers = {"content-encoding": "deflate"}

        async def aiter_raw(self):
            yield raw

    class _FakeStream:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, params=None, json=None):
            return _FakeStream()

    monkeypatch.setattr("nanobot.providers.custom_provider.httpx.AsyncClient", _FakeClient)

    with pytest.raises(RuntimeError, match=r"HTTP 502: upstream down"):
        await provider._chat_via_responses(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="gpt-5.4",
            max_tokens=128,
            reasoning_effort=None,
        )

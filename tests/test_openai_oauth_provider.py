from unittest.mock import patch

import pytest
from oauth_cli_kit import OAuthToken

import nanobot.providers.openai_oauth_provider as oauth_provider
from nanobot.providers.openai_oauth_provider import OpenAIOAuthProvider, _strip_model_prefix
from nanobot.providers.base import ToolCallRequest


def test_strip_model_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-oauth/gpt-5.4") == "gpt-5.4"
    assert _strip_model_prefix("openai_oauth/gpt-5.4") == "gpt-5.4"
    assert _strip_model_prefix("openai-oauth/gpt-5.4-mini") == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_openai_oauth_provider_uses_oauth_token_for_responses_api(monkeypatch):
    monkeypatch.setattr(
        oauth_provider,
        "get_token",
        lambda provider=None: OAuthToken(
            access="access-token",
            refresh="refresh-token",
            expires=9999999999999,
            account_id="acct_123",
        ),
    )

    captured: dict[str, object] = {}

    async def fake_request_codex(url, headers, body, verify, on_content_delta=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["verify"] = verify
        return "hello from oauth", [], "stop"

    with patch.object(oauth_provider, "_request_codex", side_effect=fake_request_codex):
        provider = OpenAIOAuthProvider(default_model="openai-oauth/gpt-5.4")

        response = await provider.chat(
            messages=[
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "What's the weather?"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "description": "Get weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    },
                }
            ],
            reasoning_effort="medium",
            max_tokens=256,
        )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-5.4"
    assert body["instructions"] == "Be concise."
    assert body["reasoning"] == {"effort": "medium"}
    assert body["text"] == {"verbosity": "low"}
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is True
    assert body["tools"] == [
        {
            "type": "function",
            "name": "weather",
            "description": "Get weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }
    ]
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["Authorization"] == "Bearer access-token"
    assert response.content == "hello from oauth"
    assert response.finish_reason == "stop"
    assert response.tool_calls == []

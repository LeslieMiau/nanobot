from unittest.mock import AsyncMock, patch

import pytest
from oauth_cli_kit import OAuthToken

from nanobot.providers.openai_oauth_provider import OpenAIOAuthProvider, _strip_model_prefix
from nanobot.providers.base import ToolCallRequest


def test_strip_model_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-oauth/gpt-5.4") == "gpt-5.4"
    assert _strip_model_prefix("openai_oauth/gpt-5.4") == "gpt-5.4"
    assert _strip_model_prefix("openai-oauth/gpt-5.4-mini") == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_openai_oauth_provider_uses_chatgpt_backend(monkeypatch):
    fake_tool_call = ToolCallRequest(
        id="call_1|fc_1",
        name="weather",
        arguments={"city": "Shanghai"},
    )

    monkeypatch.setattr(
        "nanobot.providers.openai_oauth_provider.get_token",
        lambda provider=None: OAuthToken(
            access="access-token",
            refresh="refresh-token",
            expires=9999999999999,
            account_id="acct_123",
        ),
    )

    mock_request = AsyncMock(return_value=("hello from oauth", [fake_tool_call], "tool_calls"))

    with patch("nanobot.providers.openai_oauth_provider._request_codex", mock_request):
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
        )

    mock_request.assert_awaited_once()
    url, headers, body = mock_request.call_args.args
    assert "chatgpt.com/backend-api/responses" in url
    assert headers["Authorization"] == "Bearer access-token"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert body["model"] == "gpt-5.4"
    assert body["instructions"] == "Be concise."
    assert body["reasoning"] == {"effort": "medium"}
    assert body["stream"] is True
    assert response.content == "hello from oauth"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "weather"
    assert response.tool_calls[0].arguments == {"city": "Shanghai"}

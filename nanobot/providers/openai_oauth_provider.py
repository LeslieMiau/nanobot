"""OpenAI Responses provider authenticated via official OAuth flow."""

from __future__ import annotations

import asyncio
from typing import Any

from oauth_cli_kit import OAuthProviderConfig, get_token

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.openai_codex_provider import (
    _build_headers,
    _convert_messages,
    _convert_tools,
    _prompt_cache_key,
    _request_codex,
)

DEFAULT_OPENAI_OAUTH_URL = "https://chatgpt.com/backend-api/codex/responses"

OPENAI_OAUTH_PROVIDER = OAuthProviderConfig(
    client_id="app_EMoamEEZ73f0CkXaXp7hrann",
    authorize_url="https://auth.openai.com/oauth/authorize",
    token_url="https://auth.openai.com/oauth/token",
    redirect_uri="http://localhost:1455/auth/callback",
    scope="openid profile email offline_access",
    jwt_claim_path="https://api.openai.com/auth",
    account_id_claim="chatgpt_account_id",
    default_originator="nanobot",
    token_filename="openai.json",
)


class OpenAIOAuthProvider(LLMProvider):
    """Call OpenAI's Responses API via ChatGPT backend using an OAuth token."""

    def __init__(
        self,
        default_model: str = "openai-oauth/gpt-5.4",
        api_base: str | None = None,
    ):
        super().__init__(api_key=None, api_base=api_base or DEFAULT_OPENAI_OAUTH_URL)
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        effective_model = _strip_model_prefix(model or self.default_model)
        system_prompt, input_items = _convert_messages(messages)

        try:
            token = await asyncio.to_thread(get_token, provider=OPENAI_OAUTH_PROVIDER)
            headers = _build_headers(token.account_id, token.access)

            body: dict[str, Any] = {
                "model": effective_model,
                "store": False,
                "stream": True,
                "instructions": system_prompt,
                "input": input_items,
                "text": {"verbosity": "medium"},
                "include": ["reasoning.encrypted_content"],
                "prompt_cache_key": _prompt_cache_key(messages),
                "tool_choice": tool_choice or "auto",
                "parallel_tool_calls": True,
            }
            if reasoning_effort:
                body["reasoning"] = {"effort": reasoning_effort}
            if tools:
                body["tools"] = _convert_tools(tools)

            url = self.api_base or DEFAULT_OPENAI_OAUTH_URL

            try:
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=True)
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=False)

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling OpenAI OAuth: {e}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-oauth/") or model.startswith("openai_oauth/"):
        return model.split("/", 1)[1]
    return model

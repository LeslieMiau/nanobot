from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.providers.openai_codex_provider import OpenAICodexProvider


@pytest.mark.asyncio
async def test_openai_codex_provider_forwards_verbosity_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_request(url, headers, body, verify):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["verify"] = verify
        return "ok", [], "stop"

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda: SimpleNamespace(account_id="acct", access="token"),
    )
    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", _fake_request)

    provider = OpenAICodexProvider(
        default_model="openai-codex/gpt-5.1",
        response_verbosity="low",
        parallel_tool_calls=True,
    )
    response = await provider.chat(
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        max_tokens=321,
        temperature=0.2,
        parallel_tool_calls=False,
    )

    assert response.content == "ok"
    assert captured["verify"] is True
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-5.1"
    assert body["text"] == {"verbosity": "low"}
    assert body["max_output_tokens"] == 321
    assert body["temperature"] == 0.2
    assert body["parallel_tool_calls"] is False

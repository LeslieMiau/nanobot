from __future__ import annotations

import time
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CodingConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def _tc(call_id: str, name: str, arguments: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=name, arguments=arguments)


class _RoutingProvider(LLMProvider):
    def __init__(self, responses_by_model: dict[str, list[LLMResponse]] | None = None):
        super().__init__(api_key=None, api_base=None)
        self.responses_by_model = {k: list(v) for k, v in (responses_by_model or {}).items()}
        self.models: list[str] = []

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        model_name = str(model or "")
        self.models.append(model_name)
        queue = self.responses_by_model.get(model_name) or []
        if queue:
            return queue.pop(0)
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _provider_name_for(model: str) -> str:
    lowered = model.lower()
    if lowered.startswith("github-copilot/"):
        return "github_copilot"
    if lowered.startswith("anthropic/"):
        return "anthropic"
    if lowered.startswith("openai-codex/"):
        return "openai_codex"
    if lowered.startswith("openai/") or lowered.startswith("gpt-"):
        return "openai"
    return "custom"


def _make_loop(
    tmp_path: Path,
    provider: _RoutingProvider,
    *,
    unavailable: set[str] | None = None,
    coding_config: CodingConfig | None = None,
) -> AgentLoop:
    unavailable_models = unavailable or set()

    def provider_switcher(requested_model: str | None):
        if requested_model is None:
            return provider, "dummy", "custom"
        if requested_model in unavailable_models:
            raise ValueError(f"provider unavailable for {requested_model}")
        return provider, requested_model, _provider_name_for(requested_model)

    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="dummy",
        provider_name="custom",
        provider_switcher=provider_switcher,
        coding_config=coding_config,
    )


def test_coding_model_normalization_rules() -> None:
    model, note = AgentLoop._normalize_coding_model_name("gpt-5.4")
    assert model == "gpt-5.4"
    assert note is None

    model, note = AgentLoop._normalize_coding_model_name("gpt-5.3-codex")
    assert model == "github-copilot/gpt-5.3-codex"
    assert note is not None

    model, note = AgentLoop._normalize_coding_model_name("claude-opus-4-5")
    assert model == "anthropic/claude-opus-4-5"
    assert note is not None

    model, note = AgentLoop._normalize_coding_model_name("unknown-provider/demo")
    assert model is None
    assert "unknown provider prefix" in (note or "")


@pytest.mark.asyncio
async def test_coding_route_falls_back_in_expected_order(tmp_path: Path) -> None:
    provider = _RoutingProvider(
        {
            "gpt-5.4": [LLMResponse(content="primary failed", finish_reason="error")],
            "github-copilot/gpt-5.3-codex": [LLMResponse(content="fallback ok")],
        }
    )
    loop = _make_loop(tmp_path, provider)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="fix demo.py please")
    )

    assert out is not None
    assert out.content == "fallback ok"
    assert provider.models == ["gpt-5.4", "github-copilot/gpt-5.3-codex"]
    assert loop._coding_model_cooldowns.get("gpt-5.4", 0.0) > time.monotonic()


@pytest.mark.asyncio
async def test_coding_route_skips_unavailable_candidates(tmp_path: Path) -> None:
    provider = _RoutingProvider(
        {"github-copilot/gpt-5.3-codex": [LLMResponse(content="codex fallback ok")]}
    )
    loop = _make_loop(tmp_path, provider, unavailable={"gpt-5.4"})

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="fix demo.py")
    )

    assert out is not None
    assert out.content == "codex fallback ok"
    assert provider.models == ["github-copilot/gpt-5.3-codex"]


@pytest.mark.asyncio
async def test_coding_route_does_not_retry_after_side_effect(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    provider = _RoutingProvider(
        {
            "gpt-5.4": [
                LLMResponse(content="", tool_calls=[_tc("call-1", "read_file", {"path": "demo.py"})]),
                LLMResponse(content="", tool_calls=[_tc(
                    "call-2",
                    "edit_file",
                    {"path": "demo.py", "old_text": "print('old')\n", "new_text": "print('new')\n"},
                )]),
                LLMResponse(content="primary failed after edit", finish_reason="error"),
            ],
            "github-copilot/gpt-5.3-codex": [LLMResponse(content="should not be used")],
        }
    )
    loop = _make_loop(tmp_path, provider)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="fix demo.py")
    )

    assert out is not None
    assert "primary failed after edit" in out.content
    assert provider.models == ["gpt-5.4", "gpt-5.4", "gpt-5.4"]
    assert target.read_text(encoding="utf-8") == "print('new')\n"


@pytest.mark.asyncio
async def test_coding_status_reports_model_route_details(tmp_path: Path) -> None:
    provider = _RoutingProvider()
    coding = CodingConfig(fallback_models=["gpt-5.3-codex"])
    loop = _make_loop(
        tmp_path,
        provider,
        unavailable={"github-copilot/gpt-5.3-codex"},
        coding_config=coding,
    )
    loop._coding_model_cooldowns["gpt-5.4"] = time.monotonic() + 120

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/coding status")
    )

    assert out is not None
    assert "Coding primary model: `gpt-5.4`" in out.content
    assert "Resolved coding candidates:" in out.content
    assert "Skipped coding candidates:" in out.content
    assert "`gpt-5.3-codex` -> `github-copilot/gpt-5.3-codex`" in out.content
    assert "cooling down" in out.content
    assert "unavailable" in out.content

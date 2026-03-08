from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.catalog import AvailableModel
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self, label: str = "provider"):
        super().__init__(api_key=None, api_base=None)
        self.label = label
        self.last_model: str | None = None

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.last_model = model
        return LLMResponse(content=f"{self.label}:{model}")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(
    workspace: Path,
    *,
    provider_name: str | None = None,
    provider_switcher=None,
    available_models_provider=None,
) -> tuple[AgentLoop, _Provider]:
    bus = MessageBus()
    provider = _Provider("default")
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="dummy",
        max_iterations=1,
        provider_name=provider_name,
        provider_switcher=provider_switcher,
        available_models_provider=available_models_provider,
    )
    return loop, provider


@pytest.mark.asyncio
async def test_model_command_shows_current_model(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, provider_name="custom")
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model")

    out = await loop._process_message(msg)

    assert out is not None
    assert "Current model" in out.content
    assert "`dummy`" in out.content
    assert "Current provider" in out.content
    assert "`custom`" in out.content


@pytest.mark.asyncio
async def test_model_command_switches_model_and_applies_to_chat(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)

    switch = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model gpt-5.2")
    switched = await loop._process_message(switch)
    assert switched is not None
    assert "gpt-5.2" in switched.content
    assert loop.model == "gpt-5.2"
    assert loop.subagents.model == "gpt-5.2"

    normal = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")
    out = await loop._process_message(normal)
    assert out is not None
    assert out.content == "default:gpt-5.2"
    assert provider.last_model == "gpt-5.2"


@pytest.mark.asyncio
async def test_model_command_chinese_alias_and_reset(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)

    switch = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="切换模型 gemini-3.1-pro-preview")
    switched = await loop._process_message(switch)
    assert switched is not None
    assert "gemini-3.1-pro-preview" in switched.content
    assert loop.model == "gemini-3.1-pro-preview"

    reset = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model reset")
    reset_out = await loop._process_message(reset)
    assert reset_out is not None
    assert "dummy" in reset_out.content
    assert loop.model == "dummy"


@pytest.mark.asyncio
async def test_model_command_natural_language_switches_provider(tmp_path: Path) -> None:
    switch_calls: list[str | None] = []

    class _SwitchedProvider(_Provider):
        pass

    def provider_switcher(requested_model: str | None):
        switch_calls.append(requested_model)
        provider = _SwitchedProvider()
        if requested_model is None:
            return provider, "dummy", "custom"
        return provider, requested_model, "github_copilot"

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    switched = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="把模型换成 gpt-5.3-codex")
    )

    assert switched is not None
    assert "gpt-5.3-codex" in switched.content
    assert "github_copilot" in switched.content
    assert loop.model == "gpt-5.3-codex"
    assert loop.provider_name == "github_copilot"
    assert switch_calls == ["gpt-5.3-codex"]


@pytest.mark.asyncio
async def test_model_command_reset_restores_default_provider(tmp_path: Path) -> None:
    class _SwitchedProvider(_Provider):
        pass

    def provider_switcher(requested_model: str | None):
        provider = _SwitchedProvider()
        if requested_model is None:
            return provider, "dummy", "custom"
        return provider, requested_model, "openai"

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model gpt-5.2")
    )
    reset_out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model reset")
    )

    assert reset_out is not None
    assert "provider: `custom`" in reset_out.content
    assert loop.model == "dummy"
    assert loop.provider_name == "custom"


@pytest.mark.asyncio
async def test_model_command_reports_provider_switch_errors(tmp_path: Path) -> None:
    def provider_switcher(requested_model: str | None):
        raise ValueError(f"Provider unavailable for {requested_model}")

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="把模型换成 gpt-5.3-codex")
    )

    assert out is not None
    assert out.content == "Model switch failed: Provider unavailable for gpt-5.3-codex"


@pytest.mark.asyncio
async def test_model_command_lists_available_models(tmp_path: Path) -> None:
    def available_models_provider(_current_model: str | None, _current_provider: str | None):
        return [
            AvailableModel(model="anthropic/claude-opus-4-5", provider_name="anthropic"),
            AvailableModel(model="gpt-5.4", provider_name="openai"),
        ]

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        available_models_provider=available_models_provider,
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model list")
    )

    assert out is not None
    assert "Available models:" in out.content
    assert "1. `anthropic/claude-opus-4-5`" in out.content
    assert "2. `gpt-5.4`" in out.content
    assert "Current model: `dummy`" in out.content


@pytest.mark.asyncio
async def test_model_command_selects_model_by_index(tmp_path: Path) -> None:
    def provider_switcher(requested_model: str | None):
        if requested_model is None:
            return _Provider("default"), "dummy", "custom"
        return _Provider("switched"), requested_model, "openai"

    def available_models_provider(_current_model: str | None, _current_provider: str | None):
        return [
            AvailableModel(model="anthropic/claude-opus-4-5", provider_name="anthropic"),
            AvailableModel(model="gpt-5.4", provider_name="openai"),
        ]

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
        available_models_provider=available_models_provider,
    )

    switched = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model 2")
    )

    assert switched is not None
    assert "gpt-5.4" in switched.content
    assert "provider: `openai`" in switched.content
    assert loop.model == "gpt-5.4"


@pytest.mark.asyncio
async def test_model_command_switch_is_isolated_per_session(tmp_path: Path) -> None:
    def provider_switcher(requested_model: str | None):
        if requested_model is None:
            return _Provider("default"), "dummy", "custom"
        return _Provider("switched"), requested_model, "openai"

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="/model gpt-5.2")
    )

    out_a = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="hello")
    )
    out_b = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-b", content="hello")
    )

    assert out_a is not None
    assert out_b is not None
    assert out_a.content == "switched:gpt-5.2"
    assert out_b.content == "default:dummy"


@pytest.mark.asyncio
async def test_model_command_reset_only_affects_current_session(tmp_path: Path) -> None:
    def provider_switcher(requested_model: str | None):
        if requested_model is None:
            return _Provider("default"), "dummy", "custom"
        return _Provider("switched"), requested_model, "openai"

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="/model gpt-5.2")
    )
    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-b", content="/model gemini-2.0")
    )

    reset = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="/model reset")
    )
    out_a = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-a", content="hello")
    )
    out_b = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="chat-b", content="hello")
    )

    assert reset is not None
    assert "provider: `custom`" in reset.content
    assert out_a is not None
    assert out_b is not None
    assert out_a.content == "default:dummy"
    assert out_b.content == "switched:gemini-2.0"


@pytest.mark.asyncio
async def test_model_command_persists_session_selection_across_reloads(tmp_path: Path) -> None:
    def provider_switcher(requested_model: str | None):
        if requested_model is None:
            return _Provider("default"), "dummy", "custom"
        return _Provider("switched"), requested_model, "openai"

    loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model gpt-5.2")
    )

    reloaded_loop, _ = _make_loop(
        tmp_path,
        provider_name="custom",
        provider_switcher=provider_switcher,
    )
    out = await reloaded_loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")
    )

    assert out is not None
    assert out.content == "switched:gpt-5.2"


@pytest.mark.asyncio
async def test_image_confirm_reports_no_pending_prompt(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/image-confirm")
    )

    assert out is not None
    assert out.content == "No pending image prompt to confirm."

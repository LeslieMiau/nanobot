from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self):
        super().__init__(api_key=None, api_base=None)
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
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(workspace: Path) -> tuple[AgentLoop, _Provider]:
    bus = MessageBus()
    provider = _Provider()
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="dummy",
        max_iterations=1,
    )
    return loop, provider


@pytest.mark.asyncio
async def test_model_command_shows_current_model(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/model")

    out = await loop._process_message(msg)

    assert out is not None
    assert "Current model" in out.content
    assert "`dummy`" in out.content


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
    assert out.content == "ok"
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


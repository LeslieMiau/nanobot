from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(tmp_path: Path, restart_callback=None) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        restart_callback=restart_callback,
    )


@pytest.mark.asyncio
async def test_restart_command_unavailable_without_callback(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/restart")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "Restart is not available in this mode."


@pytest.mark.asyncio
async def test_restart_command_calls_callback(tmp_path: Path) -> None:
    cb = AsyncMock()
    loop = _make_loop(tmp_path, restart_callback=cb)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/restart")

    out = await loop._process_message(msg)

    cb.assert_awaited_once()
    assert out is not None
    assert out.content == "Restarting nanobot..."


@pytest.mark.asyncio
async def test_restart_alias_in_chinese_calls_callback(tmp_path: Path) -> None:
    cb = AsyncMock()
    loop = _make_loop(tmp_path, restart_callback=cb)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="重启")

    out = await loop._process_message(msg)

    cb.assert_awaited_once()
    assert out is not None
    assert out.content == "Restarting nanobot..."

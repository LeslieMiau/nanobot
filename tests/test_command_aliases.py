from __future__ import annotations

import asyncio
from pathlib import Path

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


def _make_loop(tmp_path: Path) -> tuple[AgentLoop, MessageBus]:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
    )
    return loop, bus


@pytest.mark.asyncio
async def test_start_alias_works(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="开始")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "你好，我是 nanobot。直接告诉我你想处理的事就行。"


@pytest.mark.asyncio
async def test_help_alias_works(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="帮助")

    out = await loop._process_message(msg)

    assert out is not None
    assert "/help" in out.content
    assert "/coding" in out.content
    assert "/retry-cron" in out.content
    assert "/stop" in out.content


@pytest.mark.asyncio
async def test_new_alias_works(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="新会话")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "New session started."


@pytest.mark.asyncio
async def test_stop_alias_works_in_run_loop(tmp_path: Path) -> None:
    loop, bus = _make_loop(tmp_path)
    run_task = asyncio.create_task(loop.run())
    try:
        await bus.publish_inbound(
            InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="停止")
        )
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert "No active task" in out.content
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2.0)

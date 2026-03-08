from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import TokenGuardConfig
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
    assert "我是 nanobot 小新版" in out.content
    assert "重启回来" in out.content


@pytest.mark.asyncio
async def test_restart_alias_in_chinese_calls_callback(tmp_path: Path) -> None:
    cb = AsyncMock()
    loop = _make_loop(tmp_path, restart_callback=cb)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="重启")

    out = await loop._process_message(msg)

    cb.assert_awaited_once()
    assert out is not None
    assert "我是 nanobot 小新版" in out.content
    assert "重启回来" in out.content


@pytest.mark.asyncio
async def test_restart_alias_works_in_run_loop_while_token_guard_pending(tmp_path: Path) -> None:
    cb = AsyncMock()
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        restart_callback=cb,
        token_guard_config=TokenGuardConfig(
            enabled=True,
            threshold_tokens=10,
            confirm_command="/confirm",
            cancel_command="/cancel",
        ),
    )
    run_task = asyncio.create_task(loop.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="A" * 300,
            )
        )
        blocked = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert "Token Guard" in blocked.content

        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="重启",
            )
        )
        restarted = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        cb.assert_awaited_once()
        assert "我是 nanobot 小新版" in restarted.content
        assert "重启回来" in restarted.content

        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="/confirm",
            )
        )
        cleared = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert cleared.content == "No pending large task or coding plan to confirm."
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2.0)


@pytest.mark.asyncio
async def test_start_command_returns_shinchan_welcome(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/start")

    out = await loop._process_message(msg)

    assert out is not None
    assert "我是 nanobot 小新版" in out.content

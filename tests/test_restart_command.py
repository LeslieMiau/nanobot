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
    assert "我是 nanobot" in out.content
    assert "正在重启" in out.content


@pytest.mark.asyncio
async def test_restart_alias_in_chinese_calls_callback(tmp_path: Path) -> None:
    cb = AsyncMock()
    loop = _make_loop(tmp_path, restart_callback=cb)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="重启")

    out = await loop._process_message(msg)

    cb.assert_awaited_once()
    assert out is not None
    assert "我是 nanobot" in out.content
    assert "正在重启" in out.content


@pytest.mark.asyncio
async def test_restart_alias_works_in_run_loop_while_token_guard_pending(tmp_path: Path) -> None:
    cb = AsyncMock()
    bus = MessageBus()
    session_key = "telegram:6460709699"
    loop = AgentLoop(
        bus=bus,
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        restart_callback=cb,
        token_guard_config=TokenGuardConfig(
            enabled=True,
            default_mode="on",
            default_budget_k=20,
        ),
    )
    session = loop.sessions.get_or_create(session_key)
    for i in range(24):
        session.messages.append({"role": "user", "content": f"history-user-{i} " + ("A" * 500)})
        session.messages.append({"role": "assistant", "content": "history-assistant " + ("B" * 500)})
    run_task = asyncio.create_task(loop.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="请 repo-wide 搜索、读取、修改并测试整个项目，然后给我 exhaustive report。" + ("A" * 7000),
            )
        )
        blocked = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert "⚠️ Token Guard 拦截" in blocked.content

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
        assert "我是 nanobot" in restarted.content
        assert "正在重启" in restarted.content
        assert loop.sessions.get_or_create(session_key).metadata["token_guard"]["pending_message"] is None
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2.0)


@pytest.mark.asyncio
async def test_restart_has_highest_priority_while_session_task_is_running(tmp_path: Path) -> None:
    cb = AsyncMock()
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        restart_callback=cb,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    original_process = loop._process_message

    async def blocking_process(msg, **kwargs):
        if msg.content == "work":
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        return await original_process(msg, **kwargs)

    loop._process_message = blocking_process
    run_task = asyncio.create_task(loop.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="work",
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        await bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                sender_id="6460709699",
                chat_id="6460709699",
                content="/restart",
            )
        )
        restarted = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        cb.assert_awaited_once()
        assert "我是 nanobot" in restarted.content
        await asyncio.wait_for(cancelled.wait(), timeout=2.0)
    finally:
        release.set()
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2.0)


@pytest.mark.asyncio
async def test_start_command_returns_neutral_welcome(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/start")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "你好，我是 nanobot。直接告诉我你想处理的事就行。"

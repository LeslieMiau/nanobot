from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import TokenGuardConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self):
        super().__init__(api_key=None, api_base=None)
        self.calls = 0

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(workspace: Path, *, threshold: int) -> tuple[AgentLoop, _Provider]:
    bus = MessageBus()
    provider = _Provider()
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="dummy",
        max_iterations=1,
        token_guard_config=TokenGuardConfig(
            enabled=True,
            threshold_tokens=threshold,
            confirm_command="/confirm",
            cancel_command="/cancel",
        ),
    )
    return loop, provider


@pytest.mark.asyncio
async def test_token_guard_does_not_block_normal_message(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, threshold=100_000)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "ok"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_blocks_large_message_until_confirmed(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, threshold=10)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="A" * 300)

    blocked = await loop._process_message(msg)

    assert blocked is not None
    assert "Token Guard" in blocked.content
    assert provider.calls == 0

    confirm = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/confirm")
    resumed = await loop._process_message(confirm)

    assert resumed is not None
    assert resumed.content == "ok"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_cancel_clears_pending_task(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, threshold=10)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="A" * 300)
    await loop._process_message(msg)

    cancel = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/cancel")
    canceled = await loop._process_message(cancel)

    assert canceled is not None
    assert "Canceled pending" in canceled.content
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_token_guard_exit_alias_cancels_pending_task(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, threshold=10)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="A" * 300)
    await loop._process_message(msg)

    exit_msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="exit")
    canceled = await loop._process_message(exit_msg)

    assert canceled is not None
    assert "Canceled pending" in canceled.content
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_token_guard_pending_preserves_original_request(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, threshold=10)
    first = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="A" * 300)
    second = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="B" * 300)

    blocked = await loop._process_message(first)
    blocked_again = await loop._process_message(second)
    confirm = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/confirm")
    resumed = await loop._process_message(confirm)

    assert blocked is not None
    assert blocked_again is not None
    assert "pending large task" in blocked_again.content.lower()
    assert resumed is not None
    assert resumed.content == "ok"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_runs_before_large_change_plan_guard(tmp_path: Path) -> None:
    bus = MessageBus()

    class _PlanningProvider(LLMProvider):
        def __init__(self):
            super().__init__(api_key=None, api_base=None)
            self.calls = 0

        async def chat(
            self,
            messages,
            tools=None,
            model=None,
            max_tokens=4096,
            temperature=0.7,
            reasoning_effort=None,
        ) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                content="1. Inspect files\n2. Make changes\n3. Verify",
            ) if self.calls == 1 else LLMResponse(content="ok")

        def get_default_model(self) -> str:
            return "dummy"

    provider = _PlanningProvider()
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="dummy",
        max_iterations=1,
        token_guard_config=TokenGuardConfig(
            enabled=True,
            threshold_tokens=10,
            confirm_command="/confirm",
            cancel_command="/cancel",
        ),
    )
    request = "请重构整个 agent loop 并清理多文件结构 " + ("A" * 300)

    blocked = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=request)
    )
    assert blocked is not None
    assert "Token Guard" in blocked.content
    assert provider.calls == 0

    planned = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/confirm")
    )
    assert planned is not None
    assert "Inspect files" in planned.content
    assert provider.calls == 1

    resumed = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/confirm")
    )
    assert resumed is not None
    assert resumed.content == "ok"
    assert provider.calls == 2

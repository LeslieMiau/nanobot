from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__(api_key=None, api_base=None)
        self._responses = iter(responses)
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
        return next(self._responses)

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(tmp_path: Path, responses: list[LLMResponse]) -> tuple[AgentLoop, _Provider]:
    provider = _Provider(responses)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="dummy",
        max_iterations=1,
    )
    return loop, provider


@pytest.mark.asyncio
async def test_large_coding_request_requires_plan_confirmation(tmp_path: Path) -> None:
    loop, provider = _make_loop(
        tmp_path,
        [
            LLMResponse(content="1. Inspect files\n2. Refactor carefully\n3. Run targeted tests"),
            LLMResponse(content="implemented"),
        ],
    )

    initial = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请重构整个 agent loop 并清理多文件结构")
    )

    assert initial is not None
    assert "Inspect files" in initial.content
    assert "Reply `/confirm` to execute this larger change" in initial.content
    assert provider.calls == 1

    resumed = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/confirm")
    )

    assert resumed is not None
    assert resumed.content == "implemented"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_pending_plan_blocks_other_messages_until_confirm_or_cancel(tmp_path: Path) -> None:
    loop, provider = _make_loop(
        tmp_path,
        [LLMResponse(content="Plan first")],
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请重写整个项目结构")
    )
    blocked = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="顺便看看这个报错")
    )

    assert blocked is not None
    assert "pending coding plan" in blocked.content.lower()
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cancel_clears_pending_plan(tmp_path: Path) -> None:
    loop, provider = _make_loop(
        tmp_path,
        [LLMResponse(content="Plan first")],
    )

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请重构整个代码库")
    )
    canceled = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/cancel")
    )

    assert canceled is not None
    assert canceled.content == "Canceled pending task."
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_small_coding_request_skips_plan_guard(tmp_path: Path) -> None:
    loop, provider = _make_loop(
        tmp_path,
        [LLMResponse(content="fixed")],
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请修复 demo.py 的一个报错")
    )

    assert out is not None
    assert out.content.startswith("fixed")
    assert "Token Guard：" not in out.content
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_large_change_plan_falls_back_when_provider_errors(tmp_path: Path) -> None:
    loop, provider = _make_loop(
        tmp_path,
        [LLMResponse(content="Error: upstream unavailable", finish_reason="error")],
    )

    initial = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请重构整个 agent loop")
    )

    assert initial is not None
    assert "Planned steps:" in initial.content
    assert "Inspect the relevant files and tests." in initial.content
    assert "upstream unavailable" not in initial.content
    assert provider.calls == 1

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def _tc(call_id: str, name: str, arguments: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=name, arguments=arguments)


class _ScriptedProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__(api_key=None, api_base=None)
        self._responses = iter(responses)
        self.calls = 0
        self.messages: list[list[dict]] = []

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
        self.messages.append(copy.deepcopy(messages))
        return next(self._responses)

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(tmp_path: Path, responses: list[LLMResponse]) -> tuple[AgentLoop, _ScriptedProvider]:
    provider = _ScriptedProvider(responses)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="dummy",
    )
    return loop, provider


@pytest.mark.asyncio
async def test_coding_guard_blocks_edit_without_prior_read(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    loop, provider = _make_loop(
        tmp_path,
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="blocked", tool_calls=[]),
        ],
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请修复 demo.py")
    )

    assert out is not None
    assert out.content.startswith("blocked")
    assert "Token Guard：原始体量" in out.content
    assert target.read_text(encoding="utf-8") == "print('old')\n"
    assert provider.calls == 2
    assert "requires reading a file before modifying it" in provider.messages[1][-1]["content"]


@pytest.mark.asyncio
async def test_coding_guard_allows_edit_after_read_and_verification(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    loop, provider = _make_loop(
        tmp_path,
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "read_file", {"path": "demo.py"})]),
            LLMResponse(content="", tool_calls=[_tc("call-2", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="", tool_calls=[_tc("call-3", "exec", {"command": "printf verification"})]),
            LLMResponse(content="updated", tool_calls=[]),
        ],
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请修复 demo.py 并验证")
    )

    assert out is not None
    assert out.content.startswith("updated")
    assert "Changed:\n- demo.py" in out.content
    assert "Verified:\n- `printf verification`" in out.content
    assert "Unverified:\n- None noted." in out.content
    assert target.read_text(encoding="utf-8") == "print('new')\n"
    assert provider.calls == 4


@pytest.mark.asyncio
async def test_coding_guard_requests_verification_after_edit(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    loop, provider = _make_loop(
        tmp_path,
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "read_file", {"path": "demo.py"})]),
            LLMResponse(content="", tool_calls=[_tc("call-2", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="done", tool_calls=[]),
            LLMResponse(content="done; verification not run because no local test command is available", tool_calls=[]),
        ],
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请修复 demo.py")
    )

    assert out is not None
    assert out.content.startswith("done; verification not run because no local test command is available")
    assert "Unverified:\n- Edits were not verified with an exec command." in out.content
    assert provider.calls == 4
    assert "[Coding mode guard]" in provider.messages[3][-1]["content"]


@pytest.mark.asyncio
async def test_coding_guard_accepts_failed_verification_attempt(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    loop, provider = _make_loop(
        tmp_path,
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "read_file", {"path": "demo.py"})]),
            LLMResponse(content="", tool_calls=[_tc("call-2", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="", tool_calls=[_tc("call-3", "exec", {"command": "command_that_does_not_exist_12345"})]),
            LLMResponse(content="updated; verification failed because the command was unavailable", tool_calls=[]),
        ],
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请修复 demo.py 并验证")
    )

    assert out is not None
    assert out.content.startswith("updated; verification failed because the command was unavailable")
    assert "Verification command reported a problem" in out.content
    assert target.read_text(encoding="utf-8") == "print('new')\n"
    assert provider.calls == 4

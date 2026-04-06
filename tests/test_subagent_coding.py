from __future__ import annotations

import copy
from pathlib import Path

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _tc(call_id: str, name: str, arguments: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=name, arguments=arguments)


class _Provider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = iter(responses)
        self.messages: list[list[dict]] = []

    async def chat(self, messages, *args, **kwargs) -> LLMResponse:
        self.messages.append(copy.deepcopy(messages))
        return next(self._responses)

    def get_default_model(self) -> str:
        return "dummy"


@pytest.mark.asyncio
async def test_subagent_coding_guard_blocks_edit_without_read(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    provider = _Provider(
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="blocked", tool_calls=[]),
        ]
    )
    bus = MessageBus()
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    await mgr._run_subagent("sub1", "fix demo.py", "fix demo.py", {"channel": "cli", "chat_id": "direct"}, True)

    assert target.read_text(encoding="utf-8") == "print('old')\n"
    assert "requires reading a file before modifying it" in provider.messages[1][-1]["content"]


@pytest.mark.asyncio
async def test_subagent_coding_summary_included_in_announced_result(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    provider = _Provider(
        [
            LLMResponse(content="", tool_calls=[_tc("call-1", "read_file", {"path": "demo.py"})]),
            LLMResponse(content="", tool_calls=[_tc("call-2", "edit_file", {
                "path": "demo.py",
                "old_text": "print('old')\n",
                "new_text": "print('new')\n",
            })]),
            LLMResponse(content="", tool_calls=[_tc("call-3", "exec", {"command": "printf verification"})]),
            LLMResponse(content="done", tool_calls=[]),
        ]
    )
    bus = MessageBus()
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    await mgr._run_subagent("sub2", "fix demo.py", "fix demo.py", {"channel": "cli", "chat_id": "direct"}, True)
    announced = await bus.consume_inbound()

    assert target.read_text(encoding="utf-8") == "print('new')\n"
    assert "Changed:\n- demo.py" in announced.content
    assert "Verified:\n- `printf verification`" in announced.content
    assert "Unverified:\n- None noted." in announced.content

from __future__ import annotations

import pytest

from nanobot.agent.tools.spawn import SpawnTool
from nanobot.providers.base import LLMProvider


class _Provider(LLMProvider):
    async def chat(self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7, reasoning_effort=None):
        raise AssertionError("chat should not be called in this unit test")

    def get_default_model(self) -> str:
        return "dummy"


class _Manager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return "spawned"


@pytest.mark.asyncio
async def test_spawn_tool_passes_session_runtime_snapshot() -> None:
    manager = _Manager()
    provider = _Provider(api_key=None, api_base=None)
    tool = SpawnTool(manager=manager)
    tool.set_context(
        "cli",
        "room",
        coding_enabled=True,
        provider=provider,
        model="gpt-5.2",
        session_key="cli:room:thread-a",
    )

    result = await tool.execute("do work", label="task")

    assert result == "spawned"
    assert manager.calls == [{
        "task": "do work",
        "label": "task",
        "origin_channel": "cli",
        "origin_chat_id": "room",
        "session_key": "cli:room:thread-a",
        "coding_enabled": True,
        "provider": provider,
        "model": "gpt-5.2",
    }]

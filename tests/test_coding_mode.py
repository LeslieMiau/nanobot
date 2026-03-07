from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CodingConfig
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


def _make_loop(tmp_path: Path, *, coding_config: CodingConfig | None = None) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        coding_config=coding_config,
    )


@pytest.mark.asyncio
async def test_coding_command_reports_status(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/coding status")
    )

    assert out is not None
    assert "Coding mode setting: `auto`" in out.content
    assert "Use `/coding on`, `/coding off`, or `/coding auto`." in out.content


@pytest.mark.asyncio
async def test_coding_command_updates_session_mode(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/coding on")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "Coding mode set to: `on`"
    session = loop.sessions.get_or_create("cli:direct")
    assert session.metadata["coding_mode"] == "on"


def test_coding_auto_detect_triggers_for_code_requests(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")

    setting, active = loop._resolve_coding_mode(session, "请帮我修复 tests/test_model_command.py 的报错")

    assert setting == "auto"
    assert active is True


def test_coding_auto_detect_does_not_trigger_for_plain_chat(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")

    _, active = loop._resolve_coding_mode(session, "今天天气怎么样")

    assert active is False


def test_explicit_coding_off_overrides_auto_detection(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")
    session.metadata["coding_mode"] = "off"

    setting, active = loop._resolve_coding_mode(session, "fix the failing pytest command")

    assert setting == "off"
    assert active is False

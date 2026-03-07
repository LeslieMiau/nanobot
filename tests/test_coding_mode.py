from __future__ import annotations

import copy
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CodingConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self):
        super().__init__(api_key=None, api_base=None)
        self.messages = []
        self.temperatures = []

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.messages.append(copy.deepcopy(messages))
        self.temperatures.append(float(temperature))
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(tmp_path: Path, *, coding_config: CodingConfig | None = None) -> tuple[AgentLoop, _Provider]:
    provider = _Provider()
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="dummy",
        coding_config=coding_config,
    ), provider


@pytest.mark.asyncio
async def test_coding_command_reports_status(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/coding status")
    )

    assert out is not None
    assert "Coding mode setting: `auto`" in out.content
    assert "Use `/coding on`, `/coding off`, or `/coding auto`." in out.content


@pytest.mark.asyncio
async def test_coding_command_updates_session_mode(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/coding on")

    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "Coding mode set to: `on`"
    session = loop.sessions.get_or_create("cli:direct")
    assert session.metadata["coding_mode"] == "on"


def test_coding_auto_detect_triggers_for_code_requests(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")

    setting, active = loop._resolve_coding_mode(session, "请帮我修复 tests/test_model_command.py 的报错")

    assert setting == "auto"
    assert active is True


def test_coding_auto_detect_does_not_trigger_for_plain_chat(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")

    _, active = loop._resolve_coding_mode(session, "今天天气怎么样")

    assert active is False


def test_explicit_coding_off_overrides_auto_detection(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")
    session.metadata["coding_mode"] = "off"

    setting, active = loop._resolve_coding_mode(session, "fix the failing pytest command")

    assert setting == "off"
    assert active is False


@pytest.mark.asyncio
async def test_coding_requests_skip_persona_hints_and_clamp_temperature(tmp_path: Path) -> None:
    (tmp_path / "CODING.md").write_text("Use coding guardrails.", encoding="utf-8")
    loop, provider = _make_loop(tmp_path)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="请帮我修复这个报错")
    )

    assert out is not None
    assert provider.temperatures == [0.1]
    system_prompt = provider.messages[0][0]["content"]
    assert "Use coding guardrails." in system_prompt
    assert "Persona Runtime Directive" not in system_prompt

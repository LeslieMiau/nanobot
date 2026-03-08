from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CodingConfig, TokenGuardConfig
from nanobot.providers.base import LLMProvider, LLMResponse


def _last_user_text(messages) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


class _Provider(LLMProvider):
    def __init__(self) -> None:
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
        if "[Planning guard]" in _last_user_text(messages):
            return LLMResponse(content="1. Inspect files\n2. Make changes\n3. Verify")
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(
    workspace: Path,
    *,
    mode: str = "on",
    budget_k: int = 20,
    coding_enabled: bool = True,
) -> tuple[AgentLoop, _Provider]:
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
            default_mode=mode,
            default_budget_k=budget_k,
        ),
        coding_config=CodingConfig(enabled=coding_enabled, auto_detect=coding_enabled),
    )
    return loop, provider


def _seed_long_session(loop: AgentLoop, session_key: str = "cli:direct") -> None:
    session = loop.sessions.get_or_create(session_key)
    for i in range(24):
        session.messages.append({"role": "user", "content": f"history-user-{i} " + ("A" * 500)})
        session.messages.append({"role": "assistant", "content": "history-assistant " + ("B" * 500)})


@pytest.mark.asyncio
async def test_token_guard_allows_normal_message_and_appends_estimate(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")
    )

    assert out is not None
    assert out.content.startswith("ok")
    assert "Token Guard：原始体量" in out.content
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_control_commands_update_session_state(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)

    mode_out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="TokenGuard: strict")
    )
    budget_out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="TokenBudget: 42k")
    )

    session = loop.sessions.get_or_create("cli:direct")

    assert mode_out is not None
    assert mode_out.content == "Token Guard mode set to: `strict`"
    assert budget_out is not None
    assert budget_out.content == "Token Guard budget set to: `42k`"
    assert session.metadata["token_guard"]["mode"] == "strict"
    assert session.metadata["token_guard"]["budget_k"] == 42
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_token_guard_does_not_block_short_follow_up_in_long_session(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)
    _seed_long_session(loop)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="只看 loop.py 这里的一个小问题")
    )

    assert out is not None
    assert out.content.startswith("ok")
    assert "Token Guard：原始体量" in out.content
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_intercepts_high_risk_task_until_proceeded(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, coding_enabled=False)
    _seed_long_session(loop)
    request = (
        "请 repo-wide 搜索、汇总并对比整个项目的配置、日志和文档，使用 bash 和 web 一起排查，"
        "最后给我一份 exhaustive full report。"
        + ("A" * 7000)
    )

    blocked = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=request)
    )

    session = loop.sessions.get_or_create("cli:direct")
    assert blocked is not None
    assert "⚠️ Token Guard 拦截" in blocked.content
    assert "REPO_WIDE" in blocked.content
    assert session.metadata["token_guard"]["pending_message"] == request
    assert provider.calls == 0

    resumed = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="继续")
    )

    assert resumed is not None
    assert resumed.content == "ok"
    assert session.metadata["token_guard"]["pending_message"] is None
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_new_instruction_replaces_pending_request(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)
    _seed_long_session(loop)

    await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="direct",
            content="请 repo-wide 搜索并重构整个项目，再输出 exhaustive report。" + ("A" * 7000),
        )
    )
    narrowed = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="direct",
            content="只检查 nanobot/agent/loop.py 这一处，并告诉我最可能的风险。",
        )
    )

    session = loop.sessions.get_or_create("cli:direct")
    assert narrowed is not None
    assert narrowed.content.startswith("ok")
    assert session.metadata["token_guard"]["pending_message"] is None
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_token_guard_runs_before_large_change_plan_guard(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path)
    _seed_long_session(loop)
    request = (
        "请 repo-wide 搜索、读取、修改并测试整个 agent loop 与相关多文件结构，"
        "使用 bash 和 web 一起排查，再完整说明设计取舍。"
        + ("A" * 7000)
    )

    blocked = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=request)
    )

    assert blocked is not None
    assert "⚠️ Token Guard 拦截" in blocked.content
    assert provider.calls == 0

    planned = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="继续")
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


@pytest.mark.asyncio
async def test_token_guard_off_mode_skips_interception_and_estimate(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, mode="off", coding_enabled=False)
    _seed_long_session(loop)

    out = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="direct",
            content="请 repo-wide 搜索、读取、修改并测试整个项目，然后给我 exhaustive report。" + ("A" * 7000),
        )
    )

    assert out is not None
    assert out.content == "ok"
    assert provider.calls == 1

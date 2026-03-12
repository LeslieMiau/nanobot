from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule
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


class _FakeCronService:
    def __init__(self) -> None:
        self.on_job = None
        self.run_calls: list[tuple[str, bool]] = []
        self._job = CronJob(
            id="job-1",
            name="Daily AI News",
            schedule=CronSchedule(kind="cron", expr="0 8 * * *", tz="Asia/Shanghai"),
            payload=CronPayload(
                message="Generate digest",
                deliver=True,
                channel="telegram",
                to="chat-1",
            ),
            state=CronJobState(),
        )

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        return [self._job]

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        self.run_calls.append((job_id, force))
        if self.on_job is None:
            return False
        await self.on_job(self._job)
        return True


def _make_loop(tmp_path, cron_service: _FakeCronService | None = None) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        model="dummy",
        cron_service=cron_service,
    )


@pytest.mark.asyncio
async def test_retry_cron_stages_pending_confirmation(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)

    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )

    assert out is not None
    assert "Pending cron retry for `job-1`" in out.content
    assert "/confirm" in out.content
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert session.metadata["operator_action"]["kind"] == "cron_retry"
    assert session.metadata["operator_action"]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_retry_cron_accepts_natural_language_trigger(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)

    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="重跑定时任务 job-1")
    )

    assert out is not None
    assert "Pending cron retry for `job-1`" in out.content
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert session.metadata["operator_action"]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_retry_cron_confirm_executes_in_current_chat(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)
    loop.process_system_turn = AsyncMock(return_value="digest ready")

    await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )
    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/confirm")
    )

    assert out is not None
    assert "Retried cron job `job-1` (Daily AI News):" in out.content
    assert "digest ready" in out.content
    assert cron.run_calls == [("job-1", True)]
    loop.process_system_turn.assert_awaited_once()
    args = loop.process_system_turn.await_args.args
    kwargs = loop.process_system_turn.await_args.kwargs
    assert "Daily AI News" in args[0]
    assert kwargs["session_key"] == "cron:job-1:manual"
    assert kwargs["channel"] == "cli"
    assert kwargs["chat_id"] == "cron-retry:job-1"
    assert kwargs["stateless"] is True
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert "operator_action" not in session.metadata


@pytest.mark.asyncio
async def test_retry_cron_accepts_natural_confirmation(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)
    loop.process_system_turn = AsyncMock(return_value="digest ready")

    await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )
    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="确认")
    )

    assert out is not None
    assert "Retried cron job `job-1` (Daily AI News):" in out.content
    assert cron.run_calls == [("job-1", True)]
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert "operator_action" not in session.metadata


@pytest.mark.asyncio
async def test_retry_cron_cancel_clears_pending_action(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)

    await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )
    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/cancel")
    )

    assert out is not None
    assert out.content == "Canceled pending task."
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert "operator_action" not in session.metadata


@pytest.mark.asyncio
async def test_retry_cron_accepts_natural_cancellation(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)

    await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )
    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="取消")
    )

    assert out is not None
    assert out.content == "Canceled pending task."
    session = loop.sessions.get_or_create("telegram:chat-1")
    assert "operator_action" not in session.metadata


@pytest.mark.asyncio
async def test_retry_cron_reports_missing_job(tmp_path) -> None:
    cron = _FakeCronService()
    cron.list_jobs = lambda include_disabled=False: []
    loop = _make_loop(tmp_path, cron)

    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron missing-job")
    )

    assert out is not None
    assert out.content == "Cron job not found: `missing-job`"


@pytest.mark.asyncio
async def test_retry_cron_blocks_other_messages_until_confirmed(tmp_path) -> None:
    cron = _FakeCronService()
    loop = _make_loop(tmp_path, cron)

    await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="/retry-cron job-1")
    )
    out = await loop._process_message(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="chat-1", content="继续帮我别的事")
    )

    assert out is not None
    assert "There is already a pending cron retry" in out.content
    assert "/confirm" in out.content

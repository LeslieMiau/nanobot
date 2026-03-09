import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatDecisionError, HeartbeatService
from nanobot.providers.base import LLMResponse, ToolCallRequest


class DummyProvider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_build_decision_messages_includes_current_time_context(tmp_path, monkeypatch) -> None:
    service = HeartbeatService(
        workspace=tmp_path,
        provider=DummyProvider([]),
        model="openai/gpt-4o-mini",
    )
    monkeypatch.setattr(
        service,
        "_current_time_context",
        lambda: "Current local time: 2026-03-08 09:00:00 (CST, UTC+08:00)",
    )

    messages = service._build_decision_messages("heartbeat content")

    assert messages[1]["content"].startswith(
        "Current local time: 2026-03-08 09:00:00 (CST, UTC+08:00)"
    )
    assert "should run now" in messages[1]["content"]


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call_and_empty_content(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_decide_raises_when_provider_returns_plain_text(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="Error: backend unavailable", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    with pytest.raises(HeartbeatDecisionError):
        await service._decide("heartbeat content")


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert called_with == ["check open tasks"]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    assert await service.trigger_now() is None


@pytest.mark.asyncio
async def test_tick_reports_decision_error_once_until_success(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})],
        ),
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
    ])

    seen: list[tuple[str, str]] = []

    async def _on_error(phase: str, error: Exception) -> None:
        seen.append((phase, str(error)))

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_error=_on_error,
    )

    await service._tick()
    await service._tick()
    await service._tick()
    await service._tick()

    assert seen == [
        ("decision", "Heartbeat decision returned plain text instead of a tool call: Error: backend unavailable"),
        ("decision", "Heartbeat decision returned plain text instead of a tool call: Error: backend unavailable"),
    ]


@pytest.mark.asyncio
async def test_tick_reports_execution_error(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    seen: list[tuple[str, str]] = []

    async def _on_execute(_tasks: str) -> str:
        raise RuntimeError("execution boom")

    async def _on_error(phase: str, error: Exception) -> None:
        seen.append((phase, str(error)))

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
        on_error=_on_error,
    )

    await service._tick()

    assert seen == [("execution", "execution boom")]


@pytest.mark.asyncio
async def test_tick_retries_transient_decision_error_once(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})],
        ),
    ])

    seen: list[tuple[str, str]] = []
    recovery: list[tuple[str, dict[str, object]]] = []

    async def _on_error(phase: str, error: Exception) -> None:
        seen.append((phase, str(error)))

    async def _on_recovery(status: str, payload: dict[str, object]) -> None:
        recovery.append((status, payload))

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_error=_on_error,
        on_recovery=_on_recovery,
        decision_retry_delay_s=0.01,
    )

    await service._tick()
    await asyncio.sleep(0.05)

    assert provider.calls == 2
    assert service._decision_retry_task is None
    assert service._last_error_signature is None
    assert seen == [
        ("decision", "Heartbeat decision returned plain text instead of a tool call: Error: backend unavailable"),
    ]
    assert [status for status, _payload in recovery] == ["scheduled", "recovered"]
    assert recovery[0][1]["phase"] == "decision"
    assert recovery[0][1]["retry_delay_s"] == 0.01


@pytest.mark.asyncio
async def test_tick_does_not_retry_non_transient_decision_error(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="Error: invalid response schema", tool_calls=[]),
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})],
        ),
    ])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        decision_retry_delay_s=0.01,
    )

    await service._tick()
    await asyncio.sleep(0.05)

    assert provider.calls == 1
    assert len(provider._responses) == 1


@pytest.mark.asyncio
async def test_tick_reports_when_transient_decision_retry_is_exhausted(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
    ])

    recovery: list[tuple[str, dict[str, object]]] = []

    async def _on_recovery(status: str, payload: dict[str, object]) -> None:
        recovery.append((status, payload))

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_recovery=_on_recovery,
        decision_retry_delay_s=0.01,
    )

    await service._tick()
    await asyncio.sleep(0.05)

    assert provider.calls == 2
    assert [status for status, _payload in recovery] == ["scheduled", "exhausted"]
    assert "HeartbeatDecisionError" in str(recovery[1][1]["latest_error"])


@pytest.mark.asyncio
async def test_tick_dedupes_transient_decision_retry_until_success(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(content="Error: backend unavailable", tool_calls=[]),
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="hb_1", name="heartbeat", arguments={"action": "skip"})],
        ),
    ])

    recovery: list[tuple[str, dict[str, object]]] = []

    async def _on_recovery(status: str, payload: dict[str, object]) -> None:
        recovery.append((status, payload))

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_recovery=_on_recovery,
        decision_retry_delay_s=0.03,
    )

    await service._tick()
    await service._tick()
    await asyncio.sleep(0.08)

    assert provider.calls == 3
    assert service._decision_retry_task is None
    assert [status for status, _payload in recovery] == ["scheduled", "recovered"]

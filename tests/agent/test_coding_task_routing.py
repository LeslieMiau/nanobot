from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore


def _make_loop(tmp_path: Path):
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    store = CodingTaskStore(tmp_path / "automation" / "coding_tasks.json")
    manager = CodexWorkerManager(tmp_path, store)

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            coding_task_manager=manager,
        )
    return loop, store


@pytest.mark.asyncio
async def test_private_telegram_start_coding_creates_task_and_acknowledges(tmp_path: Path) -> None:
    loop, store = _make_loop(tmp_path)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 42},
        )
    )

    assert response is not None
    assert "已创建编程任务" in response.content
    assert "状态: queued" in response.content

    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].repo_path == str(repo_path)
    assert tasks[0].goal == "修复登录回调"
    assert tasks[0].metadata["origin_channel"] == "telegram"
    assert tasks[0].metadata["origin_chat_id"] == "chat-1"
    assert tasks[0].metadata["requested_via"] == "telegram_private_chat"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_without_repo_or_goal_returns_usage(tmp_path: Path) -> None:
    loop, store = _make_loop(tmp_path)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="开始编程",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "请用以下格式创建编程任务" in response.content
    assert store.list_tasks() == []

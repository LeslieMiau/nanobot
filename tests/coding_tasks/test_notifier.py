from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.notifier import CodingTaskNotifier
from nanobot.coding_tasks.progress import PlanProgress, TaskProgressReport
from nanobot.coding_tasks.store import CodingTaskStore


async def _send_collector(sent: list[OutboundMessage], msg: OutboundMessage) -> None:
    sent.append(msg)


def _make_report(summary: str = "summary") -> TaskProgressReport:
    return TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Running pytest",
        branch_name="",
        recent_commit_summary="",
        summary=summary,
    )


def test_notifier_skips_starting_notifications(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, _make_report()))

    assert sent == []


def test_notifier_skips_running_notifications(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    task = manager.mark_running(task.id, summary="Working")
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, _make_report()))

    assert sent == []


def test_notifier_sends_terminal_notifications(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    manager.update_metadata(
        task.id,
        updates={"worktree_branch": "codex/task-123", "recent_commit_summary": "abc123 test"},
    )
    task = manager.mark_failed(task.id, summary="task_timeout: timeout")
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, _make_report("task_timeout: timeout")))

    assert len(sent) == 1
    assert "编程任务失败" in sent[0].content
    assert "任务超时" in sent[0].content
    assert "codex/task-123" in sent[0].content


def test_notifier_allows_waiting_user_notifications(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    task = manager.mark_waiting_user(task.id, summary="Need choice")
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, _make_report("Need choice")))

    assert len(sent) == 1
    assert (
        "等待你的确认" in sent[0].content
        or "仓库里已有未完成的 harness" in sent[0].content
        or "仓库里已有已完成的 harness" in sent[0].content
    )

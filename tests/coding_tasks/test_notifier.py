from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.notifier import CodingTaskNotifier
from nanobot.coding_tasks.progress import PlanProgress, TaskProgressReport
from nanobot.coding_tasks.store import CodingTaskStore


async def _send_collector(sent: list[OutboundMessage], msg: OutboundMessage) -> None:
    sent.append(msg)


def test_notifier_throttles_duplicate_progress_notifications(tmp_path) -> None:
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
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Running pytest",
        branch_name="",
        recent_commit_summary="",
        summary="已完成 1/2 项，剩余 1 项 | 当前输出: Running pytest",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))
    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1
    assert "Running pytest" in sent[0].content

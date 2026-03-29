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
    assert "编程任务进行中" in sent[0].content
    assert "目标: notify" in sent[0].content
    assert "Running pytest" in sent[0].content
    assert "已完成 1/2 项" not in sent[0].content


def test_notifier_suppresses_unchanged_content_even_after_throttle_window(tmp_path) -> None:
    import asyncio
    import time

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
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=1)

    asyncio.run(notifier.maybe_notify(task.id, report))
    time.sleep(1.1)
    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1


def test_notifier_allows_new_status_with_new_content(tmp_path) -> None:
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
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Need choice",
        branch_name="",
        recent_commit_summary="",
        summary="Need choice",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1
    assert (
        "等待你的确认" in sent[0].content
        or "仓库里已有未完成的 harness" in sent[0].content
        or "仓库里已有已完成的 harness" in sent[0].content
    )


def test_notifier_shortens_dirty_repo_note_for_running_task(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="替换底部 tab 图标",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(
        task.id,
        summary=(
            "已完成 1/1 项，剩余 0 项 | 最近记录: 尝试按仓库流程补本地提交时，被当前沙箱拦截："
            "`git add package.json scripts/probe-isolated-worker.sh && git commit ...` 失败。 | 当前输出: ❯"
        ),
    )
    task = manager.mark_running(task.id, summary=task.last_progress_summary)
    report = TaskProgressReport(
        latest_note="尝试按仓库流程补本地提交时，被当前沙箱拦截",
        plan_progress=PlanProgress(completed=1, remaining=0, total=1),
        live_output="",
        branch_name="",
        recent_commit_summary="",
        summary=task.last_progress_summary,
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1
    assert "编程任务进行中" in sent[0].content
    assert "尝试按仓库流程补本地提交时，被当前沙箱拦截" in sent[0].content
    assert "已完成 1/1 项" not in sent[0].content
    assert "scripts/probe-isolated-worker.sh" not in sent[0].content

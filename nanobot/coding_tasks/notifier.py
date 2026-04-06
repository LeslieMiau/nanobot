"""Throttled outbound notifications for coding task progress."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import TaskProgressReport
from nanobot.coding_tasks.reporting import (
    build_completion_report,
    build_failure_report,
    build_waiting_user_report,
    repo_display_name,
)


class CodingTaskNotifier:
    """Throttle and deliver coding-task notifications to the originating chat."""

    def __init__(
        self,
        manager: CodexWorkerManager,
        send_callback: Callable[[OutboundMessage], Awaitable[None]],
        *,
        throttle_s: int = 30,
        running_throttle_s: int = 120,
    ) -> None:
        self.manager = manager
        self.send_callback = send_callback
        self.throttle_s = throttle_s
        self.running_throttle_s = running_throttle_s
        self._last_sent_at: dict[str, float] = {}
        self._last_sent_signature: dict[str, tuple[str, str]] = {}

    async def maybe_notify(self, task_id: str, report: TaskProgressReport) -> bool:
        task = self.manager.require_task(task_id)
        channel = task.metadata.get("origin_channel")
        chat_id = task.metadata.get("origin_chat_id")
        if not channel or not chat_id:
            return False

        content = self._build_content(task, report)
        if not content:
            return False

        now = time.monotonic()
        signature = (task.status, content)
        last_signature = self._last_sent_signature.get(task_id)
        last_at = self._last_sent_at.get(task_id, 0.0)
        if last_signature == signature:
            return False
        effective_throttle = self.running_throttle_s if task.status == "running" else self.throttle_s
        if last_at and now - last_at < effective_throttle:
            return False

        await self.send_callback(
            OutboundMessage(channel=channel, chat_id=chat_id, content=content, metadata={"render_as": "text"})
        )
        self._last_sent_at[task_id] = now
        self._last_sent_signature[task_id] = signature
        return True

    def _build_content(self, task, report: TaskProgressReport) -> str:
        if task.status == "completed":
            return build_completion_report(task)
        if task.status == "failed":
            return build_failure_report(task)
        if task.status == "waiting_user":
            return build_waiting_user_report(task)
        if task.status == "starting":
            return self._build_start_notification(task)
        if task.status == "running":
            return self._build_running_notification(task, report)
        return ""

    def _build_start_notification(self, task) -> str:
        repo_name = repo_display_name(task)
        goal = _truncate_line(task.goal, limit=64)
        return "\n".join(
            [
                f"**已开始编程任务** · `{repo_name}`",
                f"**目标**: {goal}",
            ]
        )

    def _build_running_notification(self, task, report: TaskProgressReport) -> str:
        repo_name = repo_display_name(task)
        lines = [f"**编程进行中** · `{repo_name}`"]
        if report.plan_progress.total:
            pp = report.plan_progress
            bar = _progress_bar(pp.completed, pp.total)
            lines.append(f"**进度**: {bar} {pp.completed}/{pp.total} 项")
        detail = report.latest_note or report.live_output or ""
        if detail:
            lines.append(f"**最近**: {_truncate_line(detail, limit=200)}")
        if not report.plan_progress.total and not detail:
            return ""
        return "\n".join(lines)


def _progress_bar(completed: int, total: int, *, width: int = 6) -> str:
    if total <= 0:
        return "░" * width
    filled = round(completed / total * width)
    return "█" * filled + "░" * (width - filled)


def _truncate_line(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."

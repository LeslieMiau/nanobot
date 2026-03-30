"""Task-selection and concurrency policy for coding-task orchestration."""

from __future__ import annotations

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.types import CodingTask

_HIDDEN_TASK_STATUSES = {"failed", "cancelled"}


class CodingTaskPolicy:
    """Encapsulate MVP task-selection rules outside transport routers."""

    def __init__(self, manager: CodexWorkerManager) -> None:
        self.manager = manager

    def blocking_active_task(self) -> CodingTask | None:
        """Return the workspace-wide task that blocks creating another task."""
        return self.manager.latest_active_task()

    def select_control_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the newest active visible task for one origin chat."""
        return self.manager.latest_active_task_for_origin(channel, chat_id)

    def latest_origin_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the latest visible task for one origin chat."""
        tasks = self.manager.tasks_for_origin(channel, chat_id)
        return tasks[0] if tasks else None

    def tasks_for_origin(self, channel: str, chat_id: str) -> list[CodingTask]:
        """Return visible tasks for one origin chat, newest first."""
        return [
            task
            for task in self.manager.tasks_for_origin(channel, chat_id)
            if task.status not in _HIDDEN_TASK_STATUSES
        ]

    def task_for_origin_index(self, channel: str, chat_id: str, index: int) -> CodingTask | None:
        """Return the 1-based indexed task for one origin chat, if any."""
        if index < 1:
            return None
        tasks = self.tasks_for_origin(channel, chat_id)
        if index > len(tasks):
            return None
        return tasks[index - 1]

"""Task-selection and concurrency policy for coding-task orchestration."""

from __future__ import annotations

from nanobot.coding_tasks.harness import detect_repo_harness
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.types import CodingTask
from nanobot.coding_tasks.types import WAITING_REASON_KIND_WORKER_EXIT_REVIEW

_HIDDEN_TASK_STATUSES = {"completed", "failed", "cancelled"}
_CONTROL_TASK_STATUSES = {"starting", "running", "waiting_user"}
_HARNESS_CONFLICT_EXPECTED_STATES = {
    "repo_active_harness": "active",
    "repo_completed_harness": "completed",
}
_STALE_HARNESS_CONFLICT_SUMMARY = (
    "Cleared stale harness conflict record because the repository's current harness state no longer matches it."
)


class CodingTaskPolicy:
    """Encapsulate MVP task-selection rules outside transport routers."""

    def __init__(self, manager: CodexWorkerManager) -> None:
        self.manager = manager

    def blocking_active_task(self) -> CodingTask | None:
        """Return the workspace-wide task that blocks creating another task."""
        for task in self._reconcile_stale_harness_conflicts(self.manager.active_tasks()):
            if not self._is_nonblocking_review_wait(task):
                return task
        return None

    def select_control_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the newest active visible task for one origin chat."""
        for task in self.tasks_for_origin(channel, chat_id):
            if task.status in _CONTROL_TASK_STATUSES:
                return task
        return None

    def latest_origin_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the latest visible task for one origin chat."""
        tasks = self.manager.tasks_for_origin(channel, chat_id)
        visible = self._reconcile_stale_harness_conflicts(tasks)
        return visible[0] if visible else None

    def tasks_for_origin(self, channel: str, chat_id: str) -> list[CodingTask]:
        """Return visible tasks for one origin chat, newest first."""
        return [
            task
            for task in self._reconcile_stale_harness_conflicts(
                self.manager.tasks_for_origin(channel, chat_id)
            )
            if task.status not in _HIDDEN_TASK_STATUSES
        ]

    def visible_tasks(self, *, include_terminal: bool = False) -> list[CodingTask]:
        """Return workspace tasks in UI order, optionally including terminal history."""
        tasks = self._reconcile_stale_harness_conflicts(
            self.manager._newest_first(self.manager.store.list_tasks())
        )
        if include_terminal:
            return tasks
        return [task for task in tasks if task.status not in _HIDDEN_TASK_STATUSES]

    def task_for_origin_index(self, channel: str, chat_id: str, index: int) -> CodingTask | None:
        """Return the 1-based indexed task for one origin chat, if any."""
        if index < 1:
            return None
        tasks = self.tasks_for_origin(channel, chat_id)
        if index > len(tasks):
            return None
        return tasks[index - 1]

    @staticmethod
    def _is_nonblocking_review_wait(task: CodingTask) -> bool:
        return (
            task.status == "waiting_user"
            and task.metadata.get("waiting_reason_kind") == WAITING_REASON_KIND_WORKER_EXIT_REVIEW
        )

    def _reconcile_stale_harness_conflicts(self, tasks: list[CodingTask]) -> list[CodingTask]:
        reconciled: list[CodingTask] = []
        for task in tasks:
            if self._is_stale_harness_conflict(task):
                self.manager.cancel_task(task.id, summary=_STALE_HARNESS_CONFLICT_SUMMARY)
                continue
            reconciled.append(task)
        return reconciled

    def _is_stale_harness_conflict(self, task: CodingTask) -> bool:
        if task.status != "waiting_user":
            return False
        expected_state = _HARNESS_CONFLICT_EXPECTED_STATES.get(
            str(task.metadata.get("harness_conflict_reason") or "")
        )
        if expected_state is None:
            return False
        return detect_repo_harness(task.repo_path).harness_state != expected_state

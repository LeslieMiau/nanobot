"""Lifecycle manager for Codex-backed coding tasks."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

from nanobot.coding_tasks.store import CodingTaskStore
from nanobot.coding_tasks.types import (
    HARNESS_STATE_VALUES,
    TASK_STATUS_VALUES,
    CodingRunEvent,
    CodingTask,
    now_ms,
)
from nanobot.utils.helpers import safe_filename

_ALLOWED_TRANSITIONS = {
    "queued": {"starting", "waiting_user", "cancelled", "failed"},
    "starting": {"running", "waiting_user", "completed", "failed", "cancelled"},
    "running": {"waiting_user", "completed", "failed", "cancelled"},
    "waiting_user": {"starting", "running", "completed", "failed", "cancelled"},
    "failed": {"starting", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
_ACTIVE_TASK_STATUSES = {"starting", "running", "waiting_user"}
_ARTIFACT_SUFFIXES = (".prompt.txt", ".launch.sh", ".codex.log")


class CodexWorkerManager:
    """Track task state and session metadata for an external Codex worker."""

    def __init__(
        self,
        workspace: Path,
        store: CodingTaskStore,
        session_prefix: str = "codex-task",
    ):
        self.workspace = workspace
        self.store = store
        self.session_prefix = session_prefix

    def create_task(
        self,
        *,
        repo_path: str,
        goal: str,
        title: str | None = None,
        branch_name: str | None = None,
        approval_policy: str = "local_only",
        harness_state: str = "missing",
        metadata: dict | None = None,
    ) -> CodingTask:
        task_id = uuid.uuid4().hex[:8]
        task = CodingTask(
            id=task_id,
            title=title or Path(repo_path).name or task_id,
            repo_path=repo_path,
            goal=goal,
            branch_name=branch_name,
            tmux_session=self._default_tmux_session(task_id, repo_path),
            approval_policy=approval_policy,
            harness_state=harness_state,
            metadata=dict(metadata or {}),
        )
        self._validate_task(task)
        self.store.upsert_task(task)
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task.id,
                event="created",
                status=task.status,
                message=task.goal,
                payload={
                    "repo_path": task.repo_path,
                    "tmux_session": task.tmux_session,
                },
            )
        )
        return task

    def recoverable_tasks(self) -> list[CodingTask]:
        return self.store.list_tasks_by_status("starting", "running", "waiting_user")

    def active_tasks(self) -> list[CodingTask]:
        """Return workspace-wide active tasks newest first."""
        tasks = self._newest_first(self.store.list_tasks())
        return [task for task in tasks if task.status in _ACTIVE_TASK_STATUSES]

    def latest_active_task(self) -> CodingTask | None:
        """Return the newest actively running task in this workspace, if any."""
        tasks = self.active_tasks()
        return tasks[0] if tasks else None

    def tasks_for_origin(self, channel: str, chat_id: str) -> list[CodingTask]:
        """Return tasks created from the given origin channel/chat, newest first."""
        tasks = [
            task
            for task in self.store.list_tasks()
            if task.metadata.get("origin_channel") == channel
            and task.metadata.get("origin_chat_id") == chat_id
        ]
        return self._newest_first(tasks)

    def latest_active_task_for_origin(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the newest actively running task for an origin chat, if any."""
        for task in self.tasks_for_origin(channel, chat_id):
            if task.status in _ACTIVE_TASK_STATUSES:
                return task
        return None

    @staticmethod
    def _newest_first(tasks: list[CodingTask]) -> list[CodingTask]:
        indexed = list(enumerate(tasks))
        indexed.sort(
            key=lambda pair: (pair[1].updated_at_ms, pair[1].created_at_ms, pair[0]),
            reverse=True,
        )
        return [task for _, task in indexed]

    def record_user_control(self, task_id: str, control: str) -> CodingTask:
        task = self.require_task(task_id)
        updated = replace(
            task,
            last_user_control=control,
            updated_at_ms=now_ms(),
        )
        self.store.upsert_task(updated)
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task_id,
                event="user_control",
                status=updated.status,
                message=control,
            )
        )
        return updated

    def update_metadata(
        self,
        task_id: str,
        *,
        updates: dict | None = None,
        remove_keys: tuple[str, ...] = (),
    ) -> CodingTask:
        """Merge task metadata fields without changing lifecycle state."""
        task = self.require_task(task_id)
        metadata = dict(task.metadata)
        for key in remove_keys:
            metadata.pop(key, None)
        if updates:
            metadata.update(updates)
        if metadata == task.metadata:
            return task
        updated = replace(
            task,
            metadata=metadata,
            updated_at_ms=now_ms(),
        )
        self.store.upsert_task(updated)
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task_id,
                event="metadata_updated",
                status=updated.status,
                payload={
                    "updated_keys": sorted((updates or {}).keys()),
                    "removed_keys": list(remove_keys),
                },
            )
        )
        return updated

    def update_progress(self, task_id: str, summary: str) -> CodingTask:
        """Refresh the last visible progress summary without changing status."""
        task = self.require_task(task_id)
        if summary == task.last_progress_summary:
            return task
        timestamp = now_ms()
        updated = replace(
            task,
            last_progress_summary=summary,
            last_progress_at_ms=timestamp,
            updated_at_ms=timestamp,
        )
        self.store.upsert_task(updated)
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task_id,
                event="progress_updated",
                status=updated.status,
                message=summary,
            )
        )
        return updated

    def update_repo_metadata(
        self,
        task_id: str,
        *,
        branch_name: str | None = None,
        recent_commit_summary: str | None = None,
        latest_note: str | None = None,
    ) -> CodingTask:
        """Persist repo-derived metadata without changing lifecycle state."""
        task = self.require_task(task_id)
        metadata = dict(task.metadata)
        if recent_commit_summary:
            metadata["recent_commit_summary"] = recent_commit_summary
        if latest_note:
            metadata["latest_note"] = latest_note
        if (
            (branch_name or task.branch_name) == task.branch_name
            and metadata == task.metadata
        ):
            return task
        updated = replace(
            task,
            branch_name=branch_name or task.branch_name,
            metadata=metadata,
            updated_at_ms=now_ms(),
        )
        self.store.upsert_task(updated)
        return updated

    def mark_starting(
        self,
        task_id: str,
        *,
        tmux_session: str | None = None,
        codex_session_hint: str | None = None,
        harness_state: str | None = None,
        summary: str = "",
    ) -> CodingTask:
        payload: dict[str, str] = {}
        if tmux_session:
            payload["tmux_session"] = tmux_session
        if codex_session_hint:
            payload["codex_session_hint"] = codex_session_hint
        if harness_state:
            payload["harness_state"] = harness_state
        return self._transition(task_id, "starting", summary=summary, extra=payload)

    def mark_running(self, task_id: str, *, summary: str = "") -> CodingTask:
        return self._transition(task_id, "running", summary=summary)

    def mark_waiting_user(self, task_id: str, *, summary: str = "") -> CodingTask:
        return self._transition(task_id, "waiting_user", summary=summary)

    def mark_completed(self, task_id: str, *, summary: str = "") -> CodingTask:
        return self._transition(task_id, "completed", summary=summary)

    def mark_failed(self, task_id: str, *, summary: str = "") -> CodingTask:
        return self._transition(task_id, "failed", summary=summary)

    def cancel_task(self, task_id: str, *, summary: str = "") -> CodingTask:
        return self._transition(task_id, "cancelled", summary=summary)

    def require_task(self, task_id: str) -> CodingTask:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown coding task: {task_id}")
        return task

    def _transition(
        self,
        task_id: str,
        new_status: str,
        *,
        summary: str = "",
        extra: dict | None = None,
    ) -> CodingTask:
        task = self.require_task(task_id)
        self._validate_status(new_status)
        allowed = _ALLOWED_TRANSITIONS.get(task.status, set())
        if new_status != task.status and new_status not in allowed:
            raise ValueError(f"Cannot transition coding task {task_id} from {task.status} to {new_status}")

        fields = dict(extra or {})
        fields["status"] = new_status
        fields["updated_at_ms"] = now_ms()
        if summary:
            fields["last_progress_summary"] = summary
            fields["last_progress_at_ms"] = fields["updated_at_ms"]

        updated = replace(task, **fields)
        self._validate_task(updated)
        self.store.upsert_task(updated)
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task_id,
                event="status_changed",
                status=updated.status,
                message=summary,
                payload={
                    "from": task.status,
                    "to": updated.status,
                    "tmux_session": updated.tmux_session or "",
                    "codex_session_hint": updated.codex_session_hint or "",
                    "harness_state": updated.harness_state,
                },
            )
        )
        if new_status == "completed":
            self._cleanup_task_artifacts(updated)
        return updated

    def _default_tmux_session(self, task_id: str, repo_path: str) -> str:
        repo_name = safe_filename(Path(repo_path).name or "repo")
        return f"{self.session_prefix}-{repo_name}-{task_id}"

    def _validate_status(self, status: str) -> None:
        if status not in TASK_STATUS_VALUES:
            raise ValueError(f"Unknown coding task status: {status}")

    def _validate_task(self, task: CodingTask) -> None:
        self._validate_status(task.status)
        if task.harness_state not in HARNESS_STATE_VALUES:
            raise ValueError(f"Unknown harness state: {task.harness_state}")

    def _cleanup_task_artifacts(self, task: CodingTask) -> None:
        removed: list[str] = []
        failed: list[str] = []

        for path in self._task_artifact_paths(task.id):
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                failed.append(f"{path.name}: {exc}")

        message = "Removed task artifacts after completion."
        if failed:
            message = "Best-effort artifact cleanup completed with errors."
        self.store.append_run_event(
            CodingRunEvent(
                task_id=task.id,
                event="artifact_cleanup",
                status=task.status,
                message=message,
                payload={
                    "removed_files": removed,
                    "failed_files": failed,
                },
            )
        )

    def _task_artifact_paths(self, task_id: str) -> list[Path]:
        artifact_dir = self.workspace / "automation" / "coding" / "artifacts"
        return [artifact_dir / f"{task_id}{suffix}" for suffix in _ARTIFACT_SUFFIXES]

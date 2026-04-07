"""Types for Codex-backed coding tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def now_ms() -> int:
    """Return the current Unix timestamp in milliseconds."""
    import time

    return int(time.time() * 1000)


TASK_STATUS_VALUES = (
    "queued",
    "starting",
    "running",
    "waiting_user",
    "completed",
    "failed",
    "cancelled",
)

HARNESS_STATE_VALUES = (
    "missing",
    "initializing",
    "active",
    "completed",
)

HARNESS_RESOLUTION_VALUES = (
    "resume_existing",
    "start_new_goal",
)

WAITING_REASON_KIND_WORKER_INPUT = "worker_input"
WAITING_REASON_KIND_WORKER_EXIT_REVIEW = "worker_exit_review"

FAILURE_SESSION_DISAPPEARED = "session_disappeared"
FAILURE_TIMEOUT = "task_timeout"
FAILURE_STALE = "task_stale"
FAILURE_LAUNCH_ERROR = "launch_error"
FAILURE_USER_CANCELLED = "user_cancelled"
FAILURE_CODEX_CRASH = "codex_crash"
FAILURE_POSTFLIGHT = "postflight_failed"

TASK_METADATA_WORKTREE_PATH = "worktree_path"
TASK_METADATA_WORKTREE_BRANCH = "worktree_branch"
TASK_METADATA_POSTFLIGHT_STAGE = "postflight_stage"
TASK_METADATA_POSTFLIGHT_RESULT = "postflight_result"
TASK_METADATA_POSTFLIGHT_SUMMARY = "postflight_summary"
TASK_METADATA_PRESERVE_FAILURE_WORKTREE = "preserve_failure_worktree"


@dataclass(slots=True)
class CodingTask:
    """Persistent metadata for one Codex-backed coding task."""

    id: str
    title: str
    repo_path: str
    goal: str
    status: str = "queued"
    branch_name: str | None = None
    tmux_session: str | None = None
    codex_session_hint: str | None = None
    harness_state: str = "missing"
    approval_policy: str = "local_only"
    last_progress_summary: str = ""
    last_progress_at_ms: int | None = None
    last_user_control: str | None = None
    created_at_ms: int = field(default_factory=now_ms)
    updated_at_ms: int = field(default_factory=now_ms)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CodingRunEvent:
    """Append-only run log entry for one coding task."""

    task_id: str
    event: str
    status: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    run_at_ms: int = field(default_factory=now_ms)


def task_worktree_path(task: CodingTask) -> str:
    """Return the persisted per-task worktree path when present."""
    value = task.metadata.get(TASK_METADATA_WORKTREE_PATH)
    return str(value).strip() if value else ""


def task_workspace_path(task: CodingTask) -> str:
    """Return the active filesystem path for one task."""
    worktree = task_worktree_path(task)
    if worktree and Path(worktree).exists():
        return worktree
    return task.repo_path


def task_worktree_branch(task: CodingTask) -> str:
    """Return the persisted per-task worktree branch when present."""
    value = task.metadata.get(TASK_METADATA_WORKTREE_BRANCH)
    return str(value).strip() if value else ""

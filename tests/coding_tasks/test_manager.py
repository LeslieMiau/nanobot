from pathlib import Path

import pytest

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore


def test_create_task_assigns_tmux_session_and_logs_creation(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)

    task = manager.create_task(
        repo_path="/Users/miau/Documents/nanobot",
        goal="Wire Codex worker",
        title="Codex worker",
    )

    assert task.status == "queued"
    assert task.tmux_session is not None
    assert task.tmux_session.startswith("codex-task-nanobot-")

    events = store.read_run_events(task.id)
    assert len(events) == 1
    assert events[0].event == "created"
    assert events[0].status == "queued"

    reloaded = store.get_task(task.id)
    assert reloaded is not None
    assert reloaded.id == task.id
    assert reloaded.tmux_session == task.tmux_session


def test_lifecycle_transitions_update_task_and_recoverable_view(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")

    manager.mark_starting(task.id, codex_session_hint="session-1", harness_state="active", summary="Restoring harness")
    running = manager.mark_running(task.id, summary="Applying patch")
    recoverable = manager.recoverable_tasks()

    assert running.status == "running"
    assert running.codex_session_hint == "session-1"
    assert running.harness_state == "active"
    assert running.last_progress_summary == "Applying patch"
    assert [task.id for task in recoverable] == [task.id]

    done = manager.mark_completed(task.id, summary="Tests passed")
    assert done.status == "completed"
    assert manager.recoverable_tasks() == []


def test_mark_completed_removes_task_artifacts_and_keeps_audit_history(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")
    artifact_dir = tmp_path / "automation" / "coding" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = artifact_dir / f"{task.id}.prompt.txt"
    launch_path = artifact_dir / f"{task.id}.launch.sh"
    log_path = artifact_dir / f"{task.id}.codex.log"
    for path in (prompt_path, launch_path, log_path):
        path.write_text("artifact\n", encoding="utf-8")

    manager.mark_starting(task.id, summary="Boot")
    done = manager.mark_completed(task.id, summary="Tests passed")

    assert done.status == "completed"
    for path in (prompt_path, launch_path, log_path):
        assert path.exists() is False
    events = store.read_run_events(task.id)
    cleanup_events = [event for event in events if event.event == "artifact_cleanup"]
    assert len(cleanup_events) == 1
    assert sorted(cleanup_events[0].payload["removed_files"]) == sorted(
        [prompt_path.name, launch_path.name, log_path.name]
    )


def test_mark_completed_preserves_completed_status_when_artifact_cleanup_fails(monkeypatch, tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")
    artifact_dir = tmp_path / "automation" / "coding" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / f"{task.id}.codex.log"
    log_path.write_text("artifact\n", encoding="utf-8")
    original_unlink = Path.unlink

    def _broken_unlink(self: Path, *args, **kwargs):
        if self == log_path:
            raise OSError("permission denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _broken_unlink)

    manager.mark_starting(task.id, summary="Boot")
    done = manager.mark_completed(task.id, summary="Tests passed")

    assert done.status == "completed"
    assert log_path.exists() is True
    cleanup_events = [event for event in store.read_run_events(task.id) if event.event == "artifact_cleanup"]
    assert len(cleanup_events) == 1
    assert cleanup_events[0].payload["failed_files"] == [f"{log_path.name}: permission denied"]


def test_invalid_transition_is_rejected(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")
    manager.mark_starting(task.id, summary="Boot")
    manager.mark_running(task.id, summary="Running")
    manager.mark_completed(task.id, summary="Done")

    with pytest.raises(ValueError, match="Cannot transition"):
        manager.mark_running(task.id, summary="Should fail")


def test_latest_active_task_ignores_failed_and_cancelled(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    first = manager.create_task(repo_path="/tmp/repo-a", goal="first")
    second = manager.create_task(repo_path="/tmp/repo-b", goal="second")
    third = manager.create_task(repo_path="/tmp/repo-c", goal="third")

    manager.mark_starting(first.id, summary="Boot")
    manager.mark_running(first.id, summary="Running")
    manager.mark_starting(second.id, summary="Boot")
    manager.mark_failed(second.id, summary="Failed")
    manager.mark_starting(third.id, summary="Boot")
    manager.cancel_task(third.id, summary="Cancelled")

    active = manager.latest_active_task()

    assert active is not None
    assert active.id == first.id

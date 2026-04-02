from __future__ import annotations

from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import CodexProgressMonitor
from nanobot.coding_tasks.recovery import CodexTaskRecovery
from nanobot.coding_tasks.store import CodingTaskStore


def _prepare_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "PROGRESS.md").write_text("## Session update - 1\n- Recovered task\n", encoding="utf-8")
    (repo / "PLAN.json").write_text('[{"id": 1, "passes": true}]', encoding="utf-8")


def test_recovery_keeps_recoverable_task_observable_when_tmux_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Recover me")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    class _FakeLauncher:
        def has_session(self, session: str) -> bool:
            return session == task.tmux_session

        def capture_pane(self, session: str) -> str:
            return "Running pytest\n"

    monitor = CodexProgressMonitor(manager, _FakeLauncher())  # type: ignore[arg-type]
    recovery = CodexTaskRecovery(manager, _FakeLauncher(), monitor)  # type: ignore[arg-type]

    result = recovery.recover_tasks()

    assert result.recovered_ids == [task.id]
    assert result.failed_ids == []
    reloaded = store.get_task(task.id)
    assert reloaded is not None
    assert reloaded.status == "running"
    assert "Running pytest" in reloaded.last_progress_summary


def test_recovery_marks_task_failed_when_tmux_session_is_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    (repo / "PLAN.json").write_text('[{"id": 1, "passes": false}]', encoding="utf-8")
    task = manager.create_task(repo_path=str(repo), goal="Recover me")
    task = manager.mark_starting(task.id, summary="Launching")

    class _MissingLauncher:
        def has_session(self, _session: str) -> bool:
            return False

        def capture_pane(self, _session: str) -> str:
            return ""

    monitor = CodexProgressMonitor(manager, _MissingLauncher())  # type: ignore[arg-type]
    recovery = CodexTaskRecovery(manager, _MissingLauncher(), monitor)  # type: ignore[arg-type]

    result = recovery.recover_tasks()

    assert result.failed_ids == [task.id]
    reloaded = store.get_task(task.id)
    assert reloaded is not None
    assert reloaded.status == "failed"
    assert "Worker session disappeared after launch" in reloaded.last_progress_summary

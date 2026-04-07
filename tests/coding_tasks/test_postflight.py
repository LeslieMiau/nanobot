from __future__ import annotations

import json
import subprocess
from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.postflight import CodexPostflightRunner
from nanobot.coding_tasks.store import CodingTaskStore


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed repo"], cwd=repo, check=True, capture_output=True)


def test_postflight_prefers_init_sh_validation_and_records_success(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    worktree = repo / ".codex-tasks" / "abc12345"
    worktree.mkdir(parents=True)
    (worktree / "init.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    task = manager.create_task(
        repo_path=str(repo),
        goal="postflight",
        metadata={"worktree_path": str(worktree), "worktree_branch": "codex/task-abc12345"},
    )

    calls: list[tuple[list[str], str]] = []

    def _runner(cmd, **kwargs):
        calls.append((cmd, kwargs["cwd"]))
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(cmd, 0, "main\n", "")
        if cmd[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["git", "remote", "get-url"]:
            return subprocess.CompletedProcess(cmd, 0, "git@example.com:test/repo.git\n", "")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    runner = CodexPostflightRunner(manager, runner=_runner)
    result = runner.run(task)

    assert result.ok is True
    assert calls[3][0] == ["bash", "init.sh"]
    reloaded = store.get_task(task.id)
    assert reloaded is not None
    assert reloaded.metadata["postflight_result"] == "passed"


def test_postflight_fails_when_validation_command_is_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    worktree = repo / ".codex-tasks" / "abc12345"
    worktree.mkdir(parents=True)
    task = manager.create_task(
        repo_path=str(repo),
        goal="postflight",
        metadata={"worktree_path": str(worktree), "worktree_branch": "codex/task-abc12345"},
    )

    runner = CodexPostflightRunner(manager)
    result = runner.run(task)

    assert result.ok is False
    assert "no safe validation command" in result.summary


def test_postflight_fails_on_dirty_main_worktree(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    worktree = repo / ".codex-tasks" / "abc12345"
    worktree.mkdir(parents=True)
    (worktree / "package.json").write_text(json.dumps({"scripts": {"test": "echo test"}, "packageManager": "pnpm@10.0.0"}), encoding="utf-8")
    task = manager.create_task(
        repo_path=str(repo),
        goal="postflight",
        metadata={"worktree_path": str(worktree), "worktree_branch": "codex/task-abc12345"},
    )

    runner = CodexPostflightRunner(manager)
    result = runner.run(task)

    assert result.ok is False
    assert "dirty" in result.summary


def test_postflight_ignores_codex_task_artifact_directory_when_checking_dirty_main(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    worktree = repo / ".codex-tasks" / "abc12345"
    worktree.mkdir(parents=True)
    (worktree / "init.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    task = manager.create_task(
        repo_path=str(repo),
        goal="postflight",
        metadata={"worktree_path": str(worktree), "worktree_branch": "codex/task-abc12345"},
    )

    calls: list[tuple[list[str], str]] = []

    def _runner(cmd, **kwargs):
        calls.append((cmd, kwargs["cwd"]))
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(cmd, 0, "main\n", "")
        if cmd[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(cmd, 0, "?? .codex-tasks/abc12345/\n", "")
        if cmd[:3] == ["git", "remote", "get-url"]:
            return subprocess.CompletedProcess(cmd, 0, "git@example.com:test/repo.git\n", "")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    runner = CodexPostflightRunner(manager, runner=_runner)
    result = runner.run(task)

    assert result.ok is True
    assert any(cmd[:3] == ["git", "status", "--short"] for cmd, _ in calls)

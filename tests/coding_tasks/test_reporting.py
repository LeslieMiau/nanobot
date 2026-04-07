from __future__ import annotations

import subprocess
from pathlib import Path

from nanobot.coding_tasks.reporting import (
    build_completion_report,
    build_failure_report,
    build_waiting_user_report,
    classify_failure_reason,
    inspect_repo_snapshot,
)
from nanobot.coding_tasks.types import CodingTask


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init repo"], cwd=repo, check=True, capture_output=True)


def test_inspect_repo_snapshot_reads_branch_and_recent_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    snapshot = inspect_repo_snapshot(repo)

    assert snapshot.branch_name == "main"
    assert "init repo" in snapshot.recent_commit_summary


def test_completion_and_failure_reports_include_actionable_context() -> None:
    task = CodingTask(
        id="task-1",
        title="demo",
        repo_path="/tmp/repo",
        goal="demo goal",
        status="completed",
        branch_name="feature/demo",
        last_progress_summary="Tests passed",
        metadata={"recent_commit_summary": "abc123 init repo", "latest_note": "Implemented demo"},
    )

    completion = build_completion_report(task)
    failure = build_failure_report(
        CodingTask(
            id="task-2",
            title="demo",
            repo_path="/tmp/repo",
            goal="demo goal",
            status="failed",
            last_progress_summary="task_timeout: 任务运行超过 4 小时，已停止 worker 并清理 worktree。",
            metadata={
                "latest_note": "Refactor complete",
                "worktree_branch": "codex/task-123",
                "recent_commit_summary": "abc123 init repo",
            },
        )
    )
    waiting = build_waiting_user_report(
        CodingTask(
            id="task-3",
            title="demo",
            repo_path="/tmp/repo",
            goal="demo goal",
            status="waiting_user",
            last_progress_summary="Need plan confirmation",
        )
    )
    conflict_waiting = build_waiting_user_report(
        CodingTask(
            id="task-4",
            title="demo",
            repo_path="/tmp/repo",
            goal="replace settings icon",
            status="waiting_user",
            last_progress_summary="Need plan confirmation",
            metadata={
                "harness_conflict_reason": "repo_active_harness",
                "existing_harness_summary": "continue old task",
            },
        )
    )
    completed_conflict_waiting = build_waiting_user_report(
        CodingTask(
            id="task-5",
            title="demo",
            repo_path="/tmp/repo",
            goal="replace settings icon",
            status="waiting_user",
            last_progress_summary="Need plan confirmation",
            metadata={
                "harness_conflict_reason": "repo_completed_harness",
                "existing_harness_summary": "completed prior mobile shell cleanup",
            },
        )
    )
    exit_review_waiting = build_waiting_user_report(
        CodingTask(
            id="task-6",
            title="demo",
            repo_path="/tmp/repo",
            goal="replace settings icon",
            status="waiting_user",
            branch_name="feature/demo",
            last_progress_summary="Worker session exited after substantial progress; review the current result before deciding whether to resume.",
            metadata={
                "waiting_reason_kind": "worker_exit_review",
                "recent_commit_summary": "abc123 init repo",
                "latest_note": "Completed review flow UI",
                "exit_review_progress": "验证证据已经拿到了",
            },
        )
    )

    assert "**分支**: feature/demo" in completion
    assert "`/coding repo <新目标>`" in completion
    assert "**最近提交**: abc123 init repo" in completion
    assert "**故障类型**: 任务超时" in failure
    assert "**worktree 分支**: codex/task-123" in failure
    assert "**最近成功步骤**: Refactor complete" in failure
    assert "**操作**: `继续` 重试 · `/coding stop` 终止" in failure
    assert "**等待原因**: Need plan confirmation" in waiting
    assert "**操作**: `继续` · `取消`" in waiting
    assert "**旧任务摘要**: continue old task" in conflict_waiting
    assert "**操作**: `继续旧任务` · `按新任务开始` · `取消`" in conflict_waiting
    assert "已有已完成的 harness" in completed_conflict_waiting
    assert "**历史摘要**: completed prior mobile shell cleanup" in completed_conflict_waiting
    assert "等待你确认结果" in exit_review_waiting
    assert "**最后进展**: 验证证据已经拿到了" in exit_review_waiting
    assert "不会阻塞新任务" in exit_review_waiting


def test_classify_failure_reason_recognizes_known_prefixes() -> None:
    assert classify_failure_reason("session_disappeared: tmux died") == "session_disappeared"
    assert classify_failure_reason("task_timeout: exceeded 4 hours") == "task_timeout"
    assert classify_failure_reason("task_stale: no progress") == "task_stale"
    assert classify_failure_reason("launch_error: startup failed") == "launch_error"

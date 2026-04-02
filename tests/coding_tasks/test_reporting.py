from __future__ import annotations

import subprocess
from pathlib import Path

from nanobot.coding_tasks.reporting import (
    build_completion_report,
    build_failure_report,
    build_waiting_user_report,
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
            last_progress_summary="pytest failed on test_x",
            metadata={"latest_note": "Refactor complete"},
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
    assert "**最近提交**: abc123 init repo" in completion
    assert "**最近成功步骤**: Refactor complete" in failure
    assert "**恢复建议**" in failure
    assert "**等待原因**: Need plan confirmation" in waiting
    assert "**旧任务摘要**: continue old task" in conflict_waiting
    assert "按新任务开始" in conflict_waiting
    assert "已有已完成的 harness" in completed_conflict_waiting
    assert "**历史摘要**: completed prior mobile shell cleanup" in completed_conflict_waiting
    assert "等待你确认结果" in exit_review_waiting
    assert "**最后进展**: 验证证据已经拿到了" in exit_review_waiting
    assert "不会阻塞新任务" in exit_review_waiting

"""Repo metadata inspection and user-facing coding task reports."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from nanobot.coding_tasks.types import CodingTask, WAITING_REASON_KIND_WORKER_EXIT_REVIEW

_WAITING_PATTERNS = (
    "waiting for user",
    "waiting for approval",
    "need approval",
    "need plan confirmation",
    "waiting for confirmation",
)


@dataclass(slots=True)
class RepoSnapshot:
    """Recent repo metadata useful for status and completion reporting."""

    branch_name: str = ""
    recent_commit_summary: str = ""


def inspect_repo_snapshot(repo_path: str | Path) -> RepoSnapshot:
    """Inspect git branch and latest commit summary when available."""
    root = Path(repo_path)
    branch = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run_git(root, ["log", "--oneline", "-1"])
    return RepoSnapshot(branch_name=branch, recent_commit_summary=commit)


def detect_waiting_reason(text: str) -> str:
    """Extract a human-facing waiting reason from live output when present."""
    lowered = text.lower()
    for pattern in _WAITING_PATTERNS:
        if pattern in lowered:
            return text.strip()
    return ""


def repo_display_name(task_or_path: CodingTask | str | Path) -> str:
    """Return a short repo display name for Telegram-facing summaries."""
    repo_path = task_or_path.repo_path if isinstance(task_or_path, CodingTask) else str(task_or_path)
    return Path(repo_path).name or str(repo_path)


def build_coding_help_report(note: str | None = None) -> str:
    """Build the shared Telegram help surface for `/coding` commands."""
    lines = ["**/coding 命令**"]
    if note:
        lines.append(note)
    lines.extend(
        [
            "",
            "`/coding <repo> <goal>`",
            "开始并启动新的编程任务。",
            "",
            "`/coding help`",
            "查看这份命令说明。",
            "",
            "`/coding list`",
            "查看当前私聊里可管理的编程任务。",
            "",
            "`/coding status [index]`",
            "查看当前任务或指定序号任务的状态。",
            "",
            "`/coding pause [index]`",
            "暂停当前任务或指定序号任务。",
            "",
            "`/coding resume [index]`",
            "继续当前任务或指定序号任务。",
            "",
            "`/coding stop [index]`",
            "结束当前任务或指定序号任务。",
            "",
            "兼容控制词：`状态`、`继续`、`停止`、`取消`、`继续旧任务`、`按新任务开始`",
        ]
    )
    return "\n".join(lines)


def build_completion_report(task: CodingTask) -> str:
    """Build a completion summary for CLI or Telegram delivery."""
    lines = _base_task_report("**编程任务已完成**", task)
    if latest_note := _latest_note(task):
        lines.append(f"**最近记录**: {latest_note}")
    lines.append(f"**结果**: {task.last_progress_summary or 'Completed'}")
    lines.append("**下一步**: 如需继续新目标，直接重新发起 `/coding <repo> <goal>`。")
    return "\n".join(lines)


def build_failure_report(task: CodingTask) -> str:
    """Build a failure summary with resume guidance."""
    lines = _base_task_report("**编程任务失败**", task)
    lines.append(f"**原因**: {task.last_progress_summary or _latest_note(task) or '-'}")
    if recent := _latest_note(task):
        lines.append(f"**最近成功步骤**: {recent}")
    lines.append("**恢复建议**: 发送 `继续` 或 `/coding resume` 重试；如需放弃可发送 `/coding stop`。")
    return "\n".join(lines)


def build_waiting_user_report(task: CodingTask) -> str:
    """Build a report for tasks waiting on explicit human input."""
    if task.metadata.get("harness_conflict_reason") == "repo_active_harness":
        lines = [
            "**仓库里已有未完成的 harness**",
            f"**仓库**: `{repo_display_name(task)}`",
        ]
        if existing := task.metadata.get("existing_harness_summary"):
            lines.append(f"**旧任务摘要**: {existing}")
        lines.append(f"**你的新目标**: {task.goal}")
        lines.append("**下一步**: 回复 `继续旧任务`、`按新任务开始` 或 `取消`。")
        return "\n".join(lines)
    if task.metadata.get("harness_conflict_reason") == "repo_completed_harness":
        lines = [
            "**仓库里已有已完成的 harness，可作为历史上下文参考**",
            f"**仓库**: `{repo_display_name(task)}`",
        ]
        if existing := task.metadata.get("existing_harness_summary"):
            lines.append(f"**历史摘要**: {existing}")
        lines.append(f"**你的新目标**: {task.goal}")
        lines.append("**下一步**: 回复 `继续旧任务`、`按新任务开始` 或 `取消`。")
        return "\n".join(lines)

    if task.metadata.get("waiting_reason_kind") == WAITING_REASON_KIND_WORKER_EXIT_REVIEW:
        lines = _base_task_report("**编程任务等待你确认结果**", task)
        if latest_note := _latest_note(task):
            lines.append(f"**最近记录**: {latest_note}")
        if recent := _last_meaningful_progress(task):
            lines.append(f"**最后进展**: {recent}")
        lines.append(f"**等待原因**: {task.last_progress_summary or '-'}")
        lines.append(
            "**下一步**: 发送 `状态` 或 `/coding status` 查看详情；如需继续，发送 `继续` 或 `/coding resume`。这个待确认状态不会阻塞新任务。"
        )
        return "\n".join(lines)

    lines = _base_task_report("**编程任务等待你的确认**", task)
    lines.append(f"**等待原因**: {task.last_progress_summary or '-'}")
    lines.append("**下一步**: 回复 `继续` 或 `取消`。")
    return "\n".join(lines)


def _base_task_report(title: str, task: CodingTask) -> list[str]:
    repo_name = repo_display_name(task)
    lines = [
        f"{title} · `{repo_name}`",
        f"**目标**: {task.goal}",
    ]
    if task.branch_name:
        lines.append(f"**分支**: {task.branch_name}")
    if recent_commit := _recent_commit(task):
        lines.append(f"**最近提交**: {recent_commit}")
    return lines


def _recent_commit(task: CodingTask) -> str:
    return str(task.metadata.get("recent_commit_summary") or "").strip()


def _latest_note(task: CodingTask) -> str:
    return str(task.metadata.get("latest_note") or "").strip()


def _last_meaningful_progress(task: CodingTask) -> str:
    return str(task.metadata.get("exit_review_progress") or task.metadata.get("last_meaningful_progress") or "").strip()


def _run_git(repo_path: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return ""
    return (result.stdout or "").strip()

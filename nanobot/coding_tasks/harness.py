"""Harness detection and Codex bootstrap prompt construction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class RepoHarnessState:
    """Detected harness-related files in a target repository."""

    repo_path: str
    has_plan: bool
    has_progress: bool
    has_init: bool
    latest_note: str = ""
    plan_summary: str = ""
    plan_completed: bool | None = None

    @property
    def harness_state(self) -> str:
        if self.has_plan and self.has_progress and self.has_init:
            if self.plan_completed is True:
                return "completed"
            return "active"
        if self.has_plan or self.has_progress or self.has_init:
            return "initializing"
        return "missing"

    @property
    def summary(self) -> str:
        if self.latest_note:
            return self.latest_note
        return self.plan_summary


def detect_repo_harness(repo_path: str | Path) -> RepoHarnessState:
    """Inspect a repository for standard long-running harness files."""
    root = Path(repo_path).expanduser().resolve()
    latest_note = _read_latest_progress_note(root / "PROGRESS.md")
    plan_summary, plan_completed = _summarize_plan_progress(root / "PLAN.json")
    if plan_completed is None:
        plan_completed = _infer_completed_from_text(latest_note, plan_summary)
    return RepoHarnessState(
        repo_path=str(root),
        has_plan=(root / "PLAN.json").exists(),
        has_progress=(root / "PROGRESS.md").exists(),
        has_init=(root / "init.sh").exists(),
        latest_note=latest_note,
        plan_summary=plan_summary,
        plan_completed=plan_completed,
    )


def build_codex_bootstrap_prompt(
    *,
    repo_path: str | Path,
    goal: str,
    branch_name: str | None = None,
    approval_policy: str = "local_only",
    harness: RepoHarnessState | None = None,
    harness_resolution: str = "resume_existing",
) -> str:
    """Build the initial prompt nanobot should send to Codex for a coding task."""
    state = harness or detect_repo_harness(repo_path)
    root = Path(repo_path).expanduser().resolve()
    lines = [
        "You are Codex running as nanobot's coding worker.",
        f"Target repository: {root}",
        f"Task goal: {goal}",
        f"Approval policy: {approval_policy}",
    ]
    if branch_name:
        lines.append(f"Preferred branch: {branch_name}")

    lines.extend(
        [
            "Execution boundaries:",
            "- You may read and edit repository files, run local tests, and create local commits when appropriate.",
            "- Do not push, deploy, or perform external side effects unless nanobot explicitly says so.",
            "- Follow the repository's AGENTS.md and local instructions without overwriting them.",
        ]
    )
    if (root / "AGENTS.md").exists():
        lines.append("Repository instructions detected: read AGENTS.md before any edits.")

    if state.harness_state == "active":
        if state.summary:
            lines.append(f"Existing harness summary: {state.summary}")
        if harness_resolution == "start_new_goal":
            lines.extend(
                [
                    "Harness mode: existing harness detected, but the user explicitly chose to start a new goal.",
                    "Before editing anything, read the existing PROGRESS.md and PLAN.json only to recover constraints and recent context.",
                    "Do not continue the old unfinished harness features as the primary task.",
                    "Treat the previous harness as background context, then re-anchor the repository around the new task goal.",
                    "If repository instructions require a harness, refresh PLAN.json and PROGRESS.md so they describe the new goal before implementation continues.",
                    "After that reset step, continue the requested new task goal.",
                ]
            )
        else:
            lines.extend(
                [
                    "Harness mode: existing harness detected.",
                    "Before editing anything, restore the repository state:",
                    "1. Read PROGRESS.md.",
                    "2. Read PLAN.json.",
                    "3. Run the repository startup sequence, including init.sh if present.",
                    "4. Verify existing functionality still works before new edits.",
                    "Only after restoring context should you continue the requested task goal.",
                ]
            )
    elif state.harness_state == "completed":
        if state.summary:
            lines.append(f"Completed harness summary: {state.summary}")
        if harness_resolution == "start_new_goal":
            lines.extend(
                [
                    "Harness mode: completed harness detected, and the user explicitly chose to start a new goal.",
                    "Before editing anything, read the existing PROGRESS.md and PLAN.json only to recover historical context and constraints.",
                    "Do not treat the previous completed harness as unfinished work that must be resumed.",
                    "Treat the completed harness as background reference, then anchor the repository around the new task goal.",
                    "If repository instructions require a harness refresh for the new goal, update PLAN.json and PROGRESS.md before implementation continues.",
                    "After that reset step, continue the requested new task goal.",
                ]
            )
        else:
            lines.extend(
                [
                    "Harness mode: completed harness detected.",
                    "Before editing anything, read the existing PROGRESS.md and PLAN.json to recover historical context and repository conventions.",
                    "Treat the prior harness as completed background context, not as unfinished work that must be resumed.",
                    "Then continue the requested task goal with that context in mind.",
                ]
            )
    else:
        lines.extend(
            [
                "Harness mode: no complete harness detected.",
                "Before implementing the task goal, initialize the repository harness:",
                "1. Create a granular PLAN.json that tracks the remaining work.",
                "2. Create PROGRESS.md with the initial state and key decisions.",
                "3. Create init.sh for repeatable startup and validation.",
                "4. Commit the harness scaffolding before feature work if the repository instructions allow it.",
                "After initialization, continue with the requested task goal.",
            ]
        )
        if state.harness_state == "initializing":
            lines.append(
                "Some harness files already exist, so preserve and complete the partial harness instead of replacing it."
            )

    return "\n".join(lines)


def _read_latest_progress_note(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for raw in reversed(lines):
        line = raw.strip()
        if not line or line.startswith("##"):
            continue
        if line.startswith("- "):
            return line[2:].strip()
        return line
    return ""


def _summarize_plan_progress(path: Path) -> tuple[str, bool | None]:
    if not path.exists():
        return "", None
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "", None
    if not isinstance(items, list) or not items:
        return "", True if isinstance(items, list) else None
    total = len(items)
    completed = sum(1 for item in items if isinstance(item, dict) and item.get("passes"))
    remaining = max(total - completed, 0)
    return f"PLAN progress: {completed}/{total} complete, {remaining} remaining", remaining == 0


def _infer_completed_from_text(*texts: str) -> bool | None:
    normalized = " ".join(text.strip().lower() for text in texts if text.strip())
    if not normalized:
        return None
    completion_markers = (
        "剩余 0 项",
        "0 remaining",
        "remaining=0",
        "remaining: 0",
        "全部完成",
        "all features complete",
        "all complete",
        "已全部完成",
    )
    for marker in completion_markers:
        if marker in normalized:
            return True
    active_markers = (
        "剩余 1 项",
        "remaining 1",
        "未完成",
        "unfinished",
        "in progress",
    )
    for marker in active_markers:
        if marker in normalized:
            return False
    return None

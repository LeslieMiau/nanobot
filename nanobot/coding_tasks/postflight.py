"""Postflight validation/merge/push flow for completed coding tasks."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.types import (
    FAILURE_POSTFLIGHT,
    TASK_METADATA_POSTFLIGHT_RESULT,
    TASK_METADATA_POSTFLIGHT_STAGE,
    TASK_METADATA_POSTFLIGHT_SUMMARY,
    TASK_METADATA_PRESERVE_FAILURE_WORKTREE,
    CodingTask,
    task_worktree_branch,
    task_workspace_path,
)


@dataclass(slots=True)
class PostflightStep:
    """One postflight shell step."""

    name: str
    command: list[str]
    cwd: str


@dataclass(slots=True)
class PostflightResult:
    """Structured result for the coding-task postflight flow."""

    ok: bool
    summary: str
    stage: str
    steps: list[dict] = field(default_factory=list)


class CodexPostflightRunner:
    """Execute test -> merge main -> push origin before completion."""

    def __init__(
        self,
        manager: CodexWorkerManager,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        target_branch: str = "main",
        target_remote: str = "origin",
    ) -> None:
        self.manager = manager
        self.runner = runner or subprocess.run
        self.target_branch = target_branch
        self.target_remote = target_remote

    def run(self, task: CodingTask) -> PostflightResult:
        """Run the postflight sequence for one task."""
        current = self.manager.require_task(task.id)
        result = str(current.metadata.get(TASK_METADATA_POSTFLIGHT_RESULT) or "")
        if result == "passed":
            summary = str(current.metadata.get(TASK_METADATA_POSTFLIGHT_SUMMARY) or current.last_progress_summary)
            return PostflightResult(ok=True, summary=summary, stage="done")

        step_results: list[dict] = []
        self.manager.update_metadata(
            current.id,
            updates={
                TASK_METADATA_POSTFLIGHT_STAGE: "validation",
                TASK_METADATA_POSTFLIGHT_RESULT: "running",
            },
            remove_keys=(TASK_METADATA_POSTFLIGHT_SUMMARY, TASK_METADATA_PRESERVE_FAILURE_WORKTREE),
        )
        try:
            steps = self._build_steps(current)
        except Exception as exc:
            summary = f"{FAILURE_POSTFLIGHT}: validation failed: {type(exc).__name__}: {exc}"
            self.manager.update_metadata(
                current.id,
                updates={
                    TASK_METADATA_POSTFLIGHT_STAGE: "validation",
                    TASK_METADATA_POSTFLIGHT_RESULT: "failed",
                    TASK_METADATA_POSTFLIGHT_SUMMARY: summary,
                    TASK_METADATA_PRESERVE_FAILURE_WORKTREE: True,
                },
            )
            return PostflightResult(ok=False, summary=summary, stage="validation", steps=step_results)

        for step in steps:
            self.manager.update_progress(current.id, f"Postflight: {step.name}")
            result = self._run_step(step)
            step_results.append(result)
            if not result["ok"]:
                summary = f"{FAILURE_POSTFLIGHT}: {step.name} failed: {result['detail']}"
                self.manager.update_metadata(
                    current.id,
                    updates={
                        TASK_METADATA_POSTFLIGHT_STAGE: step.name,
                        TASK_METADATA_POSTFLIGHT_RESULT: "failed",
                        TASK_METADATA_POSTFLIGHT_SUMMARY: summary,
                        TASK_METADATA_PRESERVE_FAILURE_WORKTREE: True,
                    },
                )
                return PostflightResult(ok=False, summary=summary, stage=step.name, steps=step_results)

            next_stage = step.name
            self.manager.update_metadata(
                current.id,
                updates={TASK_METADATA_POSTFLIGHT_STAGE: next_stage},
            )

        summary = (
            f"Postflight passed: validation ok, merged to {self.target_branch}, "
            f"pushed to {self.target_remote}/{self.target_branch}."
        )
        self.manager.update_metadata(
            current.id,
            updates={
                TASK_METADATA_POSTFLIGHT_STAGE: "done",
                TASK_METADATA_POSTFLIGHT_RESULT: "passed",
                TASK_METADATA_POSTFLIGHT_SUMMARY: summary,
            },
            remove_keys=(TASK_METADATA_PRESERVE_FAILURE_WORKTREE,),
        )
        return PostflightResult(ok=True, summary=summary, stage="done", steps=step_results)

    def _build_steps(self, task: CodingTask) -> list[PostflightStep]:
        workspace = task_workspace_path(task)
        repo_root = task.repo_path
        validation = self._detect_validation_command(Path(workspace))
        self._validate_merge_target(repo_root)
        branch_name = task_worktree_branch(task)
        return [
            PostflightStep(name="validation", command=validation, cwd=workspace),
            PostflightStep(
                name="merge",
                command=["git", "merge", "--no-edit", branch_name],
                cwd=repo_root,
            ),
            PostflightStep(
                name="push",
                command=["git", "push", self.target_remote, self.target_branch],
                cwd=repo_root,
            ),
        ]

    def _validate_merge_target(self, repo_root: str) -> None:
        branch = self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            check=True,
        ).stdout.strip()
        if branch != self.target_branch:
            raise RuntimeError(f"target repo is on {branch}, expected {self.target_branch}")
        status_output = self._run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
        ).stdout
        dirty_lines = [line for line in status_output.splitlines() if line.strip()]
        visible_dirty = [line for line in dirty_lines if not self._is_task_artifact_status(line)]
        if visible_dirty:
            raise RuntimeError(f"target branch worktree is dirty: {'; '.join(visible_dirty)}")
        remote = self._run(
            ["git", "remote", "get-url", self.target_remote],
            cwd=repo_root,
            check=True,
        ).stdout.strip()
        if not remote:
            raise RuntimeError(f"remote {self.target_remote} is missing")

    def _is_task_artifact_status(self, line: str) -> bool:
        path_text = line[3:] if len(line) > 3 else ""
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        normalized = path_text.strip().strip('"')
        return normalized == ".codex-tasks" or normalized.startswith(".codex-tasks/")

    def _detect_validation_command(self, workspace: Path) -> list[str]:
        init_path = workspace / "init.sh"
        if init_path.exists():
            return ["bash", "init.sh"]

        package_json = workspace / "package.json"
        if package_json.exists():
            try:
                payload = json.loads(package_json.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - defensive
                raise RuntimeError(f"unable to read package.json: {exc}") from exc
            scripts = payload.get("scripts") or {}
            if "test" in scripts:
                package_manager = str(payload.get("packageManager") or "")
                if package_manager.startswith("pnpm"):
                    return ["corepack", "pnpm", "test"]
                return ["npm", "test"]

        if (workspace / "pyproject.toml").exists() or (workspace / "requirements.txt").exists():
            venv_pytest = workspace / ".venv" / "bin" / "pytest"
            if venv_pytest.exists():
                return [str(venv_pytest)]
            return ["pytest"]

        raise RuntimeError("no safe validation command could be inferred")

    def _run_step(self, step: PostflightStep) -> dict:
        result = self._run(step.command, cwd=step.cwd, check=False)
        detail = (result.stderr or "").strip() or (result.stdout or "").strip() or f"exit {result.returncode}"
        return {
            "name": step.name,
            "cwd": step.cwd,
            "command": " ".join(step.command),
            "ok": result.returncode == 0,
            "detail": detail,
        }

    def _run(self, cmd: list[str], *, cwd: str, check: bool) -> subprocess.CompletedProcess[str]:
        return self.runner(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
        )

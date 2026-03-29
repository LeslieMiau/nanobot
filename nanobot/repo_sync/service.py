"""Background repo-sync watcher and safe default sync helper."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

SyncRunner = Callable[..., Awaitable[str]]


async def _run_git(
    repo_path: str | os.PathLike[str],
    *args: str,
    ssh_command: str = "",
) -> tuple[int, str, str]:
    """Run a git command and return exit code, stdout, and stderr."""
    env = os.environ.copy()
    if ssh_command:
        env["GIT_SSH_COMMAND"] = ssh_command
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(repo_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode().strip(), stderr.decode().strip()


async def sync_fork_once(
    *,
    repo_path: str | os.PathLike[str],
    branch: str = "main",
    upstream_remote: str = "upstream",
    upstream_url: str = "",
    push_remote: str = "origin",
    auto_push: bool = False,
    allow_dirty_worktree: bool = False,
    ssh_command: str = "",
) -> str:
    """Safely fast-forward a local branch from an upstream remote once."""
    path = Path(repo_path).expanduser()
    if not path.exists():
        return f"Repo sync failed: repo path does not exist: {path}"
    if not path.is_dir():
        return f"Repo sync failed: repo path is not a directory: {path}"

    code, stdout, stderr = await _run_git(path, "rev-parse", "--is-inside-work-tree", ssh_command=ssh_command)
    if code != 0 or stdout.lower() != "true":
        detail = stderr or stdout or "not a git repository"
        return f"Repo sync failed: {detail}"

    if upstream_url:
        remote_code, remote_stdout, _ = await _run_git(
            path,
            "remote",
            "get-url",
            upstream_remote,
            ssh_command=ssh_command,
        )
        if remote_code != 0:
            add_code, _, add_stderr = await _run_git(
                path,
                "remote",
                "add",
                upstream_remote,
                upstream_url,
                ssh_command=ssh_command,
            )
            if add_code != 0:
                return f"Repo sync failed: {add_stderr or 'unable to add upstream remote'}"
        elif remote_stdout != upstream_url:
            set_code, _, set_stderr = await _run_git(
                path,
                "remote",
                "set-url",
                upstream_remote,
                upstream_url,
                ssh_command=ssh_command,
            )
            if set_code != 0:
                return f"Repo sync failed: {set_stderr or 'unable to update upstream remote'}"

    status_code, status_stdout, status_stderr = await _run_git(
        path,
        "status",
        "--porcelain",
        ssh_command=ssh_command,
    )
    if status_code != 0:
        return f"Repo sync failed: {status_stderr or 'unable to inspect worktree state'}"
    if status_stdout and not allow_dirty_worktree:
        return "Repo sync failed: worktree has local changes."

    fetch_code, _, fetch_stderr = await _run_git(
        path,
        "fetch",
        upstream_remote,
        branch,
        ssh_command=ssh_command,
    )
    if fetch_code != 0:
        return f"Repo sync failed: {fetch_stderr or 'unable to fetch upstream branch'}"

    head_code, local_head, head_stderr = await _run_git(
        path,
        "rev-parse",
        "HEAD",
        ssh_command=ssh_command,
    )
    if head_code != 0:
        return f"Repo sync failed: {head_stderr or 'unable to read local HEAD'}"

    upstream_code, upstream_head, upstream_stderr = await _run_git(
        path,
        "rev-parse",
        f"{upstream_remote}/{branch}",
        ssh_command=ssh_command,
    )
    if upstream_code != 0:
        return f"Repo sync failed: {upstream_stderr or 'unable to read upstream HEAD'}"

    if local_head == upstream_head:
        return "Repo sync: already up to date."

    merge_code, _, merge_stderr = await _run_git(
        path,
        "merge",
        "--ff-only",
        f"{upstream_remote}/{branch}",
        ssh_command=ssh_command,
    )
    if merge_code != 0:
        return f"Repo sync failed: {merge_stderr or 'fast-forward merge failed'}"

    if auto_push:
        push_code, _, push_stderr = await _run_git(
            path,
            "push",
            push_remote,
            branch,
            ssh_command=ssh_command,
        )
        if push_code != 0:
            return f"Repo sync failed: {push_stderr or 'push failed after sync'}"
        return f"Repo sync: updated `{branch}` from {upstream_remote}/{branch} and pushed to {push_remote}."

    return f"Repo sync: updated `{branch}` from {upstream_remote}/{branch}."


class RepoSyncWatcher:
    """Background watcher that syncs a fork when upstream changes are detected."""

    def __init__(
        self,
        *,
        repo_path: str,
        branch: str = "main",
        upstream_remote: str = "upstream",
        upstream_url: str = "",
        push_remote: str = "origin",
        auto_push: bool = False,
        allow_dirty_worktree: bool = False,
        interval_s: float = 3600,
        sync_hour: int = -1,
        run_on_start: bool = True,
        ssh_command: str = "",
        sync_runner: SyncRunner = sync_fork_once,
    ) -> None:
        self.repo_path = repo_path
        self.branch = branch
        self.upstream_remote = upstream_remote
        self.upstream_url = upstream_url
        self.push_remote = push_remote
        self.auto_push = auto_push
        self.allow_dirty_worktree = allow_dirty_worktree
        self.interval_s = float(interval_s) if interval_s > 0 else 1.0
        self.sync_hour = sync_hour
        self.run_on_start = run_on_start
        self.ssh_command = ssh_command
        self._sync_runner = sync_runner

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._sync_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            logger.debug("Repo sync watcher already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        if 0 <= self.sync_hour <= 23:
            logger.info("Repo sync watcher started (nightly at {:02d}:00)", self.sync_hour)
        else:
            logger.info("Repo sync watcher started (interval: {:.0f}s)", self.interval_s)

        if self.run_on_start:
            try:
                await self.trigger_now()
            except Exception:
                logger.exception("Repo sync on-start failed; will retry later")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def trigger_now(self) -> str:
        """Run one sync check immediately."""
        async with self._sync_lock:
            result = await self._sync_runner(
                repo_path=self.repo_path,
                branch=self.branch,
                upstream_remote=self.upstream_remote,
                upstream_url=self.upstream_url,
                push_remote=self.push_remote,
                auto_push=self.auto_push,
                allow_dirty_worktree=self.allow_dirty_worktree,
                ssh_command=self.ssh_command,
            )

        lowered = result.lower()
        if "failed" in lowered:
            logger.warning(result)
        elif "already up to date" in lowered:
            logger.debug(result)
        else:
            logger.info(result)
        return result

    @staticmethod
    def _seconds_until_hour(hour: int) -> float:
        now = datetime.now().astimezone()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return max((target - now).total_seconds(), 0.0)

    async def _run_loop(self) -> None:
        try:
            while self._running:
                if 0 <= self.sync_hour <= 23:
                    delay = self._seconds_until_hour(self.sync_hour)
                else:
                    delay = self.interval_s
                logger.debug("Repo sync: next run in {:.0f}s", delay)
                await asyncio.sleep(delay)
                if not self._running:
                    break
                await self.trigger_now()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Repo sync watcher error")
            if self._running:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    self._task = asyncio.create_task(self._run_loop())

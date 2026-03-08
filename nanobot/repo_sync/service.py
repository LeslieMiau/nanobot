"""Deterministic git fork sync service."""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger


async def _run_git(repo: Path, *args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace").strip(), err.decode(
        "utf-8", errors="replace"
    ).strip()


async def sync_fork_once(
    *,
    repo_path: str,
    branch: str = "main",
    upstream_remote: str = "upstream",
    upstream_url: str = "https://github.com/HKUDS/nanobot.git",
    push_remote: str = "origin",
    auto_push: bool = True,
    allow_dirty_worktree: bool = False,
) -> str:
    """Sync local fork with upstream branch using fast-forward only."""
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        return f"Repo sync skipped: repo path not found: {repo}"

    code, out, _ = await _run_git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return f"Repo sync skipped: not a git repository: {repo}"

    if not allow_dirty_worktree:
        code, out, _ = await _run_git(repo, "status", "--porcelain")
        if code != 0:
            return "Repo sync failed: cannot read git status."
        if out.strip():
            return "Repo sync skipped: working tree is dirty."

    code, current_branch, _ = await _run_git(repo, "branch", "--show-current")
    if code != 0:
        return "Repo sync failed: cannot detect current branch."
    if current_branch.strip() != branch:
        return f"Repo sync skipped: current branch is '{current_branch.strip()}', expected '{branch}'."

    code, existing_url, _ = await _run_git(repo, "remote", "get-url", upstream_remote)
    if code != 0:
        code, _, err = await _run_git(repo, "remote", "add", upstream_remote, upstream_url)
        if code != 0:
            return f"Repo sync failed: cannot add upstream remote: {err or 'unknown error'}"
    elif existing_url.strip() != upstream_url:
        code, _, err = await _run_git(repo, "remote", "set-url", upstream_remote, upstream_url)
        if code != 0:
            return f"Repo sync failed: cannot set upstream remote URL: {err or 'unknown error'}"

    code, _, err = await _run_git(repo, "fetch", upstream_remote)
    if code != 0:
        return f"Repo sync failed: fetch upstream failed: {err or 'unknown error'}"

    code, counts, err = await _run_git(
        repo, "rev-list", "--left-right", "--count", f"{branch}...{upstream_remote}/{branch}"
    )
    if code != 0:
        return f"Repo sync failed: cannot compare branches: {err or 'unknown error'}"

    left_ahead, right_ahead = [int(x) for x in counts.split()]
    if left_ahead > 0:
        return (
            "Repo sync skipped: local branch has commits not in upstream "
            f"({left_ahead} ahead, {right_ahead} behind)."
        )
    if right_ahead == 0:
        return "Repo sync: already up to date."

    code, _, err = await _run_git(repo, "merge", "--ff-only", f"{upstream_remote}/{branch}")
    if code != 0:
        return f"Repo sync failed: fast-forward merge failed: {err or 'unknown error'}"

    if not auto_push:
        return f"Repo sync completed: fast-forwarded {right_ahead} commit(s) locally."

    code, _, err = await _run_git(repo, "push", push_remote, branch)
    if code != 0:
        return (
            "Repo sync partially completed: local branch updated, but push failed: "
            f"{err or 'unknown error'}"
        )

    return (
        "Repo sync completed: "
        f"fast-forwarded {right_ahead} commit(s) and pushed to {push_remote}/{branch}."
    )


class RepoSyncWatcher:
    """Background watcher that syncs a fork when upstream changes are detected."""

    def __init__(
        self,
        *,
        repo_path: str,
        branch: str = "main",
        upstream_remote: str = "upstream",
        upstream_url: str = "https://github.com/HKUDS/nanobot.git",
        push_remote: str = "origin",
        auto_push: bool = True,
        allow_dirty_worktree: bool = False,
        interval_s: float = 60.0,
        run_on_start: bool = True,
        sync_runner: Callable[..., Awaitable[str]] = sync_fork_once,
    ) -> None:
        self.repo_path = repo_path
        self.branch = branch
        self.upstream_remote = upstream_remote
        self.upstream_url = upstream_url
        self.push_remote = push_remote
        self.auto_push = auto_push
        self.allow_dirty_worktree = allow_dirty_worktree
        self.interval_s = float(interval_s) if interval_s > 0 else 1.0
        self.run_on_start = run_on_start
        self._sync_runner = sync_runner

        self._running = False
        self._task: asyncio.Task | None = None
        self._sync_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start background watcher loop."""
        if self._running:
            logger.debug("Repo sync watcher already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Repo sync watcher started (every {}s)", self.interval_s)

        if self.run_on_start:
            await self.trigger_now()

    def stop(self) -> None:
        """Stop background watcher loop."""
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
            )

        lowered = result.lower()
        if "failed" in lowered:
            logger.warning(result)
        elif "already up to date" in lowered:
            logger.debug(result)
        else:
            logger.info(result)
        return result

    async def _run_loop(self) -> None:
        """Main watcher loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self.trigger_now()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Repo sync watcher error")

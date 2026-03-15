"""Deterministic git fork sync service."""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

CONFLICT_LOG_DIR = Path.home() / ".nanobot" / "logs"


async def _run_git(repo: Path, *args: str, env: dict | None = None) -> tuple[int, str, str]:
    full_env = {**os.environ, **(env or {})}
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=full_env,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace").strip(), err.decode(
        "utf-8", errors="replace"
    ).strip()


async def _collect_conflict_info(
    repo: Path,
    branch: str,
    upstream_remote: str,
    local_ahead: int,
    upstream_ahead: int,
    rebase_err: str,
) -> Path:
    """Collect conflict details and write to a log file for later diagnosis."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_file = CONFLICT_LOG_DIR / f"repo-sync-conflict-{now}.log"
    CONFLICT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# Repo Sync Conflict Report",
        f"# Time: {datetime.now(timezone.utc).isoformat()}",
        f"# Repo: {repo}",
        f"# Branch: {branch} ({local_ahead} ahead, {upstream_ahead} behind {upstream_remote}/{branch})",
        "",
        "## Rebase error output",
        rebase_err or "(empty)",
        "",
    ]

    # Conflicting files
    code, diff_out, _ = await _run_git(repo, "diff", "--name-only", "--diff-filter=U")
    if code == 0 and diff_out.strip():
        lines.append("## Conflicting files")
        for f in diff_out.strip().splitlines():
            lines.append(f"  - {f}")
        lines.append("")

        # Show conflict markers for each file (first 50 lines)
        for f in diff_out.strip().splitlines()[:10]:
            fpath = repo / f
            if fpath.exists():
                lines.append(f"## Conflict detail: {f}")
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    # Extract only sections with conflict markers
                    in_conflict = False
                    for line in content.splitlines():
                        if line.startswith("<<<<<<<"):
                            in_conflict = True
                        if in_conflict:
                            lines.append(f"  {line}")
                        if line.startswith(">>>>>>>"):
                            in_conflict = False
                except Exception:
                    lines.append("  (could not read file)")
                lines.append("")

    # Local commits that were being rebased
    code, log_out, _ = await _run_git(
        repo, "log", "--oneline", f"{upstream_remote}/{branch}..{branch}", "--max-count=20"
    )
    if code == 0 and log_out.strip():
        lines.append("## Local commits being rebased")
        lines.append(log_out)
        lines.append("")

    # Upstream commits being integrated
    code, log_out, _ = await _run_git(
        repo, "log", "--oneline", f"{branch}..{upstream_remote}/{branch}", "--max-count=20"
    )
    if code == 0 and log_out.strip():
        lines.append("## Upstream commits being integrated")
        lines.append(log_out)
        lines.append("")

    log_file.write_text("\n".join(lines), encoding="utf-8")
    logger.warning("Repo sync conflict report saved to {}", log_file)
    return log_file


async def sync_fork_once(
    *,
    repo_path: str,
    branch: str = "main",
    upstream_remote: str = "upstream",
    upstream_url: str = "https://github.com/HKUDS/nanobot.git",
    push_remote: str = "origin",
    auto_push: bool = True,
    allow_dirty_worktree: bool = False,
    ssh_command: str = "",
) -> str:
    """Sync local fork with upstream branch.

    Strategy:
    - If local is behind upstream: fast-forward merge.
    - If local is ahead (has own commits): rebase local commits onto upstream.
    - If worktree is dirty: stash → sync → stash pop.
    - SSH push uses ssh_command to bypass proxy issues.
    """
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        return f"Repo sync skipped: repo path not found: {repo}"

    code, out, _ = await _run_git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return f"Repo sync skipped: not a git repository: {repo}"

    # Check current branch
    code, current_branch, _ = await _run_git(repo, "branch", "--show-current")
    if code != 0:
        return "Repo sync failed: cannot detect current branch."
    if current_branch.strip() != branch:
        return f"Repo sync skipped: current branch is '{current_branch.strip()}', expected '{branch}'."

    # Handle dirty worktree: stash if allowed
    stashed = False
    code, status_out, _ = await _run_git(repo, "status", "--porcelain")
    if code != 0:
        return "Repo sync failed: cannot read git status."
    is_dirty = bool(status_out.strip())

    if is_dirty:
        if not allow_dirty_worktree:
            # Auto-stash instead of giving up
            code, _, err = await _run_git(repo, "stash", "push", "-m", "repo-sync-auto-stash")
            if code != 0:
                return f"Repo sync skipped: worktree dirty and stash failed: {err or 'unknown error'}"
            stashed = True
        # If allow_dirty_worktree, proceed without stash

    git_env = {}
    if ssh_command:
        git_env["GIT_SSH_COMMAND"] = ssh_command

    try:
        return await _do_sync(
            repo=repo,
            branch=branch,
            upstream_remote=upstream_remote,
            upstream_url=upstream_url,
            push_remote=push_remote,
            auto_push=auto_push,
            git_env=git_env,
        )
    finally:
        if stashed:
            code, _, err = await _run_git(repo, "stash", "pop")
            if code != 0:
                logger.warning("Repo sync: stash pop failed after sync: {}", err)


async def _do_sync(
    *,
    repo: Path,
    branch: str,
    upstream_remote: str,
    upstream_url: str,
    push_remote: str,
    auto_push: bool,
    git_env: dict,
) -> str:
    """Core sync logic, assumes clean worktree."""

    # Ensure upstream remote
    code, existing_url, _ = await _run_git(repo, "remote", "get-url", upstream_remote)
    if code != 0:
        code, _, err = await _run_git(repo, "remote", "add", upstream_remote, upstream_url)
        if code != 0:
            return f"Repo sync failed: cannot add upstream remote: {err or 'unknown error'}"
    elif existing_url.strip() != upstream_url:
        code, _, err = await _run_git(repo, "remote", "set-url", upstream_remote, upstream_url)
        if code != 0:
            return f"Repo sync failed: cannot set upstream remote URL: {err or 'unknown error'}"

    # Fetch upstream (may need SSH for private repos)
    code, _, err = await _run_git(repo, "fetch", upstream_remote, env=git_env)
    if code != 0:
        return f"Repo sync failed: fetch upstream failed: {err or 'unknown error'}"

    # Compare branches
    code, counts, err = await _run_git(
        repo, "rev-list", "--left-right", "--count", f"{branch}...{upstream_remote}/{branch}"
    )
    if code != 0:
        return f"Repo sync failed: cannot compare branches: {err or 'unknown error'}"

    left_ahead, right_ahead = [int(x) for x in counts.split()]

    # Already up to date
    if right_ahead == 0:
        return "Repo sync: already up to date."

    # Local has no extra commits → simple fast-forward
    if left_ahead == 0:
        code, _, err = await _run_git(repo, "merge", "--ff-only", f"{upstream_remote}/{branch}")
        if code != 0:
            return f"Repo sync failed: fast-forward merge failed: {err or 'unknown error'}"
        result_msg = f"fast-forwarded {right_ahead} commit(s)"
    else:
        # Local has own commits → rebase onto upstream
        code, _, err = await _run_git(repo, "rebase", f"{upstream_remote}/{branch}")
        if code != 0:
            # Collect conflict details before aborting
            conflict_report = await _collect_conflict_info(repo, branch, upstream_remote, left_ahead, right_ahead, err)
            await _run_git(repo, "rebase", "--abort")
            return (
                f"Repo sync failed: rebase conflict ({left_ahead} local, {right_ahead} upstream). "
                f"Conflict log saved to {conflict_report}. Manual resolution needed."
            )
        result_msg = f"rebased {left_ahead} local commit(s) onto {right_ahead} new upstream commit(s)"

    if not auto_push:
        return f"Repo sync completed: {result_msg} locally."

    # Push with SSH command support
    push_args = ["push", push_remote, branch]
    if left_ahead > 0:
        # After rebase, force-push is needed for the fork
        push_args = ["push", "--force-with-lease", push_remote, branch]

    code, _, err = await _run_git(repo, *push_args, env=git_env)
    if code != 0:
        return (
            f"Repo sync partially completed: {result_msg} locally, but push failed: "
            f"{err or 'unknown error'}"
        )

    return f"Repo sync completed: {result_msg} and pushed to {push_remote}/{branch}."


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
        ssh_command: str = "",
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
        self.ssh_command = ssh_command
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

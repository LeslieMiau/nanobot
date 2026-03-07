"""Deterministic git fork sync service."""

import asyncio
from pathlib import Path


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

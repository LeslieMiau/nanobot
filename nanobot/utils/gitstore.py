"""Git-backed version control for memory files."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class CommitInfo:
    sha: str  # Short SHA (8 chars)
    message: str
    timestamp: str  # Formatted datetime

    def format(self, diff: str = "") -> str:
        """Format this commit for display, optionally with a diff."""
        header = f"## {self.message.splitlines()[0]}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"


class GitStore:
    """Git-backed version control for memory files."""

    _AUTHOR_NAME = "nanobot"
    _AUTHOR_EMAIL = "nanobot@dream"

    def __init__(self, workspace: Path, tracked_files: list[str]):
        self._workspace = workspace
        self._tracked_files = tracked_files

    def is_initialized(self) -> bool:
        """Check if the git repo has been initialized."""
        return (self._workspace / ".git").is_dir()

    # -- init ------------------------------------------------------------------

    def init(self) -> bool:
        """Initialize a git repo if not already initialized.

        Creates .gitignore and makes an initial commit.
        Returns True if a new repo was created, False if already exists.
        """
        if self.is_initialized():
            return False

        try:
            self._run_git("init")

            gitignore = self._workspace / ".gitignore"
            gitignore.write_text(self._build_gitignore(), encoding="utf-8")

            for rel in self._tracked_files:
                p = self._workspace / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")

            self._run_git("add", "--", ".gitignore", *self._tracked_files)
            self._commit_tracked("init: nanobot memory store")
            logger.info("Git store initialized at {}", self._workspace)
            return True
        except Exception:
            logger.warning("Git store init failed for {}", self._workspace)
            return False

    # -- daily operations ------------------------------------------------------

    def auto_commit(self, message: str) -> str | None:
        """Stage tracked memory files and commit if there are changes.

        Returns the short commit SHA, or None if nothing to commit.
        """
        if not self.is_initialized():
            return None

        try:
            if not self._has_tracked_changes():
                return None

            self._run_git("add", "--", *self._tracked_files)
            self._commit_tracked(message)
            sha = self._current_short_sha()
            logger.debug("Git auto-commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.warning("Git auto-commit failed: {}", message)
            return None

    # -- internal helpers ------------------------------------------------------

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """Resolve a short SHA prefix to the full SHA bytes."""
        try:
            result = self._run_git("rev-parse", f"{short_sha}^{{commit}}")
            resolved = result.stdout.strip()
            return bytes.fromhex(resolved) if resolved else None
        except Exception:
            return None

    def _build_gitignore(self) -> str:
        """Generate .gitignore content from tracked files."""
        dirs: set[str] = set()
        for f in self._tracked_files:
            parent = str(Path(f).parent)
            if parent != ".":
                dirs.add(parent)
        lines = ["/*"]
        for d in sorted(dirs):
            lines.append(f"!{d}/")
        for f in self._tracked_files:
            lines.append(f"!{f}")
        lines.append("!.gitignore")
        return "\n".join(lines) + "\n"

    # -- query -----------------------------------------------------------------

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        """Return simplified commit log."""
        if not self.is_initialized():
            return []

        try:
            entries: list[CommitInfo] = []
            result = self._run_git(
                "log",
                f"-n{max_entries}",
                "--date=format:%Y-%m-%d %H:%M",
                "--pretty=format:%H%x1f%s%x1f%ad",
                "--",
                *self._tracked_files,
            )
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                sha, msg, ts = line.split("\x1f")
                entries.append(CommitInfo(
                    sha=sha[:8],
                    message=msg.strip(),
                    timestamp=ts.strip(),
                ))
            return entries
        except Exception:
            logger.warning("Git log failed")
            return []

    def diff_commits(self, sha1: str, sha2: str) -> str:
        """Show diff between two commits."""
        if not self.is_initialized():
            return ""

        try:
            if not self._resolve_sha(sha1) or not self._resolve_sha(sha2):
                return ""
            result = self._run_git(
                "diff",
                sha1,
                sha2,
                "--",
                *self._tracked_files,
            )
            return result.stdout
        except Exception:
            logger.warning("Git diff_commits failed")
            return ""

    def find_commit(self, short_sha: str, max_entries: int = 20) -> CommitInfo | None:
        """Find a commit by short SHA prefix match."""
        for c in self.log(max_entries=max_entries):
            if c.sha.startswith(short_sha):
                return c
        return None

    def show_commit_diff(self, short_sha: str, max_entries: int = 20) -> tuple[CommitInfo, str] | None:
        """Find a commit and return it with its diff vs the parent."""
        commits = self.log(max_entries=max_entries)
        for i, c in enumerate(commits):
            if c.sha.startswith(short_sha):
                if i + 1 < len(commits):
                    diff = self.diff_commits(commits[i + 1].sha, c.sha)
                else:
                    diff = ""
                return c, diff
        return None

    # -- restore ---------------------------------------------------------------

    def revert(self, commit: str) -> str | None:
        """Revert (undo) the changes introduced by the given commit.

        Restores all tracked memory files to the state at the commit's parent,
        then creates a new commit recording the revert.

        Returns the new commit SHA, or None on failure.
        """
        if not self.is_initialized():
            return None

        try:
            if not self._resolve_sha(commit):
                logger.warning("Git revert: SHA not found: {}", commit)
                return None
            parent = self._parent_of(commit)
            if not parent:
                logger.warning("Git revert: cannot revert root commit {}", commit)
                return None

            restored = False
            for filepath in self._tracked_files:
                content = self._show_file_at_commit(parent, filepath)
                dest = self._workspace / filepath
                dest.parent.mkdir(parents=True, exist_ok=True)
                if content is None:
                    if dest.exists():
                        dest.unlink()
                        restored = True
                    continue
                dest.write_text(content, encoding="utf-8")
                restored = True

            if not restored:
                return None

            return self.auto_commit(f"revert: undo {commit}")
        except Exception:
            logger.warning("Git revert failed for {}", commit)
            return None

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._workspace,
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit_tracked(self, message: str) -> None:
        self._run_git(
            "-c",
            f"user.name={self._AUTHOR_NAME}",
            "-c",
            f"user.email={self._AUTHOR_EMAIL}",
            "commit",
            "--author",
            f"{self._AUTHOR_NAME} <{self._AUTHOR_EMAIL}>",
            "-m",
            message,
        )

    def _current_short_sha(self) -> str:
        result = self._run_git("rev-parse", "--short=8", "HEAD")
        return result.stdout.strip()

    def _has_tracked_changes(self) -> bool:
        result = self._run_git("status", "--porcelain", "--", *self._tracked_files)
        return bool(result.stdout.strip())

    def _parent_of(self, short_sha: str) -> str | None:
        result = self._run_git("rev-list", "--parents", "-n", "1", short_sha)
        parts = result.stdout.strip().split()
        if len(parts) < 2:
            return None
        return parts[1]

    def _show_file_at_commit(self, commit: str, filepath: str) -> str | None:
        try:
            result = self._run_git("show", f"{commit}:{filepath}")
            return result.stdout
        except Exception:
            return None

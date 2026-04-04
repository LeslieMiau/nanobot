#!/usr/bin/env python3
"""Run a disposable real-world coding-task smoke test with tmux and Codex."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
    and os.environ.get("NANOBOT_SMOKE_REEXEC") != "1"
):
    env = os.environ.copy()
    env["NANOBOT_SMOKE_REEXEC"] = "1"
    os.execve(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
        env,
    )

from nanobot.coding_tasks.reporting import build_completion_report
from nanobot.coding_tasks.runtime import build_coding_task_runtime


def _say(message: str) -> None:
    print(message, flush=True)


def _resolve_codex_bin() -> str | None:
    if resolved := shutil.which("codex"):
        return resolved
    app_path = Path("/Applications/Codex.app/Contents/Resources/codex")
    if app_path.exists():
        return str(app_path)
    return None


def _write_smoke_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Disposable Coding Task Smoke Repo\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        textwrap.dedent(
            """
            # Smoke Repo Instructions

            - Read `PROGRESS.md`, `PLAN.json`, and run `./init.sh` before editing.
            - Complete the single remaining PLAN item without changing any `description` or `steps`.
            - Create `SMOKE_DONE.txt` with the exact content `smoke ok`.
            - Append `- wrapped everything up` to `PROGRESS.md`.
            - Set the remaining PLAN item `passes` field to `true`.
            - Do not run `git commit` in this smoke repo; the goal is to finish the harness state, not to validate git metadata writes.
            - Stop after the repo harness is fully complete.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "PLAN.json").write_text(
        '[{"id": 1, "description": "seed smoke repo", "steps": ["already done"], "passes": true}, '
        '{"id": 2, "description": "finish disposable smoke task", "steps": ["create SMOKE_DONE.txt", "mark plan passed"], "passes": false}]',
        encoding="utf-8",
    )
    (repo / "PROGRESS.md").write_text(
        "## Session update\n- Finish the disposable smoke task\n",
        encoding="utf-8",
    )
    (repo / "init.sh").write_text(
        "#!/usr/bin/env bash\ncd \"$(dirname \"$0\")\"\n[ -f README.md ] || echo \"missing README.md\"\nexit 0\n",
        encoding="utf-8",
    )
    (repo / "init.sh").chmod(0o755)

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "smoke@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed smoke repo"], cwd=repo, check=True, capture_output=True)


async def _run_smoke(timeout_s: int, poll_s: float) -> int:
    temp_root = "/tmp" if Path("/tmp").exists() else None
    with tempfile.TemporaryDirectory(prefix="nanobot-coding-smoke-", dir=temp_root) as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        repo = root / "repo"
        _write_smoke_repo(repo)

        runtime = build_coding_task_runtime(workspace)
        task = runtime.manager.create_task(
            repo_path=str(repo),
            goal=(
                "Complete the disposable harness smoke repo exactly as described by AGENTS.md and PLAN.json, "
                "without making a git commit, then stop when the harness is complete."
            ),
        )
        try:
            launched = runtime.launcher.launch_task(task.id)
        except subprocess.CalledProcessError as exc:
            _say(f"[smoke] failed to launch tmux worker: {exc}")
            if exc.stderr:
                _say(exc.stderr)
            return 1
        _say(f"[smoke] launched task={task.id} tmux={launched.task.tmux_session} reused={launched.session_reused}")
        _say(f"[smoke] prompt={launched.prompt_path}")
        _say(f"[smoke] log={launched.log_path}")

        artifact_dir = workspace / "automation" / "coding" / "artifacts"
        prompt_path = artifact_dir / f"{task.id}.prompt.txt"
        launch_path = artifact_dir / f"{task.id}.launch.sh"
        log_path = artifact_dir / f"{task.id}.codex.log"

        deadline = time.monotonic() + timeout_s
        last_status = ""
        while time.monotonic() < deadline:
            report = await runtime.monitor.poll_task(task.id)
            current = runtime.store.get_task(task.id)
            if current is None:
                _say("[smoke] task disappeared from store")
                return 1
            if current.status != last_status:
                _say(f"[smoke] status={current.status} summary={current.last_progress_summary or report.summary}")
                last_status = current.status
            if current.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(poll_s)

        current = runtime.store.get_task(task.id)
        if current is None:
            _say("[smoke] task missing after polling")
            return 1

        _say(f"[smoke] final status={current.status}")
        _say(f"[smoke] final progress={current.last_progress_summary or '-'}")

        visible_ids = {item.id for item in runtime.policy.visible_tasks()}
        all_ids = {item.id for item in runtime.policy.visible_tasks(include_terminal=True)}
        artifact_paths = [prompt_path, launch_path, log_path]
        artifact_exists = [path.name for path in artifact_paths if path.exists()]

        if current.status != "completed":
            if log_path.exists():
                _say("[smoke] recent worker log:")
                _say(log_path.read_text(encoding="utf-8")[-4000:])
            return 1
        if task.id in visible_ids:
            _say("[smoke] completed task is still visible in the default task view")
            return 1
        if task.id not in all_ids:
            _say("[smoke] completed task is missing from task history")
            return 1
        if artifact_exists:
            _say(f"[smoke] expected task artifacts to be removed, but found: {artifact_exists}")
            return 1

        _say("[smoke] completion report:")
        _say(build_completion_report(current))
        _say("[smoke] PASS")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=240, help="Maximum seconds to wait for the smoke task")
    parser.add_argument("--poll", type=float, default=5.0, help="Polling interval in seconds")
    args = parser.parse_args()

    if shutil.which("tmux") is None:
        _say("tmux is required for the real smoke test.")
        return 2
    if _resolve_codex_bin() is None:
        _say("Codex CLI is required for the real smoke test.")
        return 2

    try:
        return asyncio.run(_run_smoke(args.timeout, args.poll))
    except KeyboardInterrupt:
        _say("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.bus.events import OutboundMessage
from nanobot.cli.commands import app
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.notifier import CodingTaskNotifier
from nanobot.coding_tasks.runtime import build_coding_task_runtime
from nanobot.coding_tasks.store import CodingTaskStore
from nanobot.coding_tasks.worker import CodexWorkerLauncher
from nanobot.config.schema import Config


class _MutableTmuxRunner:
    def __init__(self) -> None:
        self.has_session = False
        self.capture_output = ""
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if "has-session" in cmd:
            return subprocess.CompletedProcess(cmd, 0 if self.has_session else 1, "", "")
        if "capture-pane" in cmd:
            return subprocess.CompletedProcess(cmd, 0, self.capture_output, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed smoke repo"], cwd=repo, check=True, capture_output=True)


def _init_disposable_harness_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "README.md").write_text("# Smoke Repo\n", encoding="utf-8")
    (repo / "PLAN.json").write_text(
        '[{"id": 1, "description": "seed", "steps": ["done"], "passes": true}, '
        '{"id": 2, "description": "finish harness smoke", "steps": ["mark done"], "passes": false}]',
        encoding="utf-8",
    )
    (repo / "PROGRESS.md").write_text(
        "## Session update\n- Finish the remaining harness smoke task\n",
        encoding="utf-8",
    )
    (repo / "init.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _init_git_repo(repo)


async def _collect(sent: list[OutboundMessage], msg: OutboundMessage) -> None:
    sent.append(msg)


@pytest.mark.asyncio
async def test_cli_coding_task_e2e_completes_harness_and_hides_archived_task(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    workspace = tmp_path / "workspace"
    repo = tmp_path / "disposable-repo"
    _init_disposable_harness_repo(repo)

    config = Config()
    config.agents.defaults.workspace = str(workspace)

    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    runner = _MutableTmuxRunner()
    launcher = CodexWorkerLauncher(workspace, manager, runner=runner)
    runtime = build_coding_task_runtime(workspace, store=store, manager=manager, launcher=launcher)
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _collect(sent, msg), throttle_s=0)

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands._load_coding_task_runtime", lambda _config, send_callback=None: runtime)

    cli = CliRunner()

    create_result = cli.invoke(
        app,
        ["coding-task", "create", str(repo), "--goal", "Finish the disposable harness smoke repo", "--config", str(config_file)],
    )
    assert create_result.exit_code == 0

    tasks = store.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    manager.update_metadata(
        task.id,
        updates={"origin_channel": "telegram", "origin_chat_id": "chat-smoke"},
    )

    run_result = cli.invoke(app, ["coding-task", "run", task.id, "--config", str(config_file)])
    assert run_result.exit_code == 0

    prompt_path = workspace / "automation" / "coding" / "artifacts" / f"{task.id}.prompt.txt"
    launch_path = workspace / "automation" / "coding" / "artifacts" / f"{task.id}.launch.sh"
    log_path = workspace / "automation" / "coding" / "artifacts" / f"{task.id}.codex.log"
    log_path.write_text(
        '{"item":{"type":"agent_message","text":"验证证据已经拿到了，准备收尾。"}}\n',
        encoding="utf-8",
    )
    assert prompt_path.exists() is True
    assert launch_path.exists() is True
    assert log_path.exists() is True

    (repo / "PLAN.json").write_text(
        '[{"id": 1, "description": "seed", "steps": ["done"], "passes": true}, '
        '{"id": 2, "description": "finish harness smoke", "steps": ["mark done"], "passes": true}]',
        encoding="utf-8",
    )
    (repo / "PROGRESS.md").write_text(
        "## Session update\n- wrapped everything up\n",
        encoding="utf-8",
    )

    report = await runtime.monitor.poll_task(task.id)
    await notifier.maybe_notify(task.id, report)

    updated = store.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.last_progress_summary == "wrapped everything up"
    assert prompt_path.exists() is False
    assert launch_path.exists() is False
    assert log_path.exists() is False
    assert sent and "编程任务已完成" in sent[0].content
    assert "wrapped everything up" in sent[0].content

    default_list = cli.invoke(app, ["coding-task", "list", "--config", str(config_file)])
    assert default_list.exit_code == 0
    assert "No visible coding tasks" in _strip_ansi(default_list.stdout)
    assert task.id not in default_list.stdout

    history_list = cli.invoke(app, ["coding-task", "list", "--all", "--config", str(config_file)])
    assert history_list.exit_code == 0
    history_output = _strip_ansi(history_list.stdout)
    assert task.id in history_output
    assert "completed" in history_output

    status_result = cli.invoke(app, ["coding-task", "status", task.id, "--config", str(config_file)])
    assert status_result.exit_code == 0
    status_output = _strip_ansi(status_result.stdout)
    assert "Status: completed" in status_output
    assert "编程任务已完成" in status_output
    assert "wrapped everything up" in status_output

    cleanup_events = [event for event in store.read_run_events(task.id) if event.event == "artifact_cleanup"]
    assert len(cleanup_events) == 1
    assert sorted(cleanup_events[0].payload["removed_files"]) == sorted(
        [prompt_path.name, launch_path.name, log_path.name]
    )

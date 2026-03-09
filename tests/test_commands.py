import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import (
    _build_cron_execution_message,
    _build_heartbeat_execution_message,
    _should_deliver_heartbeat_response,
    app,
)
from nanobot.config.schema import Config
from nanobot.cron.types import CronPayload
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import _strip_model_prefix
from nanobot.providers.registry import find_by_model

runner = CliRunner()


class _StopGateway(RuntimeError):
    pass


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.cli.commands.get_workspace_path") as mock_ws:

        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text("{}")

        yield config_file, workspace_dir

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "nanobot is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "CODING.md").exists()
    assert (workspace_dir / "CONTENT_FACTORY.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert "Created CODING.md" in result.stdout
    assert "Created CONTENT_FACTORY.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "CODING.md").exists()
    assert (workspace_dir / "CONTENT_FACTORY.md").exists()


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_find_by_model_prefers_explicit_prefix_over_generic_codex_keyword():
    spec = find_by_model("github-copilot/gpt-5.3-codex")

    assert spec is not None
    assert spec.name == "github_copilot"


def test_litellm_provider_canonicalizes_github_copilot_hyphen_prefix():
    provider = LiteLLMProvider(default_model="github-copilot/gpt-5.3-codex")

    resolved = provider._resolve_model("github-copilot/gpt-5.3-codex")

    assert resolved == "github_copilot/gpt-5.3-codex"


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_build_heartbeat_execution_message_includes_summary_file_and_noop_rule():
    prompt = _build_heartbeat_execution_message(
        "daily brief might be due",
        "## Active Tasks\n- [ ] check something",
    )

    assert "Phase 1 summary:" in prompt
    assert "daily brief might be due" in prompt
    assert "Full HEARTBEAT.md:" in prompt
    assert "## Active Tasks" in prompt
    assert "Return only the final user-facing content" in prompt
    assert "Do not include execution notes" in prompt
    assert "return exactly NOOP and nothing else" in prompt


def test_build_cron_execution_message_requests_delivery_only_output():
    prompt = _build_cron_execution_message("Daily AI News", "Generate the digest")

    assert "You are executing a scheduled task." in prompt
    assert "Scheduled task name:" in prompt
    assert "Daily AI News" in prompt
    assert "Scheduled instruction:" in prompt
    assert "Generate the digest" in prompt
    assert "Return only the final user-facing content" in prompt
    assert "Do not include execution notes" in prompt


def test_should_deliver_heartbeat_response_filters_noop_and_empty():
    assert _should_deliver_heartbeat_response(None) is False
    assert _should_deliver_heartbeat_response("") is False
    assert _should_deliver_heartbeat_response("  NOOP  ") is False
    assert _should_deliver_heartbeat_response("completed heartbeat task") is True


def test_config_forced_aicodewith_provider_uses_default_gateway_base():
    config = Config()
    config.agents.defaults.provider = "aicodewith"
    config.agents.defaults.model = "gpt-4.1"
    config.providers.aicodewith.api_key = "test-key"

    assert config.get_provider_name() == "aicodewith"
    assert config.get_api_base() == "https://api.aicodewith.com/v1"


def test_litellm_provider_resolves_aicodewith_as_openai_gateway():
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-5",
        provider_name="aicodewith",
    )

    resolved = provider._resolve_model("anthropic/claude-sonnet-4-5")

    assert resolved == "openai/claude-sonnet-4-5"


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """Mock agent command dependencies for focused CLI tests."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")
    cron_dir = tmp_path / "data" / "cron"

    with patch("nanobot.config.loader.load_config", return_value=config) as mock_load_config, \
         patch("nanobot.config.paths.get_cron_dir", return_value=cron_dir), \
         patch("nanobot.cli.commands.sync_workspace_templates") as mock_sync_templates, \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.cli.commands._print_agent_response") as mock_print_response, \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.cron.service.CronService"), \
         patch("nanobot.agent.loop.AgentLoop") as mock_agent_loop_cls:

        agent_loop = MagicMock()
        agent_loop.channels_config = None
        agent_loop.process_direct = AsyncMock(return_value="mock-response")
        agent_loop.close_mcp = AsyncMock(return_value=None)
        mock_agent_loop_cls.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "agent_loop_cls": mock_agent_loop_cls,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    assert "--workspace" in result.stdout
    assert "-w" in result.stdout
    assert "--config" in result.stdout
    assert "-c" in result.stdout


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime):
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (None,)
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == (
        mock_agent_runtime["config"].workspace_path
    )
    mock_agent_runtime["agent_loop"].process_direct.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with("mock-response", render_markdown=True)


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _store: object())

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs) -> str:
            return "ok"

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_overrides_workspace_path(mock_agent_runtime):
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_workspace_override_wins_over_config_workspace(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_gateway_uses_workspace_from_config_by_default(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        lambda path: seen.__setitem__("workspace", path),
    )
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert seen["config_path"] == config_file.resolve()
    assert seen["workspace"] == Path(config.agents.defaults.workspace)


def test_gateway_workspace_option_overrides_config(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    override = tmp_path / "override-workspace"
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        lambda path: seen.__setitem__("workspace", path),
    )
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGateway)
    assert seen["workspace"] == override
    assert config.workspace_path == override


def test_gateway_uses_config_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: object())

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGateway("stop")

    monkeypatch.setattr("nanobot.cron.service.CronService", _StopCron)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert seen["cron_store"] == config_file.parent / "cron" / "jobs.json"


def test_gateway_refuses_start_when_other_gateway_process_exists(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    make_provider_called = False

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(
        "nanobot.cli.commands._find_other_gateway_processes",
        lambda: [(4242, "python -m nanobot gateway --config /tmp/nanobot.json")],
    )

    def _unexpected_make_provider(_config):
        nonlocal make_provider_called
        make_provider_called = True
        return object()

    monkeypatch.setattr("nanobot.cli.commands._make_provider", _unexpected_make_provider)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 1
    assert "Another nanobot gateway instance is already running" in result.stdout
    assert "4242" in result.stdout
    assert make_provider_called is False


def test_gateway_starts_repo_sync_watcher_without_installing_cron_job(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    config.gateway.repo_sync.enabled = True
    config.gateway.repo_sync.repo_path = str(tmp_path)
    config.gateway.repo_sync.watch_interval_s = 15
    seen: dict[str, object] = {
        "cron_add_calls": 0,
        "legacy_repo_jobs_removed": 0,
        "watcher_started": 0,
        "watcher_stopped": 0,
    }

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: object())

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            self._jobs = [
                SimpleNamespace(
                    id="legacy-sync",
                    payload=SimpleNamespace(message="__repo_sync__::/tmp/repo::main"),
                )
            ]

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def list_jobs(self, include_disabled: bool = False) -> list:
            return list(self._jobs)

        def remove_job(self, _job_id: str) -> bool:
            seen["legacy_repo_jobs_removed"] = int(seen["legacy_repo_jobs_removed"]) + 1
            self._jobs = []
            return True

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def add_job(self, *args, **kwargs) -> None:
            seen["cron_add_calls"] = int(seen["cron_add_calls"]) + 1

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.tools: dict = {}
            self.model = "gpt-5"

        async def run(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannels:
        def __init__(self, *_args, **_kwargs) -> None:
            self.enabled_channels: list[str] = []

        async def start_all(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    class _FakeHeartbeat:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeRepoSyncWatcher:
        def __init__(self, **kwargs) -> None:
            seen["watcher_interval"] = kwargs["interval_s"]

        async def start(self) -> None:
            seen["watcher_started"] = int(seen["watcher_started"]) + 1

        def stop(self) -> None:
            seen["watcher_stopped"] = int(seen["watcher_stopped"]) + 1

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannels)
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", _FakeHeartbeat)
    monkeypatch.setattr("nanobot.repo_sync.service.RepoSyncWatcher", _FakeRepoSyncWatcher)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    assert seen["cron_add_calls"] == 0
    assert seen["legacy_repo_jobs_removed"] == 1
    assert seen["watcher_interval"] == 15
    assert seen["watcher_started"] == 1
    assert seen["watcher_stopped"] == 1


def test_gateway_cron_jobs_run_with_silent_progress(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, object] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: object())

    class _FakeBus:
        def __init__(self) -> None:
            self.outbound: list[object] = []

        async def publish_outbound(self, msg) -> None:
            self.outbound.append(msg)

    bus = _FakeBus()
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)

    class _FakeCron:
        last_instance = None

        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            _FakeCron.last_instance = self

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def list_jobs(self, include_disabled: bool = False) -> list:
            return []

        def remove_job(self, _job_id: str) -> bool:
            return False

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.tools = {}
            self.model = "gpt-5"
            self.calls: list[dict[str, object]] = []
            seen["agent"] = self

        async def process_direct(self, *_args, **kwargs) -> str:
            self.calls.append(kwargs)
            return "digest ready"

        async def run(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannels:
        def __init__(self, *_args, **_kwargs) -> None:
            self.enabled_channels: list[str] = []

        async def start_all(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    class _FakeHeartbeat:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannels)
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", _FakeHeartbeat)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    cron = _FakeCron.last_instance
    assert cron is not None
    assert cron.on_job is not None

    job = SimpleNamespace(
        id="job-1",
        name="Daily AI News",
        payload=CronPayload(
            message="Generate the daily AI digest",
            deliver=True,
            channel="telegram",
            to="chat-1",
        ),
    )

    returned = asyncio.run(cron.on_job(job))

    agent = seen["agent"]
    assert returned == "digest ready"
    assert agent.calls
    kwargs = agent.calls[0]
    assert kwargs["session_key"] == "cron:job-1"
    assert kwargs["channel"] == "telegram"
    assert kwargs["chat_id"] == "chat-1"
    assert callable(kwargs["on_progress"])
    assert asyncio.run(kwargs["on_progress"]("hidden progress")) is None
    assert len(bus.outbound) == 1
    assert bus.outbound[0].content == "digest ready"


def test_doctor_outputs_markdown_report(monkeypatch, tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    seen: dict[str, object] = {}

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)

    def _build_report(**kwargs):
        seen["build_report"] = kwargs
        return {
            "paths": {
                "config_path": "/tmp/config.json",
                "workspace": str(config.workspace_path),
                "jobs_path": "/tmp/cron/jobs.json",
                "sessions_dir": str(config.workspace_path / "sessions"),
            },
            "gateway_lock": {"exists": False},
            "cron": {"exists": False, "failing_jobs": []},
            "sessions": {"latest": [], "suspected_failures": []},
            "history": {"exists": False, "recent_entries": []},
            "next_checks": ["check session file"],
        }

    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.build_report", _build_report)
    monkeypatch.setattr(
        "nanobot.debug.runtime_diagnostics.render_markdown",
        lambda report: "# doctor report\n\n- check session file\n",
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "doctor report" in result.stdout
    assert seen["build_report"]["config_path"] is None
    assert seen["build_report"]["workspace"] == config.workspace_path
    assert seen["build_report"]["limit"] == 5
    assert seen["build_report"]["session_key"] is None


def test_doctor_outputs_json_and_respects_overrides(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)

    def _build_report(**kwargs):
        seen["build_report"] = kwargs
        return {"ok": True, "session_key": kwargs["session_key"]}

    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.build_report", _build_report)

    override = tmp_path / "override-workspace"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--config",
            str(config_file),
            "--workspace",
            str(override),
            "--format",
            "json",
            "--limit",
            "7",
            "--session-key",
            "heartbeat",
        ],
    )

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()
    assert seen["build_report"]["config_path"] == config_file.resolve()
    assert seen["build_report"]["workspace"] == override
    assert seen["build_report"]["limit"] == 7
    assert seen["build_report"]["session_key"] == "heartbeat"
    assert json.loads(result.stdout) == {"ok": True, "session_key": "heartbeat"}


def test_gateway_cron_auto_diagnosis_publishes_on_failure(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.cli.commands._find_other_gateway_processes", lambda: [])
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: SimpleNamespace(list_sessions=lambda: []))
    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.build_report", lambda **_kwargs: {"sessions": {"focus_session": None, "suspected_failures": []}, "cron": {"failing_jobs": []}, "next_checks": ["Open the cron session"]})
    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.render_failure_brief", lambda _report, *, title, details: f"{title}\n- {details[0]}\n- {details[1]}\n")

    class _FakeLock:
        def __init__(self, _path: Path) -> None:
            pass

        def acquire(self) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cli.commands._GatewayInstanceLock", _FakeLock)

    class _FakeBus:
        def __init__(self) -> None:
            self.outbound: list[object] = []

        async def publish_outbound(self, msg) -> None:
            self.outbound.append(msg)

    bus = _FakeBus()
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)

    class _FakeCron:
        last_instance = None

        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            self.on_error = None
            _FakeCron.last_instance = self

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def list_jobs(self, include_disabled: bool = False) -> list:
            return []

        def remove_job(self, _job_id: str) -> bool:
            return False

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.tools = {}
            self.model = "gpt-5"

        async def run(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannels:
        def __init__(self, *_args, **_kwargs) -> None:
            self.enabled_channels: list[str] = []

        async def start_all(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    class _FakeHeartbeat:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannels)
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", _FakeHeartbeat)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    cron = _FakeCron.last_instance
    assert cron is not None
    assert cron.on_error is not None

    job = SimpleNamespace(
        id="job-1",
        name="Daily AI News",
        payload=CronPayload(
            message="Generate the daily AI digest",
            deliver=True,
            channel="telegram",
            to="chat-1",
        ),
    )

    asyncio.run(cron.on_error(job, RuntimeError("boom")))

    assert len(bus.outbound) == 1
    assert bus.outbound[0].channel == "telegram"
    assert bus.outbound[0].chat_id == "chat-1"
    assert "nanobot auto-diagnosis: cron failure" in bus.outbound[0].content
    assert "Daily AI News" in bus.outbound[0].content


def test_gateway_heartbeat_auto_diagnosis_publishes_on_failure(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.cli.commands._find_other_gateway_processes", lambda: [])
    monkeypatch.setattr(
        "nanobot.session.manager.SessionManager",
        lambda _workspace: SimpleNamespace(
            list_sessions=lambda: [{"key": "telegram:chat-1", "updated_at": "2026-03-09T12:00:00+08:00"}]
        ),
    )
    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.build_report", lambda **_kwargs: {"sessions": {"focus_session": {"key": "heartbeat"}, "suspected_failures": []}, "cron": {"failing_jobs": []}, "next_checks": ["Open heartbeat session"]})
    monkeypatch.setattr("nanobot.debug.runtime_diagnostics.render_failure_brief", lambda _report, *, title, details: f"{title}\n- {details[0]}\n- {details[1]}\n")

    class _FakeLock:
        def __init__(self, _path: Path) -> None:
            pass

        def acquire(self) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cli.commands._GatewayInstanceLock", _FakeLock)

    class _FakeBus:
        def __init__(self) -> None:
            self.outbound: list[object] = []

        async def publish_outbound(self, msg) -> None:
            self.outbound.append(msg)

    bus = _FakeBus()
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            self.on_error = None

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def list_jobs(self, include_disabled: bool = False) -> list:
            return []

        def remove_job(self, _job_id: str) -> bool:
            return False

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.tools = {}
            self.model = "gpt-5"

        async def run(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannels:
        def __init__(self, *_args, **_kwargs) -> None:
            self.enabled_channels: list[str] = ["telegram"]

        async def start_all(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    class _FakeHeartbeat:
        last_instance = None

        def __init__(self, *args, **kwargs) -> None:
            self.on_error = kwargs.get("on_error")
            _FakeHeartbeat.last_instance = self

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannels)
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", _FakeHeartbeat)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 0
    heartbeat = _FakeHeartbeat.last_instance
    assert heartbeat is not None
    assert heartbeat.on_error is not None

    asyncio.run(heartbeat.on_error("execution", RuntimeError("boom")))

    assert len(bus.outbound) == 1
    assert bus.outbound[0].channel == "telegram"
    assert bus.outbound[0].chat_id == "chat-1"
    assert "nanobot auto-diagnosis: heartbeat failure" in bus.outbound[0].content
    assert "Phase: `execution`" in bus.outbound[0].content

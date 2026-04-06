"""Runtime bootstrap helpers shared by CLI commands and app runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from rich.console import Console

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider
from nanobot.providers.catalog import AvailableModel, build_available_models
from nanobot.providers.factory import ProviderConfigError, build_runtime_provider, create_provider

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager


@dataclass(frozen=True)
class AgentRuntime:
    """Bundled runtime objects used by CLI entrypoints and services."""

    bus: MessageBus
    provider: LLMProvider
    default_provider_name: str | None
    cron: CronService
    agent: AgentLoop


def load_runtime_config(
    config: str | None = None,
    workspace: str | None = None,
    *,
    console: Console | None = None,
) -> Config:
    """Load config and optionally override the active workspace."""
    from nanobot.config.loader import load_config, set_config_path

    console = console or Console()
    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise SystemExit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def make_provider(config: Config, *, console: Console | None = None) -> LLMProvider:
    """Create the appropriate LLM provider from config."""
    console = console or Console()
    try:
        return create_provider(config, model=config.agents.defaults.model)
    except ProviderConfigError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        console.print("Set the matching provider in ~/.nanobot/config.json under `providers`.")
        raise SystemExit(1) from exc


def build_provider_switcher(
    config: Config,
) -> tuple[
    str | None,
    Callable[[str | None, str | None], tuple[LLMProvider, str, str | None]],
    Callable[[str | None, str | None], list[AvailableModel]],
]:
    """Build provider/model callbacks for runtime model switching."""
    default_provider_name = config.get_provider_name(config.agents.defaults.model)

    def provider_switcher(
        requested_model: str | None,
        requested_provider_name: str | None = None,
    ) -> tuple[LLMProvider, str, str | None]:
        if requested_provider_name:
            model = requested_model or config.agents.defaults.model
            runtime_provider = create_provider(
                config,
                model=model,
                provider_name=requested_provider_name,
            )
            return runtime_provider, model, requested_provider_name
        runtime_provider, selection = build_runtime_provider(
            config,
            requested_model,
            default_model=config.agents.defaults.model,
            default_provider_name=default_provider_name,
        )
        return runtime_provider, selection.model, selection.provider_name

    def available_models_provider(
        current_model: str | None,
        current_provider: str | None,
    ) -> list[AvailableModel]:
        return build_available_models(
            config,
            default_model=config.agents.defaults.model,
            default_provider_name=default_provider_name,
            current_model=current_model,
            current_provider_name=current_provider,
            coding_config=config.agents.defaults.coding,
        )

    return default_provider_name, provider_switcher, available_models_provider


def build_agent_runtime(
    config: Config,
    *,
    provider_factory: Callable[[Config], LLMProvider] | None = None,
    bus: MessageBus | None = None,
    cron_service: CronService | None = None,
    cron_store_path: Path | None = None,
    session_manager: SessionManager | None = None,
    restart_callback: Callable[[], Any] | None = None,
    error_callback: Callable[[Any, Exception], Any] | None = None,
) -> AgentRuntime:
    """Build the shared runtime objects needed to run an AgentLoop."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    runtime_bus = bus or MessageBus()
    provider = provider_factory(config) if provider_factory else make_provider(config)
    default_provider_name, provider_switcher, available_models_provider = build_provider_switcher(config)

    if cron_service is None:
        store_path = cron_store_path or (get_cron_dir() / "jobs.json")
        cron_service = CronService(store_path)

    agent = AgentLoop(
        bus=runtime_bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.general_model or config.agents.defaults.model,
        automation_model=config.agents.defaults.automation_model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        response_verbosity=config.agents.defaults.response_verbosity,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        brave_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        image_config=config.tools.images,
        token_guard_config=config.agents.defaults.token_guard,
        coding_config=config.agents.defaults.coding,
        restart_callback=restart_callback,
        error_callback=error_callback,
        provider_name=default_provider_name,
        provider_switcher=provider_switcher,
        available_models_provider=available_models_provider,
    )
    return AgentRuntime(
        bus=runtime_bus,
        provider=provider,
        default_provider_name=default_provider_name,
        cron=cron_service,
        agent=agent,
    )

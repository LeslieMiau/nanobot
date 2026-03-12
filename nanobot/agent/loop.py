"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.command_router import CommandRouterController
from nanobot.agent.coding.guard import CodingGuardController
from nanobot.agent.coding.routing import CodingRouteCandidate, CodingRouteController
from nanobot.agent.coding.summary import CodingSummaryController, TurnExecutionState
from nanobot.agent.context import ContextBuilder
from nanobot.agent.image_flow import ImageFlowController
from nanobot.agent.turn_executor import TurnExecutorController
from nanobot.agent.tools.image_generate import ImageGenerateTool
from nanobot.agent.memory import MemoryStore
from nanobot.agent.model_selection import ModelSelectionController
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.token_guard import TokenGuardAssessment, TokenGuardController
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.persona.engine import PersonaEngine
from nanobot.providers.base import LLMProvider
from nanobot.providers.catalog import AvailableModel
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import (
        ChannelsConfig,
        CodingConfig,
        ExecToolConfig,
        ImageGenerationConfig,
        PersonaConfig,
        TokenGuardConfig,
    )
    from nanobot.cron.service import CronService

class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500
    _COMMAND_ALIASES: dict[str, set[str]] = {
        "/start": {"/start", "start", "开始", "启动"},
        "/new": {"/new", "new", "新会话", "新建会话", "重新开始", "重开"},
        "/help": {"/help", "help", "帮助", "命令"},
        "/stop": {"/stop", "stop", "停止", "停下", "停止任务"},
        "/restart": {"/restart", "restart", "重启", "重新启动"},
        "/retry-cron": {"/retry-cron", "retry-cron", "cron-retry"},
        "/model": {"/model", "model", "模型", "切换模型"},
        "/coding": {"/coding", "coding", "代码模式", "编码模式"},
        "/image-confirm": {"/image-confirm", "image-confirm", "确认图片", "确认生图"},
        "/image-edit": {"/image-edit", "image-edit", "修改图片", "修改提示词"},
        "/image-skip": {"/image-skip", "image-skip", "跳过图片", "跳过生图"},
    }
    _TOKEN_GUARD_EXIT_ALIASES = {"exit", "quit", "/exit", "/quit", ":q", "退出", "退出吧", "结束"}
    _SHINCHAN_WELCOME = "哟～你来啦！我是 nanobot 小新版，今天也一起把事情搞定吧～"
    _CODING_SESSION_MODES = {"auto", "on", "off"}
    _CODING_KEYWORDS = (
        "code", "coding", "implement", "implementation", "fix", "bug", "debug", "refactor",
        "test", "tests", "compile", "build", "error", "stack trace", "exception",
        "script", "cli", "tool", "tools", "automation", "workflow", "cron", "heartbeat",
        "代码", "编码", "实现", "修复", "报错", "错误", "测试", "重构", "编译", "构建",
        "脚本", "小工具", "工具", "自动化", "工作流", "定时任务",
    )
    _LARGE_CHANGE_KEYWORDS = (
        "refactor", "rewrite", "redesign", "overhaul", "migration", "migrate", "architecture",
        "feature", "multi-file", "across files", "rename", "restructure", "scaffold",
        "重构", "重写", "重做", "迁移", "架构", "改造", "大改", "多文件", "跨文件", "整个", "全部",
    )
    _REPO_KEYWORDS = (
        "repo", "repository", "workspace", "project", "git", "commit", "branch", "pr",
        "仓库", "工程", "项目", "分支", "提交", "文件", "目录", "路径",
    )
    _REPO_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile")
    _SHELL_COMMAND_PREFIXES = (
        "git ", "pytest", "npm ", "pnpm ", "yarn ", "uv ", "python ", "pip ",
        "cargo ", "go ", "make", "cmake", "docker ", "kubectl ", "mvn ", "gradle ", "bun ",
    )
    _CODING_SIDE_EFFECT_TOOLS = {"write_file", "edit_file", "exec", "spawn", "message", "cron"}
    _MODEL_SELECTION_KEY = "model_selection"
    _TOKEN_GUARD_STATE_KEY = "token_guard"
    _OPERATOR_ACTION_KEY = "operator_action"
    _PLAN_CONFIRM_COMMAND = "/confirm"
    _PLAN_CANCEL_COMMAND = "/cancel"
    _TOKEN_GUARD_MODES = {"off", "on", "strict", "relaxed"}
    _TOKEN_GUARD_PROCEED_ALIASES = {
        "继续", "继续吧", "批准", "ok", "okay", "proceed", "continue", "/confirm", "confirm", "yes", "y", "好", "确认",
    }
    _TOKEN_GUARD_CANCEL_ALIASES = {
        "/cancel", "cancel", "取消", "算了", "不用了", "stop", "no", "n",
    }

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        automation_model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        response_verbosity: str = "low",
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        image_config: ImageGenerationConfig | None = None,
        persona_config: PersonaConfig | None = None,
        token_guard_config: TokenGuardConfig | None = None,
        coding_config: CodingConfig | None = None,
        restart_callback: Callable[[], Awaitable[None]] | None = None,
        error_callback: Callable[[InboundMessage, Exception], Awaitable[None]] | None = None,
        provider_name: str | None = None,
        provider_switcher: Callable[[str | None, str | None], tuple[LLMProvider, str, str | None]] | None = None,
        available_models_provider: Callable[[str | None, str | None], list[AvailableModel]] | None = None,
    ):
        from nanobot.config.schema import CodingConfig, ExecToolConfig, TokenGuardConfig
        self.bus = bus
        self.channels_config = channels_config
        self.image_config = image_config
        self.provider = provider
        self.provider_name = provider_name
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.automation_model = automation_model or self.model
        self._default_model = self.model
        self._default_provider = provider
        self._default_provider_name = provider_name
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.response_verbosity = response_verbosity
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.token_guard = token_guard_config or TokenGuardConfig()
        self.coding_config = coding_config or CodingConfig()
        self.persona = PersonaEngine(persona_config)
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self._restart_callback = restart_callback
        self._error_callback = error_callback
        self._provider_switcher = provider_switcher
        self._available_models_provider = available_models_provider

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_verbosity=self.response_verbosity,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            coding_config=self.coding_config,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._plan_guard_pending: dict[str, str] = {}  # session_key -> pending large coding request
        self._coding_model_cooldowns: dict[str, float] = {}
        self._last_coding_route_resolved: list[str] = []
        self._last_coding_route_skipped: list[str] = []
        self._last_dispatch_error_signatures: dict[str, str] = {}
        self._processing_lock = asyncio.Lock()
        self._command_router = CommandRouterController(self)
        self._coding_guard = CodingGuardController(self)
        self._coding_route = CodingRouteController(self)
        self._coding_summary = CodingSummaryController(self)
        self._image_flow = ImageFlowController(self)
        self._model_selection = ModelSelectionController(self)
        self._token_guard_controller = TokenGuardController(self)
        self._turn_executor = TurnExecutorController(self)
        self._register_default_tools()

    def _coding_summary_controller(self) -> CodingSummaryController:
        controller = getattr(self, "_coding_summary", None)
        if controller is None:
            controller = CodingSummaryController(self)
            self._coding_summary = controller
        return controller

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        if self.image_config:
            self.tools.register(
                ImageGenerateTool(
                    workspace=self.workspace,
                    config=self.image_config,
                    stage_callback=self._image_flow.stage_request,
                )
            )
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        *,
        coding_enabled: bool = False,
        session_key: str | None = None,
    ) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron", "image_generate"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    if name == "message":
                        tool.set_context(channel, chat_id, message_id)
                    elif name == "spawn":
                        tool.set_context(
                            channel,
                            chat_id,
                            coding_enabled=coding_enabled,
                            provider=self.provider,
                            model=self.model,
                            session_key=session_key,
                        )
                    elif name == "image_generate":
                        tool.set_context(channel, chat_id)
                    else:
                        tool.set_context(channel, chat_id)

    async def _handle_image_confirm(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        return await self._image_flow.handle_confirm(msg, session)

    def _handle_image_edit(self, msg: InboundMessage, session: Session, feedback: str) -> OutboundMessage:
        return self._image_flow.handle_edit(msg, session, feedback)

    def _handle_image_skip(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        return self._image_flow.handle_skip(msg, session)

    @classmethod
    def _session_coding_mode(cls, session: Session) -> str:
        mode = str(session.metadata.get("coding_mode", "auto")).strip().lower()
        return mode if mode in cls._CODING_SESSION_MODES else "auto"

    def _workspace_has_repo_markers(self) -> bool:
        return self._coding_guard.workspace_has_repo_markers()

    @classmethod
    def _looks_like_shell_command(cls, text: str) -> bool:
        return CodingGuardController.looks_like_shell_command(text, cls._SHELL_COMMAND_PREFIXES)

    @classmethod
    def _looks_like_path_or_code(cls, text: str) -> bool:
        return CodingGuardController.looks_like_path_or_code(text)

    @classmethod
    def _looks_like_coding_request(cls, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in cls._CODING_KEYWORDS):
            return True
        if any(keyword in lowered for keyword in cls._REPO_KEYWORDS):
            return True
        if cls._looks_like_shell_command(text):
            return True
        return cls._looks_like_path_or_code(text)

    def _resolve_coding_mode(self, session: Session, user_text: str) -> tuple[str, bool]:
        return self._coding_guard.resolve_coding_mode(session, user_text)

    @classmethod
    def _looks_like_large_change_request(cls, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in cls._LARGE_CHANGE_KEYWORDS):
            return True
        return bool(re.search(r"\b(?:multiple|many|several)\s+files\b", lowered))

    async def _build_large_change_plan(
        self,
        *,
        history: list[dict[str, Any]],
        msg: InboundMessage,
        coding_enabled: bool,
    ) -> str:
        return await self._coding_guard.build_large_change_plan(
            history=history,
            msg=msg,
            coding_enabled=coding_enabled,
        )

    def _persona_hints_for_turn(
        self,
        user_text: str,
        *,
        coding_enabled: bool,
        system_turn: bool = False,
    ) -> str | None:
        if coding_enabled and self.coding_config.disable_persona:
            return None
        if not self.persona.should_apply(user_text, coding_enabled=coding_enabled, system_turn=system_turn):
            return None
        return self.persona.build_runtime_hints(user_text)

    def _temperature_for_turn(
        self,
        user_text: str,
        *,
        coding_enabled: bool,
        system_turn: bool = False,
    ) -> float:
        if coding_enabled:
            return min(float(self.temperature), 0.1)
        if not self.persona.should_apply(user_text, coding_enabled=coding_enabled, system_turn=system_turn):
            return self.temperature
        return self.persona.recommended_temperature(user_text, self.temperature)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    def _token_guard_state(self, session: Session) -> dict[str, Any]:
        return self._token_guard_controller.state(session)

    def _save_token_guard_state(self, session: Session, state: dict[str, Any]) -> None:
        self._token_guard_controller.save_state(session, state)

    def _clear_token_guard_pending(self, session: Session, *, save: bool) -> None:
        self._token_guard_controller.clear_pending(session, save=save)

    @classmethod
    def _parse_token_guard_control(cls, content: str) -> tuple[str, str | int] | None:
        return TokenGuardController.parse_control(content)

    @classmethod
    def _is_token_guard_proceed_message(cls, content: str) -> bool:
        return content.strip().lower() in cls._TOKEN_GUARD_PROCEED_ALIASES

    @classmethod
    def _is_token_guard_cancel_message(cls, content: str) -> bool:
        return content.strip().lower() in cls._TOKEN_GUARD_CANCEL_ALIASES

    def _assess_token_guard(
        self,
        *,
        session: Session,
        history: list[dict[str, Any]],
        msg: InboundMessage,
        coding_enabled: bool,
        mode: str,
        parsed_cmd: str,
    ) -> TokenGuardAssessment:
        return self._token_guard_controller.assess(
            session=session,
            history=history,
            msg=msg,
            coding_enabled=coding_enabled,
            mode=mode,
            parsed_cmd=parsed_cmd,
        )

    def _token_guard_intercept_message(self, state: dict[str, Any], assessment: TokenGuardAssessment) -> str:
        return self._token_guard_controller.intercept_message(state, assessment)

    def _append_token_guard_estimate(
        self,
        content: str | None,
        assessment: TokenGuardAssessment,
    ) -> str | None:
        return self._token_guard_controller.append_estimate(content, assessment)

    @classmethod
    def _normalize_user_command(cls, content: str) -> str:
        """Normalize a single command token to canonical slash command."""
        cmd = content.strip().lower()
        for canonical, aliases in cls._COMMAND_ALIASES.items():
            if cmd in aliases:
                return canonical
        return cmd

    @classmethod
    def _parse_user_command(cls, content: str) -> tuple[str, str]:
        """Parse input into (normalized command, argument text)."""
        raw = content.strip()
        if not raw:
            return "", ""
        if match := cls._parse_natural_model_switch(raw):
            return "/model", match
        if match := cls._parse_natural_cron_retry(raw):
            return "/retry-cron", match
        first, rest = (raw.split(maxsplit=1) + [""])[:2]
        return cls._normalize_user_command(first), rest.strip()

    @staticmethod
    def _parse_natural_model_switch(content: str) -> str | None:
        return ModelSelectionController.parse_natural_model_switch(content)

    @staticmethod
    def _parse_natural_cron_retry(content: str) -> str | None:
        """Recognize natural-language cron retry requests."""
        patterns = (
            r"^(?:请)?(?:帮我)?(?:重试|重跑|重新运行)(?:一下)?\s*(?:cron|定时任务|任务|job)?\s*`?([a-z0-9_-]{4,})`?$",
            r"^(?:请)?(?:帮我)?(?:把)?(?:cron|定时任务|任务|job)\s*`?([a-z0-9_-]{4,})`?\s*(?:重试|重跑|重新运行)(?:一下)?$",
        )
        for pattern in patterns:
            match = re.match(pattern, content.strip(), flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _apply_model_provider(self, provider: LLMProvider, model: str, provider_name: str | None) -> None:
        self._model_selection.apply_model_provider(provider, model, provider_name)

    def _session_model_selection(self, session: Session) -> tuple[str | None, str | None]:
        return self._model_selection.session_model_selection(session)

    def _persist_session_model_selection(
        self,
        session: Session,
        *,
        model: str,
        provider_name: str | None,
    ) -> None:
        self._model_selection.persist_session_model_selection(
            session,
            model=model,
            provider_name=provider_name,
        )

    def _clear_session_model_selection(self, session: Session) -> None:
        self._model_selection.clear_session_model_selection(session)

    def _operator_action(self, session: Session) -> dict[str, Any] | None:
        raw = session.metadata.get(self._OPERATOR_ACTION_KEY)
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind") or "").strip()
        if not kind:
            return None
        return raw

    def _save_operator_action(self, session: Session, action: dict[str, Any] | None) -> None:
        if action:
            session.metadata[self._OPERATOR_ACTION_KEY] = action
        else:
            session.metadata.pop(self._OPERATOR_ACTION_KEY, None)
        self.sessions.save(session)

    def _cron_retry_execution_message(self, job_name: str, instruction: str) -> str:
        """Build the scheduled-task prompt for operator-confirmed cron retries."""
        return self.context.build_cron_prompt(job_name, instruction)

    async def _run_operator_cron_retry(
        self,
        session: Session,
        msg: InboundMessage,
        action: dict[str, Any],
    ) -> OutboundMessage:
        if not self.cron_service:
            self._save_operator_action(session, None)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Cron retry is not available in this mode.",
            )

        job_id = str(action.get("job_id") or "").strip()
        if not job_id:
            self._save_operator_action(session, None)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Pending cron retry is missing a job ID.",
            )

        jobs = self.cron_service.list_jobs(include_disabled=True)
        job = next((item for item in jobs if item.id == job_id), None)
        if job is None:
            self._save_operator_action(session, None)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Cron job not found: `{job_id}`",
            )

        original_on_job = self.cron_service.on_job
        outputs: list[str] = []

        async def _on_job(run_job) -> str | None:
            async def _silent(*_args, **_kwargs):
                return None

            response = await self.process_system_turn(
                self._cron_retry_execution_message(run_job.name, run_job.payload.message),
                session_key=f"cron:{run_job.id}:manual",
                channel="cli",
                chat_id=f"cron-retry:{run_job.id}",
                on_progress=_silent,
                stateless=True,
                disable_persona=True,
                model=self.automation_model,
            )
            if response:
                outputs.append(response)
            return response

        self.cron_service.on_job = _on_job
        try:
            ran = await self.cron_service.run_job(job_id, force=True)
        finally:
            self.cron_service.on_job = original_on_job

        self._save_operator_action(session, None)

        if not ran:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Failed to retry cron job `{job_id}`.",
            )

        result = outputs[-1] if outputs else f"Retried cron job `{job_id}` successfully."
        prefix = f"Retried cron job `{job_id}` ({job.name or 'unnamed'}):\n\n"
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=prefix + result,
            metadata=msg.metadata or {},
        )

    def _prepare_operator_cron_retry(
        self,
        session: Session,
        msg: InboundMessage,
        job_id: str,
    ) -> OutboundMessage:
        """Validate and stage a cron retry for explicit user confirmation."""
        normalized = job_id.strip()
        if not normalized:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Usage: `/retry-cron <job_id>`",
            )
        if not self.cron_service:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Cron retry is not available in this mode.",
            )
        jobs = self.cron_service.list_jobs(include_disabled=True)
        job = next((item for item in jobs if item.id == normalized), None)
        if job is None:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Cron job not found: `{normalized}`",
            )

        self._save_operator_action(
            session,
            {
                "kind": "cron_retry",
                "job_id": job.id,
                "job_name": job.name,
            },
        )
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                f"Pending cron retry for `{job.id}` ({job.name or 'unnamed'}).\n"
                f"Reply `{self._PLAN_CONFIRM_COMMAND}` or `继续/确认` to run it in this chat, or "
                f"`{self._PLAN_CANCEL_COMMAND}` or `取消` to cancel."
            ),
        )

    def _effective_session_model(self, session: Session) -> tuple[str, str | None]:
        return self._model_selection.effective_session_model(session)

    def _reset_model_provider(self) -> None:
        self._model_selection.reset_model_provider()

    def _switch_model_provider(self, requested_model: str, provider_name: str | None = None) -> None:
        self._model_selection.switch_model_provider(requested_model, provider_name)

    def _restore_session_model_provider(self, session: Session) -> None:
        self._model_selection.restore_session_model_provider(session)

    def _resolve_provider_for_model(
        self,
        requested_model: str | None,
        requested_provider_name: str | None = None,
    ) -> tuple[LLMProvider, str, str | None]:
        """Resolve a runtime provider/model tuple without mutating loop state."""
        target_model = (requested_model or self.model).strip()
        if (
            target_model == self.model
            and (requested_provider_name is None or requested_provider_name == self.provider_name)
        ):
            return self.provider, self.model, self.provider_name
        if self._provider_switcher:
            if requested_provider_name is None:
                return self._provider_switcher(target_model)
            try:
                return self._provider_switcher(target_model, requested_provider_name)
            except TypeError:
                return self._provider_switcher(target_model)
        if requested_provider_name and requested_provider_name != self.provider_name:
            raise ValueError(f"provider switcher is not configured for `{requested_provider_name}`")
        return self.provider, target_model, self.provider_name

    def _available_models_for_session(self, session: Session) -> list[AvailableModel]:
        return self._model_selection.available_models_for_session(session)

    def _format_available_models(self, session: Session) -> str:
        return self._model_selection.format_available_models(session)

    def _resolve_model_selection_argument(self, session: Session, arg: str) -> tuple[str, str | None]:
        return self._model_selection.resolve_model_selection_argument(session, arg)

    def _coding_route_raw_models(self) -> list[str]:
        return self._coding_route.raw_models()

    @staticmethod
    def _normalize_coding_model_name(model_name: str) -> tuple[str | None, str | None]:
        return CodingRouteController.normalize_model_name(model_name)

    def _coding_model_cooldown_remaining(self, normalized_model: str) -> int:
        return self._coding_route.cooldown_remaining(normalized_model)

    def _mark_coding_model_failure(self, normalized_model: str) -> None:
        self._coding_route.mark_failure(normalized_model)

    def _resolve_coding_route_candidates(self) -> tuple[list[CodingRouteCandidate], list[str], list[str]]:
        return self._coding_route.resolve_candidates()

    def _has_tool_side_effects(self, turn_state: TurnExecutionState, tools_used: list[str]) -> bool:
        return self._coding_summary_controller().has_tool_side_effects(turn_state, tools_used)

    def _track_path(self, raw_path: Any) -> str | None:
        return self._coding_summary_controller().track_path(raw_path)

    def _guard_coding_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        return self._coding_summary_controller().guard_tool_call(
            tool_name,
            arguments,
            turn_state,
            coding_enabled=coding_enabled,
        )

    def _record_tool_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        turn_state: TurnExecutionState,
    ) -> None:
        self._coding_summary_controller().record_tool_execution(tool_name, arguments, result, turn_state)

    def _needs_verification_follow_up(
        self,
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> bool:
        return self._coding_summary_controller().needs_verification_follow_up(
            turn_state,
            coding_enabled=coding_enabled,
        )

    @staticmethod
    def _provider_accepts_kwarg(provider: LLMProvider, name: str) -> bool:
        """Return True when the provider.chat signature accepts the keyword."""
        try:
            signature = inspect.signature(provider.chat)
        except (TypeError, ValueError):
            return False
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
            return True
        return name in signature.parameters

    async def _chat_with_provider(
        self,
        provider: LLMProvider,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None,
        response_verbosity: str | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
        }
        if response_verbosity is not None and self._provider_accepts_kwarg(provider, "response_verbosity"):
            kwargs["response_verbosity"] = response_verbosity
        if parallel_tool_calls is not None and self._provider_accepts_kwarg(provider, "parallel_tool_calls"):
            kwargs["parallel_tool_calls"] = parallel_tool_calls
        return await provider.chat(**kwargs)

    @staticmethod
    def _verification_follow_up_message() -> str:
        return CodingSummaryController.verification_follow_up_message()

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        temperature_override: float | None = None,
        *,
        coding_enabled: bool = False,
        provider_override: LLMProvider | None = None,
        model_override: str | None = None,
        response_verbosity_override: str | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> tuple[str | None, list[str], list[dict], TurnExecutionState]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages, turn_state)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        temperature = self.temperature if temperature_override is None else temperature_override
        turn_state = TurnExecutionState()
        route_candidates: list[CodingRouteCandidate] = []
        route_index = 0
        active_provider = provider_override or self.provider
        active_model = model_override or self.model

        if coding_enabled:
            route_candidates, _, _ = self._resolve_coding_route_candidates()
            if route_candidates:
                active_provider = route_candidates[0].provider
                active_model = route_candidates[0].model

        while iteration < self.max_iterations:
            iteration += 1

            response_verbosity = response_verbosity_override or getattr(self, "response_verbosity", "low")
            response = await self._chat_with_provider(
                active_provider,
                messages=messages,
                tools=self.tools.get_definitions(),
                model=active_model,
                temperature=temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
                response_verbosity=response_verbosity,
                parallel_tool_calls=parallel_tool_calls,
            )

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = self._guard_coding_tool_call(
                        tool_call.name,
                        tool_call.arguments,
                        turn_state,
                        coding_enabled=coding_enabled,
                    )
                    if result is None:
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    self._record_tool_execution(tool_call.name, tool_call.arguments, result, turn_state)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    if (
                        coding_enabled
                        and route_candidates
                        and route_index < len(route_candidates) - 1
                        and not self._has_tool_side_effects(turn_state, tools_used)
                    ):
                        failed = route_candidates[route_index]
                        self._mark_coding_model_failure(failed.normalized_model)
                        route_index += 1
                        retry = route_candidates[route_index]
                        active_provider = retry.provider
                        active_model = retry.model
                        logger.warning(
                            "Coding model failed ({}), retrying with {}",
                            failed.normalized_model,
                            retry.normalized_model,
                        )
                        if on_progress:
                            await on_progress(
                                f"[Coding route] `{failed.normalized_model}` failed; retrying with "
                                f"`{retry.normalized_model}`."
                            )
                        continue
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                if self._needs_verification_follow_up(turn_state, coding_enabled=coding_enabled):
                    turn_state.verification_prompted = True
                    messages.append({"role": "user", "content": self._verification_follow_up_message()})
                    continue
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages, turn_state

    def _display_path(self, path_str: str) -> str:
        return self._coding_summary_controller().display_path(path_str)

    def _apply_coding_summary(
        self,
        content: str | None,
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        return self._coding_summary_controller().apply_summary(
            content,
            turn_state,
            coding_enabled=coding_enabled,
        )

    async def _apply_persona_output_controls(
        self,
        content: str | None,
        all_messages: list[dict[str, Any]],
        *,
        coding_enabled: bool = False,
        user_text: str = "",
        system_turn: bool = False,
    ) -> str | None:
        """Apply persona postprocessing (e.g. script normalization) to final text."""
        if not content:
            return content
        if coding_enabled and self.coding_config.disable_persona:
            return content
        if not self.persona.should_apply(user_text, coding_enabled=coding_enabled, system_turn=system_turn):
            return content

        normalized = await self.persona.normalize_output(
            text=content,
            provider=self.provider,
            model=self.model,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )
        if normalized != content:
            for msg in reversed(all_messages):
                if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                    msg["content"] = normalized
                    break
        return normalized

    async def run(self) -> None:
        """Run the agent loop, prioritizing stop/restart over normal message dispatch."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            cmd, _ = self._parse_user_command(msg.content)
            if cmd == "/restart":
                await self._handle_restart(msg)
            elif cmd == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _cancel_session_tasks(self, session_key: str, *, wait: bool) -> int:
        """Cancel active tasks and subagents for a session."""
        tasks = self._active_tasks.pop(session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        if wait:
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        sub_cancelled = await self.subagents.cancel_by_session(session_key)
        return cancelled + sub_cancelled

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        total = await self._cancel_session_tasks(msg.session_key, wait=False)
        await asyncio.sleep(0)
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _handle_restart(self, msg: InboundMessage, *, publish: bool = True) -> OutboundMessage:
        """Handle restart with highest priority and best-effort task cancellation."""
        session = self.sessions.get_or_create(msg.session_key)
        self._clear_token_guard_pending(session, save=True)
        self._plan_guard_pending.pop(msg.session_key, None)
        if not self._restart_callback:
            out = OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Restart is not available in this mode.",
            )
        else:
            await self._cancel_session_tasks(msg.session_key, wait=False)
            await self._restart_callback()
            out = OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"{self._SHINCHAN_WELCOME}\n我先转一圈，马上重启回来喔～",
            )
        if publish:
            await self.bus.publish_outbound(out)
        return out

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                self._last_dispatch_error_signatures.pop(msg.session_key, None)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception as e:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))
                await self._report_dispatch_error(msg, e)

    async def _report_dispatch_error(self, msg: InboundMessage, error: Exception) -> None:
        """Send a best-effort deduplicated error callback for normal message failures."""
        if not self._error_callback:
            return
        signature = f"{type(error).__name__}:{error}"
        previous = self._last_dispatch_error_signatures.get(msg.session_key)
        self._last_dispatch_error_signatures[msg.session_key] = signature
        if signature == previous:
            return
        try:
            await self._error_callback(msg, error)
        except Exception as callback_error:
            logger.warning("Error callback failed for session {}: {}", msg.session_key, callback_error)

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        bypass_token_guard: bool = False,
        bypass_plan_guard: bool = False,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        if msg.channel == "system":
            return await self._turn_executor.execute_system_message(msg)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)
        self._restore_session_model_provider(session)
        routed = await self._command_router.route(
            msg=msg,
            session=session,
            key=key,
            on_progress=on_progress,
            bypass_token_guard=bypass_token_guard,
            bypass_plan_guard=bypass_plan_guard,
        )
        if routed.response is not None:
            return routed.response
        if routed.context is None:
            return None
        return await self._turn_executor.execute_user_turn(
            msg=msg,
            request=routed.context,
            on_progress=on_progress,
            bypass_token_guard=bypass_token_guard,
            bypass_plan_guard=bypass_plan_guard,
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue  # Strip runtime context from multimodal messages
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(
        self,
        session,
        *,
        provider: LLMProvider,
        model: str,
        archive_all: bool = False,
    ) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, provider, model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""

    async def process_system_turn(
        self,
        content: str,
        *,
        session_key: str = "system:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        stateless: bool = True,
        bypass_token_guard: bool = True,
        bypass_plan_guard: bool = True,
        disable_persona: bool = True,
        model: str | None = None,
    ) -> str:
        """Run an internal automation/system turn without the normal user-turn guards."""
        del bypass_token_guard, bypass_plan_guard

        await self._connect_mcp()
        response_verbosity = getattr(self, "response_verbosity", "low")
        requested_model = model
        requested_provider_name: str | None = None

        session: Session | None = None
        history: list[dict[str, Any]] = []
        if not stateless:
            session = self.sessions.get_or_create(session_key)
            history = session.get_history(max_messages=self.memory_window)
            if requested_model is None:
                requested_model, requested_provider_name = self._effective_session_model(session)
        try:
            provider, active_model, _ = self._resolve_provider_for_model(
                requested_model or self.automation_model,
                requested_provider_name,
            )
        except Exception:
            provider, active_model = self.provider, (requested_model or self.model)
        if isinstance(provider, OpenAICodexProvider):
            provider = provider.with_profile(
                default_model=active_model,
                response_verbosity=response_verbosity,
                parallel_tool_calls=False,
            )

        self._set_tool_context(
            channel,
            chat_id,
            None,
            coding_enabled=False,
            session_key=session_key,
        )
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        persona_hints = None if disable_persona else self._persona_hints_for_turn(content, coding_enabled=False)
        messages = self.context.build_messages(
            history=history,
            current_message=content,
            channel=channel,
            chat_id=chat_id,
            persona_runtime_hints=persona_hints,
            coding_mode=False,
        )
        final_content, _, all_msgs, turn_state = await self._run_agent_loop(
            messages,
            on_progress=on_progress,
            temperature_override=self.temperature,
            coding_enabled=False,
            provider_override=provider,
            model_override=active_model,
            response_verbosity_override=response_verbosity,
            parallel_tool_calls=False,
        )
        if not disable_persona:
            final_content = await self._apply_persona_output_controls(
                final_content,
                all_msgs,
                coding_enabled=False,
                user_text=content,
                system_turn=True,
            )
        final_content = self._apply_coding_summary(
            final_content,
            turn_state,
            coding_enabled=False,
        )

        if session is not None:
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)

        return final_content or ""

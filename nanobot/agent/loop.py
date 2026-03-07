"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
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
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, CodingConfig, ExecToolConfig, PersonaConfig, TokenGuardConfig
    from nanobot.cron.service import CronService


@dataclass
class _TurnExecutionState:
    files_read: set[str] = field(default_factory=set)
    files_edited: set[str] = field(default_factory=set)
    commands_run: list[str] = field(default_factory=list)
    edit_generation: int = 0
    verification_generation: int = 0
    verification_prompted: bool = False


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
        "/model": {"/model", "model", "模型", "切换模型"},
        "/coding": {"/coding", "coding", "代码模式", "编码模式"},
    }
    _TOKEN_GUARD_EXIT_ALIASES = {"exit", "quit", "/exit", "/quit", ":q", "退出", "退出吧", "结束"}
    _SHINCHAN_WELCOME = "哟～你来啦！我是 nanobot 小新版，今天也一起把事情搞定吧～"
    _CODING_SESSION_MODES = {"auto", "on", "off"}
    _CODING_KEYWORDS = (
        "code", "coding", "implement", "implementation", "fix", "bug", "debug", "refactor",
        "test", "tests", "compile", "build", "error", "stack trace", "exception",
        "代码", "编码", "实现", "修复", "报错", "错误", "测试", "重构", "编译", "构建",
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

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        persona_config: PersonaConfig | None = None,
        token_guard_config: TokenGuardConfig | None = None,
        coding_config: CodingConfig | None = None,
        restart_callback: Callable[[], Awaitable[None]] | None = None,
        provider_name: str | None = None,
        provider_switcher: Callable[[str | None], tuple[LLMProvider, str, str | None]] | None = None,
    ):
        from nanobot.config.schema import CodingConfig, ExecToolConfig, TokenGuardConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.provider_name = provider_name
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self._default_model = self.model
        self._default_provider = provider
        self._default_provider_name = provider_name
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
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
        self._provider_switcher = provider_switcher

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
        self._token_guard_pending: dict[str, str] = {}  # session_key -> pending user message
        self._plan_guard_pending: dict[str, str] = {}  # session_key -> pending large coding request
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()

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
    ) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    if name == "message":
                        tool.set_context(channel, chat_id, message_id)
                    elif name == "spawn":
                        tool.set_context(channel, chat_id, coding_enabled=coding_enabled)
                    else:
                        tool.set_context(channel, chat_id)

    @classmethod
    def _session_coding_mode(cls, session: Session) -> str:
        mode = str(session.metadata.get("coding_mode", "auto")).strip().lower()
        return mode if mode in cls._CODING_SESSION_MODES else "auto"

    def _workspace_has_repo_markers(self) -> bool:
        return any((self.workspace / marker).exists() for marker in self._REPO_MARKERS)

    @classmethod
    def _looks_like_shell_command(cls, text: str) -> bool:
        lowered = text.strip().lower()
        return any(lowered.startswith(prefix) for prefix in cls._SHELL_COMMAND_PREFIXES)

    @classmethod
    def _looks_like_path_or_code(cls, text: str) -> bool:
        if "```" in text:
            return True
        if re.search(r"(?:^|\s)(?:\./|\.\./|/)?[\w.-]+/[\w./-]+", text):
            return True
        return bool(
            re.search(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|json|toml|ya?ml|md|rs|go|java|c|cc|cpp|h)\b", text)
        )

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
        setting = self._session_coding_mode(session)
        if not self.coding_config.enabled:
            return setting, False
        if setting == "on":
            return setting, True
        if setting == "off":
            return setting, False
        if not self.coding_config.auto_detect:
            return setting, False
        if self._looks_like_coding_request(user_text):
            return setting, True
        return setting, self._workspace_has_repo_markers() and any(
            token in user_text.lower() for token in ("help me", "帮我", "请你", "how do i", "怎么", "如何")
        )

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
        planning_request = (
            f"{msg.content}\n\n"
            "[Planning guard] This looks like a larger coding change. "
            "Before making edits, provide a short implementation plan only. "
            "Do not call tools, do not claim work is done, and keep it concise."
        )
        messages = self.context.build_messages(
            history=history,
            current_message=planning_request,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            persona_runtime_hints=self._persona_hints_for_turn(msg.content, coding_enabled=coding_enabled),
            coding_mode=coding_enabled,
        )
        response = await self.provider.chat(
            messages=messages,
            tools=None,
            model=self.model,
            temperature=min(self._temperature_for_turn(msg.content, coding_enabled=coding_enabled), 0.1),
            max_tokens=min(self.max_tokens, 1024),
            reasoning_effort=self.reasoning_effort,
        )
        plan = self._strip_think(response.content) or (
            "Planned steps:\n1. Inspect the relevant files and tests.\n"
            "2. Implement the change with minimal edits.\n"
            "3. Run the narrowest verification and report any remaining risk."
        )
        return (
            f"{plan}\n\n"
            f"Reply `{self.token_guard.confirm_command}` to execute this larger change, "
            f"or `{self.token_guard.cancel_command}` to cancel."
        )

    def _persona_hints_for_turn(self, user_text: str, *, coding_enabled: bool) -> str | None:
        if coding_enabled and self.coding_config.disable_persona:
            return None
        return self.persona.build_runtime_hints(user_text)

    def _temperature_for_turn(self, user_text: str, *, coding_enabled: bool) -> float:
        if coding_enabled:
            return min(float(self.temperature), 0.1)
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

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Estimate token usage from message payload size."""
        total_chars = 0

        def walk(v: Any) -> None:
            nonlocal total_chars
            if isinstance(v, str):
                total_chars += len(v)
                return
            if isinstance(v, dict):
                for vv in v.values():
                    walk(vv)
                return
            if isinstance(v, list):
                for vv in v:
                    walk(vv)
                return

        walk(messages)
        # Rough heuristic for mixed CJK/English prompts.
        return max(1, (total_chars + 2) // 3)

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
        first, rest = (raw.split(maxsplit=1) + [""])[:2]
        return cls._normalize_user_command(first), rest.strip()

    @staticmethod
    def _parse_natural_model_switch(content: str) -> str | None:
        """Recognize natural-language model switch requests."""
        patterns = (
            r"^(?:请)?(?:把)?模型(?:切换|换|改)(?:到|成|为)?\s+(.+)$",
            r"^(?:请)?(?:把)?模型切换(?:到|成|为)?\s+(.+)$",
            r"^(?:请)?(?:把)?模型换成\s+(.+)$",
            r"^(?:请)?(?:把)?模型改成\s+(.+)$",
            r"^(?:请)?使用模型\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, content.strip(), flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _apply_model_provider(self, provider: LLMProvider, model: str, provider_name: str | None) -> None:
        """Update runtime provider/model state for the main loop and subagents."""
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.subagents.provider = provider
        self.subagents.model = model

    def _reset_model_provider(self) -> None:
        """Restore runtime model/provider to startup defaults."""
        if self._provider_switcher:
            provider, model, provider_name = self._provider_switcher(None)
            self._apply_model_provider(provider, model, provider_name)
            return
        self._apply_model_provider(self._default_provider, self._default_model, self._default_provider_name)

    def _switch_model_provider(self, requested_model: str) -> None:
        """Switch runtime model/provider for subsequent turns."""
        if self._provider_switcher:
            provider, model, provider_name = self._provider_switcher(requested_model)
            self._apply_model_provider(provider, model, provider_name)
            return
        self.model = requested_model
        self.subagents.model = requested_model

    def _track_path(self, raw_path: Any) -> str | None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        try:
            return str(path.resolve())
        except Exception:
            return str(path)

    def _guard_coding_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        turn_state: _TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        if not coding_enabled or not self.coding_config.enforce_read_before_write:
            return None
        if tool_name not in {"write_file", "edit_file"}:
            return None

        tracked_path = self._track_path(arguments.get("path"))
        if not tracked_path:
            return None

        if tool_name == "write_file":
            try:
                if not Path(tracked_path).exists():
                    return None
            except Exception:
                return None

        if tracked_path in turn_state.files_read:
            return None

        return (
            "Error: Coding mode requires reading a file before modifying it. "
            f"Call `read_file` for `{arguments.get('path')}` first."
        )

    def _record_tool_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        turn_state: _TurnExecutionState,
    ) -> None:
        tracked_path = self._track_path(arguments.get("path"))
        if tool_name == "read_file" and tracked_path and not result.startswith("Error:"):
            turn_state.files_read.add(tracked_path)
            return

        if tool_name in {"write_file", "edit_file"} and tracked_path and not result.startswith("Error:"):
            turn_state.files_edited.add(tracked_path)
            turn_state.edit_generation += 1
            return

        if tool_name == "exec":
            command = str(arguments.get("command", "")).strip()
            if command:
                turn_state.commands_run.append(command)
            if turn_state.edit_generation > 0:
                turn_state.verification_generation = turn_state.edit_generation

    def _needs_verification_follow_up(
        self,
        turn_state: _TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> bool:
        return (
            coding_enabled
            and self.coding_config.require_verification_after_edits
            and turn_state.edit_generation > turn_state.verification_generation
            and not turn_state.verification_prompted
        )

    @staticmethod
    def _verification_follow_up_message() -> str:
        return (
            "[Coding mode guard] You edited files in this turn but did not attempt verification.\n"
            "Use the `exec` tool to run the narrowest relevant test/build/check, or reply with a clear "
            "note explaining why verification could not be run and what remains unverified."
        )

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        temperature_override: float | None = None,
        *,
        coding_enabled: bool = False,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        temperature = self.temperature if temperature_override is None else temperature_override
        turn_state = _TurnExecutionState()

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            if response.has_tool_calls:
                if on_progress:
                    thoughts = [
                        self._strip_think(response.content),
                        response.reasoning_content,
                        *(
                            f"Thinking [{b.get('signature', '...')}]:\n{b.get('thought', '...')}"
                            for b in (response.thinking_blocks or [])
                            if isinstance(b, dict) and "signature" in b
                        ),
                    ]
                    combined_thoughts = "\n\n".join(filter(None, thoughts))
                    if combined_thoughts:
                        await on_progress(combined_thoughts)
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

        return final_content, tools_used, messages

    async def _apply_persona_output_controls(
        self,
        content: str | None,
        all_messages: list[dict[str, Any]],
        *,
        coding_enabled: bool = False,
    ) -> str | None:
        """Apply persona postprocessing (e.g. script normalization) to final text."""
        if not content:
            return content
        if coding_enabled and self.coding_config.disable_persona:
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
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            cmd, _ = self._parse_user_command(msg.content)
            if cmd == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
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
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

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
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            _, coding_enabled = self._resolve_coding_mode(session, msg.content)
            self._set_tool_context(
                channel,
                chat_id,
                msg.metadata.get("message_id"),
                coding_enabled=coding_enabled,
            )
            history = session.get_history(max_messages=self.memory_window)
            persona_hints = self._persona_hints_for_turn(msg.content, coding_enabled=coding_enabled)
            turn_temperature = self._temperature_for_turn(msg.content, coding_enabled=coding_enabled)
            messages = self.context.build_messages(
                history=history, current_message=msg.content, channel=channel, chat_id=chat_id,
                persona_runtime_hints=persona_hints,
                coding_mode=coding_enabled,
            )
            final_content, _, all_msgs = await self._run_agent_loop(
                messages,
                temperature_override=turn_temperature,
                coding_enabled=coding_enabled,
            )
            final_content = await self._apply_persona_output_controls(
                final_content,
                all_msgs,
                coding_enabled=coding_enabled,
            )
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd, cmd_arg = self._parse_user_command(msg.content)
        confirm_cmd = self.token_guard.confirm_command.strip().lower()
        cancel_cmd = self.token_guard.cancel_command.strip().lower()
        if cmd == confirm_cmd.lstrip("/"):
            cmd = confirm_cmd
        if cmd == cancel_cmd.lstrip("/"):
            cmd = cancel_cmd
        pending = self._token_guard_pending.get(key)
        plan_pending = self._plan_guard_pending.get(key)
        if pending is not None or plan_pending is not None:
            if cmd in self._TOKEN_GUARD_EXIT_ALIASES:
                cmd = cancel_cmd
            elif cmd not in {confirm_cmd, cancel_cmd}:
                pending_kind = "large task" if pending is not None else "coding plan"
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        f"There is already a pending {pending_kind}.\n"
                        f"Reply `{self.token_guard.confirm_command}` to continue it, or "
                        f"`{self.token_guard.cancel_command}` to cancel."
                    ),
                    metadata=msg.metadata or {},
                )
        if cmd == confirm_cmd:
            pending = self._token_guard_pending.pop(key, None)
            if pending:
                replay = InboundMessage(
                    channel=msg.channel,
                    sender_id=msg.sender_id,
                    chat_id=msg.chat_id,
                    content=pending,
                    metadata=msg.metadata or {},
                )
                return await self._process_message(
                    replay,
                    session_key=key,
                    on_progress=on_progress,
                    bypass_token_guard=True,
                    bypass_plan_guard=bypass_plan_guard,
                )
            plan_pending = self._plan_guard_pending.pop(key, None)
            if plan_pending:
                replay = InboundMessage(
                    channel=msg.channel,
                    sender_id=msg.sender_id,
                    chat_id=msg.chat_id,
                    content=plan_pending,
                    metadata=msg.metadata or {},
                )
                return await self._process_message(
                    replay,
                    session_key=key,
                    on_progress=on_progress,
                    bypass_token_guard=bypass_token_guard,
                    bypass_plan_guard=True,
                )
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content="No pending large task or coding plan to confirm.",
            )
        if cmd == cancel_cmd:
            removed = self._token_guard_pending.pop(key, None)
            plan_removed = self._plan_guard_pending.pop(key, None)
            if removed is None and plan_removed is None:
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="No pending large task or coding plan to cancel.",
                )
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content="Canceled pending task.",
            )
        if cmd == "/restart":
            if not self._restart_callback:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Restart is not available in this mode.",
                )
            await self._restart_callback()
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"{self._SHINCHAN_WELCOME}\n我先转一圈，马上重启回来喔～",
            )
        if cmd == "/start":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=self._SHINCHAN_WELCOME,
            )
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/start — Show welcome message\n/new — Start a new conversation\n/model — Show or switch model\n/coding — Show or set coding mode\n/stop — Stop the current task\n/restart — Restart nanobot (gateway mode)\n/help — Show available commands")
        if cmd == "/model":
            arg = cmd_arg.strip()
            if not arg:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        f"Current model: `{self.model}`\n"
                        f"Current provider: `{self.provider_name or 'unknown'}`\n"
                        "Use `/model <name>` to switch, or `/model reset` to restore default."
                    ),
                )
            if arg.lower() in {"reset", "default", "默认", "恢复默认"}:
                self._reset_model_provider()
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Model reset to default: `{self.model}` (provider: `{self.provider_name or 'unknown'}`)",
                )
            try:
                self._switch_model_provider(arg)
            except Exception as e:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Model switch failed: {e}",
                )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Model switched to: `{self.model}` (provider: `{self.provider_name or 'unknown'}`)",
            )
        if cmd == "/coding":
            arg = cmd_arg.strip().lower()
            if not self.coding_config.enabled:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Coding mode is disabled in config.",
                )
            if arg in {"", "status"}:
                setting, _ = self._resolve_coding_mode(session, "")
                workspace_repo = "yes" if self._workspace_has_repo_markers() else "no"
                active_desc = (
                    "always active"
                    if setting == "on"
                    else "always off"
                    if setting == "off"
                    else "auto-detected per request"
                )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        f"Coding mode setting: `{setting}`\n"
                        f"Auto-detect: `{self.coding_config.auto_detect}`\n"
                        f"Workspace looks like repo: `{workspace_repo}`\n"
                        f"Current behavior: {active_desc}\n"
                        "Use `/coding on`, `/coding off`, or `/coding auto`."
                    ),
                )
            if arg not in self._CODING_SESSION_MODES:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Usage: `/coding status|on|off|auto`",
                )
            session.metadata["coding_mode"] = arg
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Coding mode set to: `{arg}`",
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        _, coding_enabled = self._resolve_coding_mode(session, msg.content)
        self._set_tool_context(
            msg.channel,
            msg.chat_id,
            msg.metadata.get("message_id"),
            coding_enabled=coding_enabled,
        )
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        persona_hints = self._persona_hints_for_turn(msg.content, coding_enabled=coding_enabled)
        turn_temperature = self._temperature_for_turn(msg.content, coding_enabled=coding_enabled)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
            persona_runtime_hints=persona_hints,
            coding_mode=coding_enabled,
        )
        if (
            coding_enabled
            and not bypass_plan_guard
            and self.coding_config.require_plan_for_large_changes
            and self._looks_like_large_change_request(msg.content)
        ):
            self._plan_guard_pending[key] = msg.content
            plan_content = await self._build_large_change_plan(
                history=history,
                msg=msg,
                coding_enabled=coding_enabled,
            )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=plan_content,
                metadata=msg.metadata or {},
            )
        if self.token_guard.enabled and not bypass_token_guard:
            estimated = self._estimate_tokens(initial_messages)
            if estimated >= self.token_guard.threshold_tokens:
                self._token_guard_pending[key] = msg.content
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "Token Guard: this task is estimated to use "
                        f"~{estimated} tokens (threshold {self.token_guard.threshold_tokens}).\n"
                        f"Reply `{self.token_guard.confirm_command}` to continue, or "
                        f"`{self.token_guard.cancel_command}` to cancel."
                    ),
                    metadata=msg.metadata or {},
                )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            temperature_override=turn_temperature,
            coding_enabled=coding_enabled,
        )
        final_content = await self._apply_persona_output_controls(
            final_content,
            all_msgs,
            coding_enabled=coding_enabled,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
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

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
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

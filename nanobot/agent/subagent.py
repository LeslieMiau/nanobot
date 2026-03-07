"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import CodingConfig, ExecToolConfig
from nanobot.providers.base import LLMProvider


@dataclass
class _SubagentTurnState:
    files_read: set[str] = field(default_factory=set)
    files_edited: set[str] = field(default_factory=set)
    commands_run: list[str] = field(default_factory=list)
    verification_notes: list[str] = field(default_factory=list)
    edit_generation: int = 0
    verification_generation: int = 0
    verification_prompted: bool = False


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        coding_config: "CodingConfig | None" = None,
    ):
        from nanobot.config.schema import CodingConfig, ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.coding_config = coding_config or CodingConfig()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        coding_enabled: bool = False,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, coding_enabled)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

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
        turn_state: _SubagentTurnState,
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
        turn_state: _SubagentTurnState,
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
                if result.startswith("Error:") or "\nExit code:" in result:
                    turn_state.verification_notes.append(
                        f"Verification command reported a problem: `{command or 'exec'}`"
                    )

    def _needs_verification_follow_up(
        self,
        turn_state: _SubagentTurnState,
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
            "[Coding mode guard] You edited files in this task but did not attempt verification.\n"
            "Use the `exec` tool to run the narrowest relevant test/build/check, or explain why verification "
            "could not be run and what remains unverified."
        )

    def _display_path(self, path_str: str) -> str:
        path = Path(path_str)
        try:
            return str(path.relative_to(self.workspace))
        except ValueError:
            return str(path)

    def _apply_coding_summary(
        self,
        content: str | None,
        turn_state: _SubagentTurnState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        if not content or not coding_enabled:
            return content
        lowered = content.lower()
        if all(label in lowered for label in ("changed:", "verified:", "unverified:")):
            return content
        if not (turn_state.files_edited or turn_state.commands_run or turn_state.verification_notes):
            return content

        changed = (
            "\n".join(f"- {self._display_path(path)}" for path in sorted(turn_state.files_edited))
            if turn_state.files_edited
            else "- No files changed."
        )
        verified = (
            "\n".join(f"- `{cmd}`" for cmd in turn_state.commands_run)
            if turn_state.commands_run
            else "- No verification command recorded."
        )
        unverified_items: list[str] = []
        if turn_state.files_edited and turn_state.verification_generation < turn_state.edit_generation:
            unverified_items.append("- Edits were not verified with an exec command.")
        if turn_state.verification_notes:
            unverified_items.extend(f"- {note}" for note in turn_state.verification_notes)
        if not unverified_items:
            unverified_items.append("- None noted.")

        return (
            content.rstrip()
            + f"\n\nChanged:\n{changed}\n\nVerified:\n{verified}\n\nUnverified:\n"
            + "\n".join(unverified_items)
        )

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        coding_enabled: bool,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
            tools.register(WebFetchTool(proxy=self.web_proxy))
            
            system_prompt = self._build_subagent_prompt(coding_enabled=coding_enabled)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            turn_state = _SubagentTurnState()

            while iteration < max_iterations:
                iteration += 1

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )

                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })

                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = self._guard_coding_tool_call(
                            tool_call.name,
                            tool_call.arguments,
                            turn_state,
                            coding_enabled=coding_enabled,
                        )
                        if result is None:
                            result = await tools.execute(tool_call.name, tool_call.arguments)
                        self._record_tool_execution(tool_call.name, tool_call.arguments, result, turn_state)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    if self._needs_verification_follow_up(turn_state, coding_enabled=coding_enabled):
                        turn_state.verification_prompted = True
                        messages.append({"role": "user", "content": self._verification_follow_up_message()})
                        continue
                    final_result = response.content
                    break

            if final_result is None:
                final_result = "Task completed but no final response was generated."
            final_result = self._apply_coding_summary(
                final_result,
                turn_state,
                coding_enabled=coding_enabled,
            )

            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])
    
    def _build_subagent_prompt(self, coding_enabled: bool = False) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]

        if coding_enabled and self.coding_config.enabled:
            parts.append(
                "Coding mode is active for this task. Prioritize repository inspection, "
                "minimal edits, and concrete verification."
            )
            parts.append(
                "Your final response must end with three sections named exactly: "
                "Changed:, Verified:, and Unverified:."
            )
            coding_file = self.workspace / "CODING.md"
            if coding_file.exists():
                parts.append(coding_file.read_text(encoding="utf-8"))

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}")

        return "\n\n".join(parts)
    
    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

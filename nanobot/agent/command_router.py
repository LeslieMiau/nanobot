"""Command routing and control-flow helpers for inbound user messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.session.manager import Session

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass(frozen=True)
class TurnRequestContext:
    session: Session
    key: str
    cmd: str
    cmd_arg: str
    token_state: dict[str, Any]


@dataclass(frozen=True)
class CommandRoutingResult:
    context: TurnRequestContext | None = None
    response: OutboundMessage | None = None


class CommandRouterController:
    """Handle command parsing, pending confirmations, and operator flows."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    async def route(
        self,
        *,
        msg: InboundMessage,
        session: Session,
        key: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        bypass_token_guard: bool = False,
        bypass_plan_guard: bool = False,
    ) -> CommandRoutingResult:
        cmd, cmd_arg = self.loop._parse_user_command(msg.content)
        token_state = self.loop._token_guard_state(session)
        control = self.loop._parse_token_guard_control(msg.content)
        plan_pending = self.loop._plan_guard_pending.get(key)
        operator_action = self.loop._operator_action(session)

        if operator_action:
            if cmd in self.loop._TOKEN_GUARD_EXIT_ALIASES or self.loop._is_token_guard_cancel_message(msg.content):
                cmd = self.loop._PLAN_CANCEL_COMMAND
            elif self.loop._is_token_guard_proceed_message(msg.content):
                cmd = self.loop._PLAN_CONFIRM_COMMAND

        if control is not None:
            kind, value = control
            if kind == "mode":
                token_state["mode"] = str(value)
                self.loop._save_token_guard_state(session, token_state)
                return CommandRoutingResult(
                    response=OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Token Guard mode set to: `{token_state['mode']}`",
                    )
                )
            token_state["budget_k"] = int(value)
            self.loop._save_token_guard_state(session, token_state)
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Token Guard budget set to: `{token_state['budget_k']}k`",
                )
            )

        pending = token_state.get("pending_message")
        if plan_pending and cmd in self.loop._TOKEN_GUARD_EXIT_ALIASES:
            cmd = self.loop._PLAN_CANCEL_COMMAND
        if plan_pending and cmd not in {
            self.loop._PLAN_CONFIRM_COMMAND,
            self.loop._PLAN_CONFIRM_COMMAND.lstrip("/"),
            self.loop._PLAN_CANCEL_COMMAND,
            self.loop._PLAN_CANCEL_COMMAND.lstrip("/"),
            "/restart",
        }:
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "There is already a pending coding plan.\n"
                        f"Reply `{self.loop._PLAN_CONFIRM_COMMAND}` to continue it, or "
                        f"`{self.loop._PLAN_CANCEL_COMMAND}` to cancel."
                    ),
                    metadata=msg.metadata or {},
                )
            )
        if plan_pending and cmd in {self.loop._PLAN_CONFIRM_COMMAND, self.loop._PLAN_CONFIRM_COMMAND.lstrip("/")}:
            confirmed = self.loop._plan_guard_pending.pop(key, None)
            if confirmed:
                replay = InboundMessage(
                    channel=msg.channel,
                    sender_id=msg.sender_id,
                    chat_id=msg.chat_id,
                    content=confirmed,
                    metadata=msg.metadata or {},
                )
                return CommandRoutingResult(
                    response=await self.loop._process_message(
                        replay,
                        session_key=key,
                        on_progress=on_progress,
                        bypass_token_guard=True,
                        bypass_plan_guard=True,
                    )
                )
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="No pending large task or coding plan to confirm.",
                )
            )
        if cmd in {self.loop._PLAN_CANCEL_COMMAND, self.loop._PLAN_CANCEL_COMMAND.lstrip("/")}:
            removed = token_state.get("pending_message")
            if removed is not None:
                token_state["pending_message"] = None
                self.loop._save_token_guard_state(session, token_state)
            plan_removed = self.loop._plan_guard_pending.pop(key, None)
            operator_removed = operator_action
            if operator_removed is not None:
                self.loop._save_operator_action(session, None)
            if removed is None and plan_removed is None and operator_removed is None:
                return CommandRoutingResult(
                    response=OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="No pending large task or coding plan to cancel.",
                    )
                )
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Canceled pending task.",
                )
            )
        if operator_action and cmd in {self.loop._PLAN_CONFIRM_COMMAND, self.loop._PLAN_CONFIRM_COMMAND.lstrip("/")}:
            if operator_action.get("kind") == "cron_retry":
                return CommandRoutingResult(
                    response=await self.loop._run_operator_cron_retry(session, msg, operator_action)
                )
            self.loop._save_operator_action(session, None)
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Pending operator action is no longer available.",
                )
            )
        if cmd == "/restart":
            return CommandRoutingResult(
                response=await self.loop._handle_restart(msg, publish=False)
            )
        if operator_action and cmd not in {
            self.loop._PLAN_CONFIRM_COMMAND,
            self.loop._PLAN_CONFIRM_COMMAND.lstrip("/"),
            self.loop._PLAN_CANCEL_COMMAND,
            self.loop._PLAN_CANCEL_COMMAND.lstrip("/"),
            "/restart",
        }:
            job_id = str(operator_action.get("job_id") or "").strip()
            job_name = str(operator_action.get("job_name") or "").strip() or "unnamed"
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        f"There is already a pending cron retry for `{job_id}` ({job_name}).\n"
                        f"Reply `{self.loop._PLAN_CONFIRM_COMMAND}` or `继续/确认` to run it, or "
                        f"`{self.loop._PLAN_CANCEL_COMMAND}` or `取消` to cancel."
                    ),
                    metadata=msg.metadata or {},
                )
            )
        if pending is not None:
            if cmd in self.loop._TOKEN_GUARD_EXIT_ALIASES or self.loop._is_token_guard_cancel_message(msg.content):
                token_state["pending_message"] = None
                self.loop._save_token_guard_state(session, token_state)
                return CommandRoutingResult(
                    response=OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Canceled pending token-guard task.",
                    )
                )
            if self.loop._is_token_guard_proceed_message(msg.content):
                token_state["pending_message"] = None
                self.loop._save_token_guard_state(session, token_state)
                replay = InboundMessage(
                    channel=msg.channel,
                    sender_id=msg.sender_id,
                    chat_id=msg.chat_id,
                    content=pending,
                    metadata=msg.metadata or {},
                )
                return CommandRoutingResult(
                    response=await self.loop._process_message(
                        replay,
                        session_key=key,
                        on_progress=on_progress,
                        bypass_token_guard=True,
                        bypass_plan_guard=bypass_plan_guard,
                    )
                )
            token_state["pending_message"] = None
            self.loop._save_token_guard_state(session, token_state)

        if cmd == "/start":
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self.loop._SHINCHAN_WELCOME,
                )
            )
        if cmd == "/new":
            return CommandRoutingResult(response=await self._handle_new_session(msg, session))
        if cmd == "/help":
            return CommandRoutingResult(
                response=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "🐈 nanobot commands:\n/start — Show welcome message\n/new — Start a new conversation\n"
                        "/model — Show or switch model\n/coding — Show or set coding mode\n"
                        "/retry-cron <job_id> — Stage a cron job retry in this chat\n"
                        "/image-confirm — Generate the current staged image\n"
                        "/image-edit <feedback> — Revise the current staged image prompt\n"
                        "/image-skip — Skip the current staged image\n"
                        "/stop — Stop the current task\n/restart — Restart nanobot (gateway mode)\n"
                        "/help — Show available commands"
                    ),
                )
            )
        if cmd == "/retry-cron":
            return CommandRoutingResult(
                response=self.loop._prepare_operator_cron_retry(session, msg, cmd_arg)
            )
        if cmd == "/model":
            return CommandRoutingResult(response=self._handle_model_command(msg, session, cmd_arg))
        if cmd == "/coding":
            return CommandRoutingResult(response=self._handle_coding_command(msg, session, cmd_arg))
        if cmd == "/image-confirm":
            return CommandRoutingResult(response=await self.loop._handle_image_confirm(msg, session))
        if cmd == "/image-edit":
            return CommandRoutingResult(
                response=self.loop._handle_image_edit(msg, session, cmd_arg)
            )
        if cmd == "/image-skip":
            return CommandRoutingResult(response=self.loop._handle_image_skip(msg, session))

        return CommandRoutingResult(
            context=TurnRequestContext(
                session=session,
                key=key,
                cmd=cmd,
                cmd_arg=cmd_arg,
                token_state=token_state,
            )
        )

    async def _handle_new_session(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        lock = self.loop._consolidation_locks.setdefault(session.key, asyncio.Lock())
        self.loop._consolidating.add(session.key)
        try:
            async with lock:
                snapshot = session.messages[session.last_consolidated:]
                if snapshot:
                    temp = Session(key=session.key)
                    temp.messages = list(snapshot)
                    if not await self.loop._consolidate_memory(
                        temp,
                        provider=self.loop.provider,
                        model=self.loop.model,
                        archive_all=True,
                    ):
                        return OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Memory archival failed, session not cleared. Please try again.",
                        )
        except Exception:
            logger.exception("/new archival failed for {}", session.key)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Memory archival failed, session not cleared. Please try again.",
            )
        finally:
            self.loop._consolidating.discard(session.key)

        session.clear()
        self.loop._clear_token_guard_pending(session, save=False)
        self.loop.sessions.save(session)
        self.loop.sessions.invalidate(session.key)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="New session started.",
        )

    def _handle_model_command(self, msg: InboundMessage, session: Session, cmd_arg: str) -> OutboundMessage:
        arg = cmd_arg.strip()
        if not arg:
            current_model, current_provider_name = self.loop._effective_session_model(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    f"Current model: `{current_model}`\n"
                    f"Current provider: `{current_provider_name or 'unknown'}`\n"
                    "Use `/model list` to inspect choices, `/model <name>` or `/model <number>` "
                    "to switch, or `/model reset` to restore default."
                ),
            )
        if arg.lower() in {"list", "ls", "列表"}:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=self.loop._format_available_models(session),
            )
        if arg.lower() in {"reset", "default", "默认", "恢复默认"}:
            self.loop._reset_model_provider()
            self.loop._clear_session_model_selection(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Model reset to default: `{self.loop.model}` (provider: `{self.loop.provider_name or 'unknown'}`)",
            )
        try:
            requested_model, requested_provider_name = self.loop._resolve_model_selection_argument(session, arg)
            self.loop._switch_model_provider(requested_model, provider_name=requested_provider_name)
            self.loop._persist_session_model_selection(
                session,
                model=self.loop.model,
                provider_name=self.loop.provider_name,
            )
        except Exception as exc:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Model switch failed: {exc}",
            )
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=f"Model switched to: `{self.loop.model}` (provider: `{self.loop.provider_name or 'unknown'}`)",
        )

    def _handle_coding_command(self, msg: InboundMessage, session: Session, cmd_arg: str) -> OutboundMessage:
        arg = cmd_arg.strip().lower()
        if not self.loop.coding_config.enabled:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Coding mode is disabled in config.",
            )
        if arg in {"", "status"}:
            setting, _ = self.loop._resolve_coding_mode(session, "")
            workspace_repo = "yes" if self.loop._workspace_has_repo_markers() else "no"
            active_desc = (
                "always active"
                if setting == "on"
                else "always off"
                if setting == "off"
                else "auto-detected per request"
            )
            route_candidates, route_resolved, route_skipped = self.loop._resolve_coding_route_candidates()
            fallback_models = getattr(self.loop.coding_config, "fallback_models", []) or []
            fallback_block = "\n".join(f"- `{model}`" for model in fallback_models) if fallback_models else "- (none)"
            resolved_block = "\n".join(route_resolved) if route_resolved else "- (none)"
            skipped_block = "\n".join(route_skipped) if route_skipped else "- (none)"
            route_active = "yes" if route_candidates else "no"
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    f"Coding mode setting: `{setting}`\n"
                    f"Auto-detect: `{self.loop.coding_config.auto_detect}`\n"
                    f"Workspace looks like repo: `{workspace_repo}`\n"
                    f"Current behavior: {active_desc}\n"
                    f"Coding primary model: `{self.loop.coding_config.primary_model}`\n"
                    f"Coding model route active: `{route_active}`\n"
                    "Coding fallback models:\n"
                    f"{fallback_block}\n"
                    "Resolved coding candidates:\n"
                    f"{resolved_block}\n"
                    "Skipped coding candidates:\n"
                    f"{skipped_block}\n"
                    "Use `/coding on`, `/coding off`, or `/coding auto`."
                ),
            )
        if arg not in self.loop._CODING_SESSION_MODES:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Usage: `/coding status|on|off|auto`",
            )
        session.metadata["coding_mode"] = arg
        self.loop.sessions.save(session)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=f"Coding mode set to: `{arg}`",
        )

"""Turn execution helpers for system messages and normal user turns."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nanobot.agent.command_router import TurnRequestContext
from nanobot.agent.token_guard import TokenGuardAssessment
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


class TurnExecutorController:
    """Run system turns and regular user turns after command routing."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    async def execute_system_message(self, msg: InboundMessage) -> OutboundMessage:
        channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id))
        key = msg.session_key_override or f"{channel}:{chat_id}"
        logger.info("Processing system message from {}", msg.sender_id)
        final_content = await self.loop.process_system_turn(
            msg.content,
            session_key=key,
            channel=channel,
            chat_id=chat_id,
            stateless=False,
            disable_persona=True,
        )
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=final_content or "Background task completed.",
        )

    async def execute_user_turn(
        self,
        *,
        msg: InboundMessage,
        request: TurnRequestContext,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        bypass_token_guard: bool = False,
        bypass_plan_guard: bool = False,
    ) -> OutboundMessage | None:
        session = request.session
        self._schedule_consolidation_if_needed(session)

        _, coding_enabled = self.loop._resolve_coding_mode(session, msg.content)
        self.loop._set_tool_context(
            msg.channel,
            msg.chat_id,
            msg.metadata.get("message_id"),
            coding_enabled=coding_enabled,
            session_key=request.key,
        )
        if message_tool := self.loop.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.loop.memory_window)
        persona_hints = self.loop._persona_hints_for_turn(msg.content, coding_enabled=coding_enabled)
        turn_temperature = self.loop._temperature_for_turn(msg.content, coding_enabled=coding_enabled)
        initial_messages = self.loop.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            persona_runtime_hints=persona_hints,
            coding_mode=coding_enabled,
        )

        token_assessment: TokenGuardAssessment | None = None
        if self.loop.token_guard.enabled and not bypass_token_guard:
            mode = request.token_state["mode"]
            if mode != "off":
                token_assessment = self.loop._assess_token_guard(
                    session=session,
                    history=history,
                    msg=msg,
                    coding_enabled=coding_enabled,
                    mode=mode,
                    parsed_cmd=request.cmd,
                )
                if token_assessment.final_risk in {"large", "extreme"}:
                    request.token_state["pending_message"] = msg.content
                    self.loop._save_token_guard_state(session, request.token_state)
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=self.loop._token_guard_intercept_message(request.token_state, token_assessment),
                        metadata=msg.metadata or {},
                    )

        if (
            coding_enabled
            and not bypass_plan_guard
            and self.loop.coding_config.require_plan_for_large_changes
            and self.loop._looks_like_large_change_request(msg.content)
        ):
            self.loop._plan_guard_pending[request.key] = msg.content
            plan_content = await self.loop._build_large_change_plan(
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

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, _, all_msgs, turn_state = await self.loop._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            temperature_override=turn_temperature,
            coding_enabled=coding_enabled,
        )
        final_content = await self.loop._apply_persona_output_controls(
            final_content,
            all_msgs,
            coding_enabled=coding_enabled,
            user_text=msg.content,
        )
        final_content = self.loop._apply_coding_summary(
            final_content,
            turn_state,
            coding_enabled=coding_enabled,
        )
        if token_assessment is not None:
            final_content = self.loop._append_token_guard_estimate(final_content, token_assessment)

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self.loop._save_turn(session, all_msgs, 1 + len(history))
        self.loop.sessions.save(session)

        if (mt := self.loop.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    def _schedule_consolidation_if_needed(self, session) -> None:
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated < self.loop.memory_window or session.key in self.loop._consolidating:
            return

        self.loop._consolidating.add(session.key)
        lock = self.loop._consolidation_locks.setdefault(session.key, asyncio.Lock())
        consolidation_provider = self.loop.provider
        consolidation_model = self.loop.model

        async def _consolidate_and_unlock() -> None:
            try:
                async with lock:
                    await self.loop._consolidate_memory(
                        session,
                        provider=consolidation_provider,
                        model=consolidation_model,
                    )
            finally:
                self.loop._consolidating.discard(session.key)
                task = asyncio.current_task()
                if task is not None:
                    self.loop._consolidation_tasks.discard(task)

        task = asyncio.create_task(_consolidate_and_unlock())
        self.loop._consolidation_tasks.add(task)

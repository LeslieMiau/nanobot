"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatDecisionError(RuntimeError):
    """Raised when the heartbeat decision phase fails or returns invalid output."""


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        on_error: Callable[[str, Exception], Coroutine[Any, Any, None]] | None = None,
        on_recovery: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        decision_retry_delay_s: float = 15.0,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.on_error = on_error
        self.on_recovery = on_recovery
        self.interval_s = interval_s
        self.decision_retry_delay_s = decision_retry_delay_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None
        self._decision_retry_task: asyncio.Task | None = None
        self._pending_decision_retry_signature: str | None = None
        self._last_retry_signature: str | None = None
        self._last_error_signature: str | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _current_time_context(self) -> str:
        """Return the current local time with timezone information for heartbeat decisions."""
        now = datetime.now().astimezone()
        offset = now.strftime("%z")
        formatted_offset = "UTC"
        if offset:
            formatted_offset = f"UTC{offset[:3]}:{offset[3:]}"
        tz_name = now.tzname() or "local"
        return f"Current local time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name}, {formatted_offset})"

    def _build_decision_messages(self, content: str) -> list[dict[str, str]]:
        """Build the phase 1 heartbeat decision prompt with current-time context."""
        return [
            {
                "role": "system",
                "content": (
                    "You are a heartbeat agent. Call the heartbeat tool to report your decision. "
                    "Use the provided current local time. Return run only when at least one task in "
                    "HEARTBEAT.md appears due right now. If tasks exist but are not due now, return skip. "
                    "If the file is ambiguous, prefer skip."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{self._current_time_context()}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there are tasks that should run now.\n\n"
                    f"{content}"
                ),
            },
        ]

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat(
            messages=self._build_decision_messages(content),
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            text = (response.content or "").strip()
            if not text:
                return "skip", ""
            raise HeartbeatDecisionError(
                f"Heartbeat decision returned plain text instead of a tool call: {text[:200]}"
            )

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "").strip()

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._decision_retry_task:
            self._decision_retry_task.cancel()
            self._decision_retry_task = None
        self._pending_decision_retry_signature = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")
        await self._run_tick_content(content, allow_retry=True)

    async def _run_tick_content(self, content: str, *, allow_retry: bool) -> bool:
        """Run one heartbeat decision/execution cycle from prepared content."""
        try:
            action, tasks = await self._decide(content)

            if action != "run":
                self._last_error_signature = None
                self._last_retry_signature = None
                if allow_retry:
                    self._cancel_pending_decision_retry()
                logger.info("Heartbeat: OK (nothing to report)")
                return True

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
            self._last_error_signature = None
            self._last_retry_signature = None
            if allow_retry:
                self._cancel_pending_decision_retry()
            return True
        except HeartbeatDecisionError as e:
            logger.warning("Heartbeat decision failed: {}", e)
            await self._report_error("decision", e)
            if allow_retry:
                self._maybe_schedule_decision_retry(content, e)
            return False
        except Exception as e:
            logger.exception("Heartbeat execution failed")
            await self._report_error("execution", e)
            return False

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)

    async def _report_error(self, phase: str, error: Exception) -> None:
        """Send a best-effort deduplicated error callback."""
        signature = f"{phase}:{type(error).__name__}:{error}"
        if signature == self._last_error_signature:
            return
        self._last_error_signature = signature
        if not self.on_error:
            return
        try:
            await self.on_error(phase, error)
        except Exception as callback_error:
            logger.warning("Heartbeat error callback failed during {}: {}", phase, callback_error)

    def _maybe_schedule_decision_retry(self, content: str, error: Exception) -> None:
        """Schedule a one-shot retry for transient decision failures."""
        if not self._is_transient_decision_error(error):
            return
        if self._decision_retry_task and not self._decision_retry_task.done():
            return
        signature = f"{type(error).__name__}:{error}"
        if signature == self._last_retry_signature:
            return
        self._last_retry_signature = signature
        self._pending_decision_retry_signature = signature
        payload = {
            "phase": "decision",
            "retry_delay_s": self.decision_retry_delay_s,
            "error_type": type(error).__name__,
            "error": str(error),
        }

        async def _retry() -> None:
            try:
                logger.info(
                    "Heartbeat: scheduling one-shot decision retry in {}s",
                    self.decision_retry_delay_s,
                )
                await self._report_recovery("scheduled", payload)
                await asyncio.sleep(self.decision_retry_delay_s)
                recovered = await self._run_tick_content(content, allow_retry=False)
                if recovered:
                    await self._report_recovery("recovered", payload)
                else:
                    latest_error = self._last_error_signature
                    exhausted_payload = dict(payload)
                    if latest_error:
                        exhausted_payload["latest_error"] = latest_error
                    await self._report_recovery("exhausted", exhausted_payload)
            except asyncio.CancelledError:
                raise
            finally:
                if self._pending_decision_retry_signature == signature:
                    self._pending_decision_retry_signature = None
                self._decision_retry_task = None

        self._decision_retry_task = asyncio.create_task(_retry())

    def _cancel_pending_decision_retry(self) -> None:
        """Cancel an outstanding one-shot retry when a later attempt succeeds."""
        if self._decision_retry_task and not self._decision_retry_task.done():
            self._decision_retry_task.cancel()
        self._decision_retry_task = None
        self._pending_decision_retry_signature = None

    async def _report_recovery(self, status: str, payload: dict[str, Any]) -> None:
        """Send best-effort recovery lifecycle notifications."""
        if not self.on_recovery:
            return
        try:
            await self.on_recovery(status, payload)
        except Exception as callback_error:
            logger.warning("Heartbeat recovery callback failed during {}: {}", status, callback_error)

    @staticmethod
    def _is_transient_decision_error(error: Exception) -> bool:
        text = str(error)
        return any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in (
                r"\btimeout\b",
                r"\btimed out\b",
                r"\brate limit\b",
                r"\bquota\b",
                r"\btemporar(?:y|ily)\b",
                r"\bbackend unavailable\b",
                r"\bservice unavailable\b",
                r"\bconnection reset\b",
                r"\bconnection refused\b",
                r"\bconnection aborted\b",
                r"\bnetwork\b",
                r"\bunreachable\b",
                r"\boverloaded\b",
                r"\btry again\b",
                r"\b5\d{2}\b",
            )
        )

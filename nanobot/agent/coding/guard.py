"""Coding-mode detection and large-change planning helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import Session


class CodingGuardController:
    """Handle coding-mode detection and plan-gate prompts."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    def session_coding_mode(self, session: Session) -> str:
        mode = str(session.metadata.get("coding_mode", "auto")).strip().lower()
        return mode if mode in self.loop._CODING_SESSION_MODES else "auto"

    def workspace_has_repo_markers(self) -> bool:
        return any((self.loop.workspace / marker).exists() for marker in self.loop._REPO_MARKERS)

    @classmethod
    def looks_like_shell_command(cls, text: str, prefixes: tuple[str, ...]) -> bool:
        lowered = text.strip().lower()
        return any(lowered.startswith(prefix) for prefix in prefixes)

    @staticmethod
    def looks_like_path_or_code(text: str) -> bool:
        if "```" in text:
            return True
        if re.search(r"(?:^|\s)(?:\./|\.\./|/)?[\w.-]+/[\w./-]+", text):
            return True
        return bool(
            re.search(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|json|toml|ya?ml|md|rs|go|java|c|cc|cpp|h)\b", text)
        )

    def looks_like_coding_request(self, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in self.loop._CODING_KEYWORDS):
            return True
        if any(keyword in lowered for keyword in self.loop._REPO_KEYWORDS):
            return True
        if self.looks_like_shell_command(text, self.loop._SHELL_COMMAND_PREFIXES):
            return True
        return self.looks_like_path_or_code(text)

    def resolve_coding_mode(self, session: Session, user_text: str) -> tuple[str, bool]:
        setting = self.session_coding_mode(session)
        if not self.loop.coding_config.enabled:
            return setting, False
        if setting == "on":
            return setting, True
        if setting == "off":
            return setting, False
        if not self.loop.coding_config.auto_detect:
            return setting, False
        if self.looks_like_coding_request(user_text):
            return setting, True
        return setting, self.workspace_has_repo_markers() and any(
            token in user_text.lower() for token in ("help me", "帮我", "请你", "how do i", "怎么", "如何")
        )

    def looks_like_large_change_request(self, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in self.loop._LARGE_CHANGE_KEYWORDS):
            return True
        return bool(re.search(r"\b(?:multiple|many|several)\s+files\b", lowered))

    async def build_large_change_plan(
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
        messages = self.loop.context.build_messages(
            history=history,
            current_message=planning_request,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            persona_runtime_hints=self.loop._persona_hints_for_turn(msg.content, coding_enabled=coding_enabled),
            coding_mode=coding_enabled,
        )
        try:
            response = await self.loop.provider.chat(
                messages=messages,
                tools=None,
                model=self.loop.model,
                temperature=min(self.loop._temperature_for_turn(msg.content, coding_enabled=coding_enabled), 0.1),
                max_tokens=min(self.loop.max_tokens, 1024),
                reasoning_effort=self.loop.reasoning_effort,
            )
            candidate = self.loop._strip_think(response.content)
            if response.finish_reason == "error" or not candidate or candidate.startswith("Error:"):
                raise RuntimeError(candidate or "Failed to generate plan")
            plan = candidate
        except Exception:
            plan = (
                "Planned steps:\n"
                "1. Inspect the relevant files and tests.\n"
                "2. Implement the change with minimal edits.\n"
                "3. Run the narrowest verification and report any remaining risk."
            )
        return (
            f"{plan}\n\n"
            f"Reply `{self.loop._PLAN_CONFIRM_COMMAND}` to execute this larger change, "
            f"or `{self.loop._PLAN_CANCEL_COMMAND}` to cancel."
        )

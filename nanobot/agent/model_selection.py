"""Model selection and session-scoped provider switching helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.providers.catalog import AvailableModel

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


class ModelSelectionController:
    """Manage session-scoped model/provider selection."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    @staticmethod
    def parse_natural_model_switch(content: str) -> str | None:
        """Recognize natural-language model switch requests."""
        patterns = (
            r"^(?:请)?切换模型\s+(.+)$",
            r"^(?:请)?换模型\s+(.+)$",
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

    def apply_model_provider(self, provider: LLMProvider, model: str, provider_name: str | None) -> None:
        """Update runtime provider/model state for the main loop and subagents."""
        self.loop.provider = provider
        self.loop.provider_name = provider_name
        self.loop.model = model
        self.loop.runner.provider = provider
        self.loop.consolidator.provider = provider
        self.loop.consolidator.model = model
        self.loop.dream.provider = provider
        self.loop.dream.model = model
        self.loop.subagents.provider = provider
        self.loop.subagents.model = model

    def session_model_selection(self, session: Session) -> tuple[str | None, str | None]:
        raw = session.metadata.get(self.loop._MODEL_SELECTION_KEY)
        if not isinstance(raw, dict):
            return None, None
        model = str(raw.get("model") or "").strip() or None
        provider_name = str(raw.get("provider_name") or "").strip() or None
        return model, provider_name

    def persist_session_model_selection(
        self,
        session: Session,
        *,
        model: str,
        provider_name: str | None,
    ) -> None:
        session.metadata[self.loop._MODEL_SELECTION_KEY] = {
            "model": model,
            "provider_name": provider_name,
        }
        self.loop.sessions.save(session)

    def clear_session_model_selection(self, session: Session) -> None:
        session.metadata.pop(self.loop._MODEL_SELECTION_KEY, None)
        self.loop.sessions.save(session)

    def effective_session_model(self, session: Session) -> tuple[str, str | None]:
        model, provider_name = self.session_model_selection(session)
        return model or self.loop._default_model, provider_name or self.loop._default_provider_name

    def reset_model_provider(self) -> None:
        """Restore runtime model/provider to startup defaults."""
        self.apply_model_provider(
            self.loop._default_provider,
            self.loop._default_model,
            self.loop._default_provider_name,
        )

    def _invoke_provider_switcher(
        self,
        requested_model: str | None,
        provider_name: str | None = None,
    ) -> tuple[LLMProvider, str, str | None]:
        if self.loop._provider_switcher is None:
            raise RuntimeError("provider switcher not configured")
        try:
            return self.loop._provider_switcher(requested_model, provider_name)
        except TypeError:
            return self.loop._provider_switcher(requested_model)

    def switch_model_provider(self, requested_model: str, provider_name: str | None = None) -> None:
        """Switch runtime model/provider for subsequent turns."""
        if self.loop._provider_switcher:
            provider, model, resolved_provider_name = self._invoke_provider_switcher(
                requested_model,
                provider_name,
            )
            self.apply_model_provider(provider, model, resolved_provider_name)
            return
        self.loop.model = requested_model
        self.loop.provider_name = provider_name
        self.loop.subagents.model = requested_model

    def restore_session_model_provider(self, session: Session) -> None:
        """Restore runtime provider/model for the active session."""
        selected_model, selected_provider_name = self.session_model_selection(session)
        if not selected_model:
            self.reset_model_provider()
            return
        try:
            self.switch_model_provider(selected_model, provider_name=selected_provider_name)
        except Exception as exc:
            logger.warning(
                "Failed to restore session model {} for {}: {}",
                selected_model,
                session.key,
                exc,
            )
            self.clear_session_model_selection(session)
            self.reset_model_provider()

    def available_models_for_session(self, session: Session) -> list[AvailableModel]:
        current_model, current_provider_name = self.effective_session_model(session)
        options: list[AvailableModel] = []
        seen: set[str] = set()

        def add(model: str, provider_name: str | None = None, source: str | None = None) -> None:
            normalized = str(model or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            options.append(AvailableModel(normalized, provider_name=provider_name, source=source))

        if self.loop._available_models_provider:
            for option in self.loop._available_models_provider(current_model, current_provider_name):
                add(option.model, option.provider_name, option.source)
        else:
            add(self.loop._default_model, self.loop._default_provider_name, "default")
            add(current_model, current_provider_name, "current")
            for model in self.loop._coding_route_raw_models():
                add(model, source="coding")
        return options

    def format_available_models(self, session: Session) -> str:
        current_model, current_provider_name = self.effective_session_model(session)
        lines = [
            f"Current model: `{current_model}`",
            f"Current provider: `{current_provider_name or 'unknown'}`",
            "",
            "Available models:",
        ]
        for idx, option in enumerate(self.available_models_for_session(session), start=1):
            details: list[str] = []
            tags: list[str] = []
            if option.provider_name:
                details.append(f"provider: `{option.provider_name}`")
            if option.model == current_model:
                tags.append("current")
            if option.model == self.loop._default_model:
                tags.append("default")
            if option.source == "coding":
                tags.append("coding")
            if tags:
                details.append(", ".join(tags))
            suffix = f" ({'; '.join(details)})" if details else ""
            lines.append(f"{idx}. `{option.model}`{suffix}")
        lines.append("")
        lines.append("Use `/model <name>` or `/model <number>` to switch, or `/model reset` to restore default.")
        return "\n".join(lines)

    def resolve_model_selection_argument(self, session: Session, arg: str) -> tuple[str, str | None]:
        normalized = arg.strip()
        if not normalized.isdigit():
            return normalized, None
        index = int(normalized)
        options = self.available_models_for_session(session)
        if index < 1 or index > len(options):
            raise ValueError(f"Model index {index} is out of range. Use `/model list` to inspect available models.")
        option = options[index - 1]
        return option.model, option.provider_name
